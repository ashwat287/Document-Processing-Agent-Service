import hashlib
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from redis import Redis
from rq import Queue
from sqlalchemy import select, text

from src.config import settings
from src.db import AnalysisType, Job, JobAuditLog, JobStatus, SessionLocal, get_session
from src.errors import JobNotFoundError
from src.logging import correlation_id_var, get_logger
from src.metrics import metrics
from src.schemas import (
    HealthResponse,
    JobCreate,
    JobListParams,
    JobResponse,
    MetricsResponse,
)

router = APIRouter()
log = get_logger(__name__)


# Deterministic hash so duplicate (url, type) pairs map to the same job
def _idempotency_key(url: str, analysis_type: str) -> str:
    return hashlib.sha256(f"{url}:{analysis_type}".encode()).hexdigest()


def _job_to_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        idempotency_key=job.idempotency_key,
        document_url=job.document_url,
        analysis_type=job.analysis_type,
        status=job.status,
        result=job.result,
        error=job.error,
        tokens_used=job.tokens_used,
        metadata=job.metadata_,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED, response_model=JobResponse)
def create_job(payload: JobCreate) -> JobResponse:
    url_str = str(payload.document_url)
    key = _idempotency_key(url_str, payload.analysis_type.value)

    with get_session() as session:
        existing = session.execute(
            select(Job).where(Job.idempotency_key == key)
        ).scalar_one_or_none()

        if existing:
            log.info("duplicate_submission", idempotency_key=key, job_id=str(existing.id))
            return _job_to_response(existing)

        job = Job(
            document_url=url_str,
            analysis_type=payload.analysis_type,
            idempotency_key=key,
            status=JobStatus.PENDING,
        )
        session.add(job)
        # flush to generate job.id (UUID default) before creating the audit log FK
        session.flush()

        audit = JobAuditLog(
            job_id=job.id,
            from_status=None,
            to_status=JobStatus.PENDING.value,
            detail="Job created",
        )
        session.add(audit)
        session.commit()
        session.refresh(job)

        redis_conn = Redis.from_url(settings.REDIS_URL)
        q = Queue(connection=redis_conn)
        # Pass correlation_id so worker logs are traceable to the original request
        q.enqueue(
            "src.worker.process_job",
            str(job.id),
            correlation_id=correlation_id_var.get(""),
        )

        metrics.record_submission()
        log.info("job_submitted", job_id=str(job.id), analysis_type=payload.analysis_type.value)
        return _job_to_response(job)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: UUID) -> JobResponse:
    with get_session() as session:
        job = session.execute(
            select(Job).where(Job.id == job_id)
        ).scalar_one_or_none()

        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        return _job_to_response(job)


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs(
    status_filter: JobStatus | None = Query(None, alias="status"),
    analysis_type: AnalysisType | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[JobResponse]:
    with get_session() as session:
        query = select(Job)

        if status_filter:
            query = query.where(Job.status == status_filter)
        if analysis_type:
            query = query.where(Job.analysis_type == analysis_type)
        if date_from:
            query = query.where(Job.created_at >= date_from)
        if date_to:
            query = query.where(Job.created_at <= date_to)

        query = query.order_by(Job.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        jobs = session.execute(query).scalars().all()
        return [_job_to_response(j) for j in jobs]


@router.get("/healthz", response_model=HealthResponse)
def healthcheck() -> HealthResponse:
    db_ok = False
    queue_ok = False

    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    try:
        redis_conn = Redis.from_url(settings.REDIS_URL)
        redis_conn.ping()
        queue_ok = True
    except Exception:
        pass

    health = HealthResponse(
        status="ok" if (db_ok and queue_ok) else "degraded",
        db="ok" if db_ok else "unavailable",
        queue="ok" if queue_ok else "unavailable",
    )

    # Return 503 so load balancers and monitors can detect degraded state
    if not (db_ok and queue_ok):
        return Response(
            content=health.model_dump_json(),
            status_code=503,
            media_type="application/json",
        )

    return health


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics() -> MetricsResponse:
    try:
        return MetricsResponse(**metrics.snapshot())
    except Exception:
        return MetricsResponse()

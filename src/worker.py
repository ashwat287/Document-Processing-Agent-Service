import time
from datetime import datetime, timezone

from redis import Redis
from rq import Queue
from sqlalchemy import select

from src.agent import analyze, fetch_document, validate_output
from src.config import settings
from src.db import Job, JobAuditLog, JobStatus, SessionLocal
from src.errors import (
    DocumentFetchError,
    DocumentParseError,
    LLMRateLimitError,
    LLMTimeoutError,
    OutputValidationError,
    TokenBudgetExceeded,
)
from src.logging import component_var, correlation_id_var, get_logger, job_id_var
from src.metrics import metrics

log = get_logger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 2
BACKOFF_MAX = 60

# Separate error categories drive different retry/fail behavior below
RETRYABLE_ERRORS = (LLMTimeoutError, LLMRateLimitError)
IMMEDIATE_FAIL_ERRORS = (DocumentFetchError, DocumentParseError, TokenBudgetExceeded)


def recover_orphaned_jobs() -> int:
    """Reset jobs stuck in PROCESSING (from a previous worker crash) back to PENDING and re-enqueue them."""
    session = SessionLocal()
    try:
        orphaned = session.execute(
            select(Job).where(Job.status == JobStatus.PROCESSING)
        ).scalars().all()

        if not orphaned:
            return 0

        redis_conn = Redis.from_url(settings.REDIS_URL)
        q = Queue(connection=redis_conn)

        for job in orphaned:
            _transition(session, job, JobStatus.PENDING, "Recovered after worker crash")
            q.enqueue("src.worker.process_job", str(job.id))
            log.info("orphaned_job_recovered", job_id=str(job.id))

        session.commit()
        log.info("orphan_recovery_complete", recovered=len(orphaned))
        return len(orphaned)
    finally:
        session.close()


def _transition(session, job: Job, to_status: JobStatus, detail: str | None = None) -> None:
    from_status = job.status
    audit = JobAuditLog(
        job_id=job.id,
        from_status=from_status.value if from_status else None,
        to_status=to_status.value,
        detail=detail,
    )
    job.status = to_status
    job.updated_at = datetime.now(timezone.utc)
    session.add(audit)


def process_job(job_id: str, attempt: int = 0, correlation_id: str = "") -> None:
    component_var.set("worker")
    job_id_var.set(job_id)
    if correlation_id:
        correlation_id_var.set(correlation_id)

    log.info("job_processing_start", attempt=attempt)

    session = SessionLocal()
    try:
        job = session.execute(
            select(Job).where(Job.id == job_id)
        ).scalar_one_or_none()

        if not job:
            log.error("job_not_found")
            return

        _transition(session, job, JobStatus.PROCESSING, f"Processing attempt {attempt + 1}")
        session.commit()

        start_time = time.monotonic()

        text = fetch_document(job.document_url)
        result, prompt_tokens, completion_tokens = analyze(text, job.analysis_type.value)
        validated_result = validate_output(result, job.analysis_type.value)

        elapsed = time.monotonic() - start_time
        total_tokens = prompt_tokens + completion_tokens

        job.result = validated_result
        job.tokens_used = total_tokens
        _transition(session, job, JobStatus.COMPLETED, f"Completed in {elapsed:.2f}s")
        session.commit()

        metrics.record_completion(elapsed, total_tokens)
        log.info("job_completed", tokens=total_tokens, elapsed=round(elapsed, 2))

    # Validation gets one retry (LLM output can be non-deterministic)
    except OutputValidationError as exc:
        session.rollback()
        if attempt < 1:
            log.warning("validation_failed_retrying", error=str(exc))
            _transition(session, job, JobStatus.PENDING, f"Validation retry: {exc}")
            session.commit()
            _retry(job_id, attempt + 1, correlation_id, delay=0)
        else:
            _fail_job(session, job, "OutputValidationError", str(exc))

    # Exponential backoff: 2s, 4s, 8s ... capped at 60s
    except RETRYABLE_ERRORS as exc:
        session.rollback()
        error_type = type(exc).__name__
        if attempt < MAX_RETRIES:
            delay = min(BACKOFF_BASE * (2 ** attempt), BACKOFF_MAX)
            log.warning("retryable_error", error_type=error_type, attempt=attempt, delay=delay)
            _transition(session, job, JobStatus.PENDING, f"Retry {attempt + 1}: {exc}")
            session.commit()
            _retry(job_id, attempt + 1, correlation_id, delay=delay)
        else:
            _fail_job(session, job, error_type, str(exc))

    except IMMEDIATE_FAIL_ERRORS as exc:
        session.rollback()
        _fail_job(session, job, type(exc).__name__, str(exc))

    except Exception as exc:
        session.rollback()
        _fail_job(session, job, "UnexpectedError", str(exc))

    finally:
        session.close()


def _fail_job(session, job: Job, error_type: str, error_msg: str) -> None:
    job.error = f"[{error_type}] {error_msg}"
    _transition(session, job, JobStatus.FAILED, f"{error_type}: {error_msg}")
    session.commit()
    metrics.record_failure(error_type)
    log.error("job_failed", error_type=error_type, error=error_msg)


def _retry(job_id: str, attempt: int, correlation_id: str, delay: int) -> None:
    from datetime import timedelta

    redis_conn = Redis.from_url(settings.REDIS_URL)
    q = Queue(connection=redis_conn)
    q.enqueue_in(
        timedelta(seconds=delay),
        "src.worker.process_job",
        job_id,
        attempt=attempt,
        correlation_id=correlation_id,
    )


if __name__ == "__main__":
    import subprocess
    import sys

    from src.db import init_db

    init_db()
    recover_orphaned_jobs()
    sys.exit(subprocess.call([
        "rq", "worker",
        "--url", settings.REDIS_URL,
        "--with-scheduler",
    ]))

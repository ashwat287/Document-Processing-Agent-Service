from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, HttpUrl

from src.db import AnalysisType, JobStatus


class JobCreate(BaseModel):
    document_url: HttpUrl
    analysis_type: AnalysisType


class JobResponse(BaseModel):
    id: UUID
    idempotency_key: str
    document_url: str
    analysis_type: AnalysisType
    status: JobStatus
    result: dict[str, Any] | None = None
    error: str | None = None
    tokens_used: int | None = 0
    metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobListParams(BaseModel):
    status: JobStatus | None = None
    analysis_type: AnalysisType | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    page: int = 1
    page_size: int = 20


class HealthResponse(BaseModel):
    status: str
    db: str
    queue: str


class MetricsResponse(BaseModel):
    jobs_submitted: int = 0
    jobs_completed: int = 0
    jobs_failed: int = 0
    total_tokens: int = 0
    avg_processing_time: float = 0.0
    p95_processing_time: float = 0.0
    error_counts_by_type: dict[str, int] = {}

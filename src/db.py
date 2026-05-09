import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from src.config import settings

Base = declarative_base()


class AnalysisType(str, enum.Enum):
    SUMMARY = "summary"
    EXTRACTION = "extraction"
    CLASSIFICATION = "classification"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key = Column(String(64), unique=True, nullable=False, index=True)
    document_url = Column(Text, nullable=False)
    analysis_type = Column(Enum(AnalysisType), nullable=False)
    status = Column(Enum(JobStatus), nullable=False, default=JobStatus.PENDING)
    result = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    tokens_used = Column(Integer, nullable=True, default=0)
    # Extensible metadata with schema_version for future-proofing
    metadata_ = Column("metadata", JSONB, nullable=True, default=lambda: {"schema_version": 1})
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class JobAuditLog(Base):
    __tablename__ = "job_audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False, index=True)
    from_status = Column(String(20), nullable=True)
    to_status = Column(String(20), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    detail = Column(Text, nullable=True)


Index("ix_jobs_status", Job.status)
Index("ix_jobs_created_at", Job.created_at)

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


# No Alembic — single schema version, CREATE TABLE IF NOT EXISTS is sufficient
def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    return SessionLocal()

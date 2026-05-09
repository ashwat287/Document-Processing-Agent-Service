import logging
from contextvars import ContextVar

import structlog

from src.config import settings

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
job_id_var: ContextVar[str] = ContextVar("job_id", default="")
component_var: ContextVar[str] = ContextVar("component", default="api")


def add_context(logger: logging.Logger, method_name: str, event_dict: dict) -> dict:
    event_dict["correlation_id"] = correlation_id_var.get("")
    job_id = job_id_var.get("")
    if job_id:
        event_dict["job_id"] = job_id
    event_dict["component"] = component_var.get("api")
    return event_dict


def setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            add_context,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(format="%(message)s", level=getattr(logging, settings.LOG_LEVEL.upper()))


def get_logger(name: str = __name__) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)

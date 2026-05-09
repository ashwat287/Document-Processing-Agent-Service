import io
import re

import httpx
import litellm
import pdfplumber
from pydantic import BaseModel, field_validator

from src.config import settings
from src.errors import (
    DocumentFetchError,
    DocumentParseError,
    LLMRateLimitError,
    LLMTimeoutError,
    OutputValidationError,
    TokenBudgetExceeded,
)
from src.logging import get_logger
from src.prompts import PROMPTS

log = get_logger(__name__)

# Common prompt injection patterns — logged as warnings, not blocked
# (blocking would cause false positives on legitimate content)
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"disregard\s+(all\s+)?above",
    r"you\s+are\s+now\s+a",
    r"system\s*:\s*",
]


# --- Output validation schemas ---

class SummarySection(BaseModel):
    title: str
    content: str
    confidence: float

    @field_validator("confidence")
    @classmethod
    def check_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be between 0.0 and 1.0, got {v}")
        return v


class SummaryOutput(BaseModel):
    sections: list[SummarySection]

    @field_validator("sections")
    @classmethod
    def check_non_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("sections must not be empty")
        return v


class ExtractionOutput(BaseModel):
    entities: list[str]
    dates: list[str]
    amounts: list[str]
    parties: list[str]
    key_terms: list[str]


class ClassificationOutput(BaseModel):
    category: str
    reasoning: str
    confidence: float

    @field_validator("confidence")
    @classmethod
    def check_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be between 0.0 and 1.0, got {v}")
        return v


VALIDATION_SCHEMAS = {
    "summary": SummaryOutput,
    "extraction": ExtractionOutput,
    "classification": ClassificationOutput,
}


def fetch_document(url: str) -> str:
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True, verify=settings.SSL_VERIFY) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise DocumentFetchError(f"Timeout fetching {url}") from exc
    except httpx.HTTPStatusError as exc:
        raise DocumentFetchError(f"HTTP {exc.response.status_code} fetching {url}") from exc
    except httpx.RequestError as exc:
        raise DocumentFetchError(f"Request error fetching {url}: {exc}") from exc

    content_length = len(response.content)
    if content_length > settings.MAX_DOCUMENT_SIZE:
        raise DocumentFetchError(
            f"Document too large: {content_length} bytes (max {settings.MAX_DOCUMENT_SIZE})"
        )

    content_type = response.headers.get("content-type", "")

    if "application/pdf" in content_type or url.lower().endswith(".pdf"):
        return _extract_pdf_text(response.content)

    text = response.text
    _check_prompt_injection(text, url)
    return text


def _extract_pdf_text(content: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = []
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
            if not pages:
                raise DocumentParseError("PDF contains no extractable text")
            text = "\n\n".join(pages)
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError(f"Failed to parse PDF: {exc}") from exc

    _check_prompt_injection(text, "pdf-content")
    return text


def _check_prompt_injection(text: str, source: str) -> None:
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            log.warning(
                "prompt_injection_pattern_detected",
                source=source,
                pattern=pattern,
            )
            break


def analyze(text: str, analysis_type: str) -> tuple[dict, int, int]:
    prompt_config = PROMPTS[analysis_type]
    user_message = prompt_config["user"].format(document_text=text)

    kwargs: dict = {
        "model": settings.LLM_MODEL,
        "api_key": settings.LLM_API_KEY,
        "messages": [
            {"role": "system", "content": prompt_config["system"]},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": settings.MAX_TOKENS_PER_JOB,
        # JSON mode ensures structured output rather than free text
        "response_format": {"type": "json_object"},
        "timeout": 60,
    }
    if settings.LLM_API_BASE:
        kwargs["api_base"] = settings.LLM_API_BASE

    try:
        response = litellm.completion(**kwargs)
    except litellm.exceptions.RateLimitError as exc:
        raise LLMRateLimitError(str(exc)) from exc
    except litellm.exceptions.Timeout as exc:
        raise LLMTimeoutError(str(exc)) from exc
    except Exception as exc:
        raise LLMTimeoutError(f"LLM call failed: {exc}") from exc

    usage = response.usage
    prompt_tokens = usage.prompt_tokens or 0
    completion_tokens = usage.completion_tokens or 0
    total_tokens = prompt_tokens + completion_tokens

    if total_tokens > settings.MAX_TOKENS_PER_JOB:
        raise TokenBudgetExceeded(
            f"Token usage {total_tokens} exceeds budget {settings.MAX_TOKENS_PER_JOB}"
        )

    import json
    try:
        result = json.loads(response.choices[0].message.content)
    except (json.JSONDecodeError, IndexError, AttributeError) as exc:
        raise OutputValidationError(f"LLM returned invalid JSON: {exc}") from exc

    return result, prompt_tokens, completion_tokens


# Structural validation via Pydantic — never asks the LLM to self-grade
def validate_output(result: dict, analysis_type: str) -> dict:
    schema_cls = VALIDATION_SCHEMAS.get(analysis_type)
    if not schema_cls:
        raise OutputValidationError(f"Unknown analysis type: {analysis_type}")

    try:
        validated = schema_cls.model_validate(result)
    except Exception as exc:
        raise OutputValidationError(f"Output validation failed: {exc}") from exc

    return validated.model_dump()

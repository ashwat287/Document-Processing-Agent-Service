from src.agent import (
    ClassificationOutput,
    ExtractionOutput,
    SummaryOutput,
    validate_output,
)
from src.errors import OutputValidationError

import pytest


def test_validate_summary_valid():
    data = {
        "sections": [
            {"title": "Intro", "content": "Overview of the doc", "confidence": 0.9},
            {"title": "Details", "content": "More info", "confidence": 0.85},
        ]
    }
    result = validate_output(data, "summary")
    assert len(result["sections"]) == 2
    assert result["sections"][0]["confidence"] == 0.9


def test_validate_summary_empty_sections():
    with pytest.raises(OutputValidationError):
        validate_output({"sections": []}, "summary")


def test_validate_summary_bad_confidence():
    data = {
        "sections": [
            {"title": "Intro", "content": "Text", "confidence": 1.5},
        ]
    }
    with pytest.raises(OutputValidationError):
        validate_output(data, "summary")


def test_validate_extraction_valid():
    data = {
        "entities": ["Acme Corp"],
        "dates": ["2025-01-01"],
        "amounts": ["$100"],
        "parties": ["John Doe"],
        "key_terms": ["contract"],
    }
    result = validate_output(data, "extraction")
    assert result["entities"] == ["Acme Corp"]


def test_validate_extraction_empty_arrays():
    data = {
        "entities": [],
        "dates": [],
        "amounts": [],
        "parties": [],
        "key_terms": [],
    }
    result = validate_output(data, "extraction")
    assert result["entities"] == []


def test_validate_classification_valid():
    data = {
        "category": "contract",
        "reasoning": "Contains legal terms and parties",
        "confidence": 0.95,
    }
    result = validate_output(data, "classification")
    assert result["category"] == "contract"


def test_validate_classification_bad_confidence():
    data = {
        "category": "report",
        "reasoning": "Looks like a report",
        "confidence": -0.1,
    }
    with pytest.raises(OutputValidationError):
        validate_output(data, "classification")


def test_validate_unknown_type():
    with pytest.raises(OutputValidationError):
        validate_output({}, "unknown_type")

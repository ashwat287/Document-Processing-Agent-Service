from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.app import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_create_job_validates_payload(client):
    response = client.post("/jobs", json={
        "document_url": "not-a-url",
        "analysis_type": "summary",
    })
    assert response.status_code == 422

    response = client.post("/jobs", json={
        "document_url": "https://example.com/doc.pdf",
        "analysis_type": "invalid_type",
    })
    assert response.status_code == 422


def test_healthz_endpoint_exists(client):
    response = client.get("/healthz")
    assert response.status_code in (200, 503)


def test_metrics_endpoint(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "jobs_submitted" in data
    assert "jobs_completed" in data


def test_idempotency_key_deterministic():
    from src.routes import _idempotency_key
    key1 = _idempotency_key("https://example.com/doc.pdf", "summary")
    key2 = _idempotency_key("https://example.com/doc.pdf", "summary")
    key3 = _idempotency_key("https://example.com/doc.pdf", "extraction")
    assert key1 == key2
    assert key1 != key3
    assert len(key1) == 64  # sha256 hex


def test_get_nonexistent_job(client):
    with patch("src.routes.get_session") as mock_get_session:
        mock_session = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_session)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_ctx
        mock_session.execute.return_value.scalar_one_or_none.return_value = None

        response = client.get("/jobs/00000000-0000-0000-0000-000000000099")
        assert response.status_code == 404

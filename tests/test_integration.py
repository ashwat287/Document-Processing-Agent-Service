import time

import httpx

BASE_URL = "http://localhost:8000"
TEST_PDF_URL = "https://arxiv.org/pdf/1706.03762"  # Attention Is All You Need


def test_submit_and_complete_job():
    with httpx.Client(base_url=BASE_URL, timeout=120) as client:
        response = client.post("/jobs", json={
            "document_url": TEST_PDF_URL,
            "analysis_type": "summary",
        })
        assert response.status_code == 202
        job = response.json()
        job_id = job["id"]
        assert job["status"] in ("pending", "completed")  # may hit idempotent existing job

        # Poll until completed or failed (max 120s)
        if job["status"] == "pending":
            for _ in range(60):
                r = client.get(f"/jobs/{job_id}")
                assert r.status_code == 200
                data = r.json()
                if data["status"] in ("completed", "failed"):
                    break
                time.sleep(2)
        else:
            data = job

        assert data["status"] == "completed", f"Job failed: {data.get('error')}"
        assert data["result"] is not None
        assert "sections" in data["result"]
        assert len(data["result"]["sections"]) >= 1
        assert data["tokens_used"] > 0


def test_idempotent_submission():
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        payload = {
            "document_url": TEST_PDF_URL,
            "analysis_type": "classification",
        }
        r1 = client.post("/jobs", json=payload)
        r2 = client.post("/jobs", json=payload)
        assert r1.status_code == 202
        assert r2.status_code == 202
        assert r1.json()["id"] == r2.json()["id"]


def test_healthz():
    with httpx.Client(base_url=BASE_URL, timeout=10) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        data = r.json()
        assert data["db"] == "ok"
        assert data["queue"] == "ok"


def test_metrics():
    with httpx.Client(base_url=BASE_URL, timeout=10) as client:
        r = client.get("/metrics")
        assert r.status_code == 200
        data = r.json()
        assert "jobs_submitted" in data

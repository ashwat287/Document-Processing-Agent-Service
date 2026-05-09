.PHONY: help setup setup-loadtest up down restart rebuild logs health metrics submit demo unit integration test load inspect clear-db

DOC_URL ?= https://arxiv.org/pdf/1706.03762
ANALYSIS_TYPE ?= summary

help:
	@echo "Available targets:"
	@echo "  make setup            # Install app dependencies"
	@echo "  make setup-loadtest   # Install load-test dependencies"
	@echo "  make up               # Start docker stack"
	@echo "  make down             # Stop docker stack"
	@echo "  make restart          # Restart docker stack"
	@echo "  make rebuild          # Rebuild and start docker stack (fresh DB volumes)"
	@echo "  make logs             # Tail docker logs"
	@echo "  make health           # Check API health"
	@echo "  make submit DOC_URL=<url> ANALYSIS_TYPE=<summary|extraction|classification>"
	@echo "                      # Submit a job (defaults: $(DOC_URL), $(ANALYSIS_TYPE))"
	@echo "  make demo DOC_URL=<url> ANALYSIS_TYPE=<summary|extraction|classification>"
	@echo "                      # Submit and poll job to completion"
	@echo "  make unit             # Run unit tests"
	@echo "  make integration      # Run integration tests"
	@echo "  make test             # Run all tests"
	@echo "  make load             # Run locust load test"
	@echo "  make metrics          # Show operational metrics"
	@echo "  make inspect JOB_ID=<uuid>  # Inspect a job by id"
	@echo "  make clear-db         # Drop all jobs and audit logs"

setup:
	uv sync

setup-loadtest:
	uv sync --group loadtest

up:
	docker compose up --build -d

down:
	docker compose down

restart: down up

rebuild:
	docker compose down -v
	docker compose up --build -d

logs:
	docker compose logs -f --tail=100

health:
	curl -s http://localhost:8000/healthz | python3 -m json.tool

metrics:
	curl -s http://localhost:8000/metrics | python3 -m json.tool

submit:
	@echo "Submitting: DOC_URL=$(DOC_URL) ANALYSIS_TYPE=$(ANALYSIS_TYPE)"
	@curl -s -X POST http://localhost:8000/jobs \
		-H "Content-Type: application/json" \
		-d '{"document_url": "$(DOC_URL)", "analysis_type": "$(ANALYSIS_TYPE)"}' | python3 -m json.tool

demo:
	@set -e; \
	echo "Using document URL: $(DOC_URL)"; \
	echo "Using analysis type: $(ANALYSIS_TYPE)"; \
	JOB_JSON=$$(curl -s -X POST http://localhost:8000/jobs \
		-H "Content-Type: application/json" \
		-d '{"document_url": "$(DOC_URL)", "analysis_type": "$(ANALYSIS_TYPE)"}'); \
	echo "Submitted job:"; \
	echo "$$JOB_JSON" | python3 -m json.tool; \
	JOB_ID=$$(echo "$$JOB_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])"); \
	echo "Polling job $$JOB_ID ..."; \
	for i in $$(seq 1 60); do \
		STATUS_JSON=$$(curl -s http://localhost:8000/jobs/$$JOB_ID); \
		STATUS=$$(echo "$$STATUS_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', ''))"); \
		echo "[$$i] status=$$STATUS"; \
		if [ "$$STATUS" = "completed" ] || [ "$$STATUS" = "failed" ]; then \
			echo "Final response:"; \
			echo "$$STATUS_JSON" | python3 -m json.tool; \
			exit 0; \
		fi; \
		sleep 2; \
	done; \
	echo "Timed out waiting for job completion"; \
	exit 1

unit:
	PYTHONPATH=. uv run pytest tests/test_api.py tests/test_agent.py -v

integration:
	PYTHONPATH=. uv run pytest tests/test_integration.py -v

test:
	PYTHONPATH=. uv run pytest tests/ -v

load:
	uv run locust -f loadtest/locustfile.py --host=http://localhost:8000 --users=50 --spawn-rate=10 --run-time=60s --headless

inspect:
	@if [ -z "$(JOB_ID)" ]; then \
		echo "Usage: make inspect JOB_ID=<job-uuid>"; \
		exit 1; \
	fi
	docker compose exec api python cli.py inspect-job $(JOB_ID)
clear-db:
	@echo "Stopping services to release database locks..."
	docker compose stop api worker 2>/dev/null || true
	sleep 2
	docker compose exec postgres psql -U postgres -d docprocessor -c "DROP TABLE IF EXISTS job_audit_log, jobs CASCADE;"
	docker compose exec redis redis-cli FLUSHDB
	@echo "Database and cache cleared"

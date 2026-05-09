# Document Processing Agent Service

Async document processing service that accepts document URLs, queues them for AI analysis (summary, extraction, classification), and returns structured results. The service is designed for production-shaped behavior: asynchronous processing, idempotency, failure handling, persistence, and operational visibility.

## Project Overview

High-level flow:

1. Client submits a job to `POST /jobs` with `document_url` and `analysis_type`.
2. API stores the job as `PENDING`, logs an audit event, and enqueues it in Redis.
3. Worker dequeues the job, fetches the document, runs LLM analysis, validates output schema, and persists result.
4. Client polls `GET /jobs/:id` to get status and final output.

System path: FastAPI -> Redis (`rq`) -> Worker -> LiteLLM -> PostgreSQL.

For diagrams and state machine, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Quick Start

```bash
# 1) Clone and configure
git clone <repo-url> && cd robotic_imaging
cp .env.example .env
# Edit .env and set LLM_API_KEY (and LLM_MODEL if needed)

# 2) Install dependencies
make setup
make setup-loadtest

# 3) Start the stack
make up

# 4) Verify dependencies are healthy
make health

# 5) Run a full end-to-end demo (submit + poll)
make demo DOC_URL=https://arxiv.org/pdf/1706.03762 ANALYSIS_TYPE=summary
```

## Makefile Commands

```bash
make help
make up
make down
make rebuild
make logs
make submit DOC_URL=<url> ANALYSIS_TYPE=<summary|extraction|classification>
make demo DOC_URL=<url> ANALYSIS_TYPE=<summary|extraction|classification>
make unit
make integration
make test
make load
make inspect JOB_ID=<job-uuid>
make clear-db
```

## API Reference

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/jobs` | Submit document URL + analysis type. Returns `202` with job details. Idempotent by `(url + type)`. |
| GET | `/jobs/:id` | Retrieve one job status/result/error. |
| GET | `/jobs` | List jobs with filters: `status`, `analysis_type`, `date_from`, `date_to`, `page`, `page_size`. |
| GET | `/healthz` | Real dependency check (`SELECT 1` on Postgres, `PING` on Redis). Returns `503` on dependency failure. |
| GET | `/metrics` | Operational metrics: submissions/completions/failures, token spend, avg/p95 latency, error counts. |

Idempotency behavior:

- Duplicate `POST /jobs` with the same `document_url` and `analysis_type` returns the existing job instead of creating a new one.
- Backed by a unique `sha256(url + analysis_type)` key in the database.

## Configuration

Primary environment variables (see `.env.example`):

- `DATABASE_URL`
- `REDIS_URL`
- `LLM_MODEL`
- `LLM_API_KEY`
- `LLM_API_BASE` (optional)
- `MAX_TOKENS_PER_JOB`
- `MAX_DOCUMENT_SIZE`
- `SSL_VERIFY`
- `WORKER_CONCURRENCY`
- `LOG_LEVEL`

No secrets or URLs are hardcoded in application code.

## Reliability and Failure Handling

Job status lifecycle:

- `PENDING` -> `PROCESSING` -> `COMPLETED`
- `PENDING` -> `PROCESSING` -> `FAILED`
- `PROCESSING` -> `PENDING` (retry path)

Failure policy:

- Retryable: `LLMTimeoutError`, `LLMRateLimitError` with exponential backoff (`2s * 2^attempt`, capped at `60s`, max 3 retries).
- Validation retry: one retry for `OutputValidationError`, then fail.
- Immediate fail: `DocumentFetchError`, `DocumentParseError`, `TokenBudgetExceeded`.

Each state transition is persisted in `job_audit_log` for traceability.

## Agent Behavior

Per job, the worker executes:

1. `fetch_document()`
  - Downloads content via `httpx`.
  - Parses PDF text with `pdfplumber`.
  - Enforces document size limits.
  - Scans for common prompt-injection patterns and logs warnings.
2. `analyze()`
  - Calls `litellm.completion()` with JSON output mode.
  - Tracks prompt/completion token usage.
  - Enforces per-job token budget.
3. `validate_output()`
  - Pydantic schema validation (structural validation, not LLM self-grading).

## Observability

- Structured JSON logs via `structlog`.
- Correlation ID flows API -> queue -> worker.
- Metrics are Redis-backed shared counters (cross-process), exposed at `/metrics`.

Alerting condition:

- Page when error rate exceeds 10% over a 5-minute window.
- Rationale: isolated failures are expected; sustained failures indicate systemic issues.

## Test Documents

| Document | URL | Why it is included |
|---|---|---|
| Attention Is All You Need | `https://arxiv.org/pdf/1706.03762` | Dense technical paper, good for summary and extraction depth. |
| GPT-3 Paper | `https://arxiv.org/pdf/2005.14165` | Long document to stress token usage and parsing. |
| GPT-4 Technical Report | `https://arxiv.org/pdf/2303.08774` | Useful for classification and structured extraction quality. |
| W3C Dummy PDF | `https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf` | Minimal edge-case PDF for small-input validation. |
| BERT Paper | `https://arxiv.org/pdf/1810.04805` | Additional technical variation for extraction fields. |

## Testing

```bash
# Unit tests
make unit

# Integration tests (requires stack running)
make integration

# Full test suite
make test

# Load test (50 users for 60s)
make load
```

CLI debugging:

```bash
make inspect JOB_ID=<job-uuid>
make clear-db
```

## Load Test Results

Run profile: 50 concurrent users, spawn rate 10, 60s, headless Locust.

```text
Type     Name                # reqs      # fails |    Avg     Min     Max    Med |   req/s  failures/s
GET      /healthz              2997     0(0.00%) |     24       3     161     15 |   50.19        0.00
POST     /jobs                 2901     0(0.00%) |     42      10     229     30 |   48.59        0.00
GET      /metrics              3001     0(0.00%) |     10       1     121      6 |   50.26        0.00
      Aggregated            8899     0(0.00%) |     25       1     229     15 |  149.04        0.00

Response time percentiles (approx):
Aggregated p50: 15ms, p95: 86ms, p99: 140ms
```

Primary bottleneck remains LLM-side latency and provider limits, not queue/database throughput.

## Design Choices and Tradeoffs

Every major decision below includes what was gained and what was given up. For diagrams and component descriptions, see [ARCHITECTURE.md](ARCHITECTURE.md).

### rq for async job processing

rq provides a single `Queue` and `Worker` with plain-function jobs and a built-in failed-job registry for crash recovery. Its minimal API surface keeps the operational footprint small for a single-queue, single-worker service.

**Tradeoff**: rq is Redis-only and has no built-in periodic tasks. If the service later needed multi-broker support or scheduled recurring analysis, the queue layer would need to be replaced. For fire-and-forget async processing, rq is simpler to operate and debug.

### JSONB for results, no migration tooling

Each analysis type returns a different JSON structure. JSONB stores them all in one column without separate tables or a rigid column schema. `init_db()` uses `CREATE TABLE IF NOT EXISTS`. A `schema_version` field in the metadata column hedges for future migration needs.

**Tradeoff**: Schema changes require manual migration or a fresh DB. Acceptable for a greenfield project; a production service with live data would need a migration framework.

### Provider-agnostic LLM access via LiteLLM

All LLM calls go through `litellm.completion()`. Switching providers requires only changing the `LLM_MODEL` env var. No provider-specific SDK imports in application code.

**Tradeoff**: The abstraction layer can lag behind provider-specific features (streaming, tool use, vision). If the service needed fine-grained provider control, the abstraction would get in the way. For text-in/JSON-out analysis, it is sufficient.

### SHA-256 idempotency key

`sha256(url + analysis_type)` is stored as a unique DB constraint. Duplicate `POST /jobs` returns the existing job without re-enqueuing.

**Tradeoff**: Users cannot resubmit the same document for re-analysis. A production system would want idempotency key TTLs or a "force resubmit" flag. For this scope, deduplication is the higher priority.

### Structural validation via Pydantic

Output validation uses Pydantic schema checks (required fields, value ranges, types) — deterministic, fast, and free. No second LLM call to self-grade.

**Tradeoff**: Structural checks cannot catch semantic errors (wrong classification, hallucinated summary). A production system could layer embedding-similarity checks or human review. Pydantic validation reliably catches the failures that matter (malformed JSON, missing fields, out-of-range confidence scores).

### Prompt injection: log, don't block

Injection patterns in document text trigger a warning log but don't block processing. Blocking would cause false positives on legitimate documents (e.g., security training manuals discussing injection).

**Tradeoff**: A determined attacker could inject instructions. Mitigation is architectural: JSON mode constrains output format, and Pydantic rejects anything that doesn't match the expected schema. The residual risk is valid-schema-but-wrong-content — the same failure mode as any LLM hallucination.

### Redis-backed metrics

The API and worker run as separate processes (separate Docker containers). Process-local counters in the API would never see worker completions. Redis provides shared O(1) counters both processes can write to.

**Tradeoff**: If Redis is down, the metrics endpoint returns a graceful fallback (zeros) rather than real data. Querying the database for aggregates on each request would avoid this dependency but would be expensive and wouldn't capture processing times without extra columns.

### Correlation ID via ContextVar

Middleware sets a `ContextVar` once per request. Every log call in that request's stack automatically includes the correlation ID. The same value is forwarded to the rq worker via job arguments, maintaining the trace cross-process.

**Tradeoff**: ContextVars are implicit state. Explicit parameter passing would be easier to trace in code, but would pollute every function signature with `correlation_id: str`. For an 11-module service, automatic log enrichment is the simpler approach.

### HTTP 202 Accepted for job creation

`POST /jobs` returns 202 because the job is accepted for processing but not yet complete. 201 would imply the resource is fully ready, which is incorrect for an async workflow.

**Tradeoff**: Some REST clients default-handle 201 but not 202 in their success paths. The semantic accuracy is worth the minor compatibility consideration.

### Single Docker image, two entrypoints

One Dockerfile, one image. `docker-compose.yml` runs two containers with different commands (`uvicorn` vs `rq worker`). This guarantees both processes run identical code and dependencies, eliminating version-skew risk.

**Tradeoff**: The image includes dependencies each process doesn't use (API doesn't need pdfplumber, worker doesn't need uvicorn). At scale, separate images with shared base layers would reduce container size. For this scope, a single image is simpler.

### Exponential backoff with cap

Retryable errors use `min(2s × 2^attempt, 60s)`, max 3 retries. With a single worker processing jobs sequentially, per-job backoff is sufficient.

**Tradeoff**: During a prolonged LLM outage, each job exhausts its retries individually rather than failing fast. A global failure-tracking mechanism would prevent wasted retries but adds complexity for a single-worker deployment.

### Flat `src/` package

11 modules in a single directory, no nesting. Every module has one responsibility, visible from a directory listing.

**Tradeoff**: If the service grew to 30+ modules, flat structure would become unwieldy. At that point, domain-based grouping would be warranted.

## What I Cut (and Why)

1. **Migration tooling** — The schema is stable and single-version. `CREATE TABLE IF NOT EXISTS` is sufficient for greenfield. Cost of adding: migration chain management, config files, revision history. Benefit deferred until schema evolves on live data.

2. **Worker autoscaling** — Tuning concurrency requires load profiling against the LLM provider's rate limits. A single worker with sequential processing avoids thundering-herd API calls. Cost of adding: process manager or orchestrator-level autoscaling, rate-limit coordination. Benefit: higher throughput under sustained load.

3. **API rate limiting** — The load test shows the API handles 150 req/s without issue. Rate limiting matters when the service is multi-tenant or public-facing; this is an internal tool. Cost of adding: middleware + token bucket + 429 response handling. Benefit: protection against accidental abuse.

4. **Document caching** — On retry, the worker re-fetches the document. Caching would avoid redundant downloads but adds cache invalidation complexity and storage management. At 3 retries max, the wasted bandwidth is negligible.

5. **Prometheus-format metrics** — The `/metrics` endpoint returns JSON. Prometheus exposition format would enable dashboarding but requires a metrics library and changes the response format. The JSON endpoint is queryable by any HTTP client without additional tooling.

6. **Distributed tracing** — Correlation IDs in structured logs provide sufficient traceability for a two-process system (API + worker). Full distributed tracing spans would add value in a multi-service architecture with fan-out calls. Cost: SDK setup, collector sidecar, trace storage. For this scope, structured logs are enough.

## What I Would Build Next

1. Optional webhook callback on job completion/failure.
2. Object storage (S3/blob) for source documents and reproducible processing.
3. Prometheus-compatible metrics endpoint and dashboarding.
4. Queue priority tiers for latency-sensitive jobs.
5. Per-tenant budgets and quota enforcement.
6. Automatic document type detection beyond URL/content-type heuristics.

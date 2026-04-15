# Changelog

All notable changes to **Async PDF Processor** are described in this file.  
Versions follow **v.0.0.x** labels used in the UI (`frontend/src/appMeta.ts`) and documentation footers.

**Code author:** Arkadiusz Czerwinski

---

## v.0.0.2 — 14 April 2026

Hardening and product-clarity release. Closes the gaps listed under “Top Rejection Reasons” in `docs/TODO.md` (evaluation of the earlier delivery) and aligns implementation with `docs/IMPLEMENTATION_STATUS.md` (Sections 1–2 and §9).

### Parsing and product clarity

- Explicit parser identifiers end-to-end (API, worker, frontend, locales): `pypdf`, `gemini-2.5-flash-pdf`, `gemini-2.5-flash-text`, legacy `gemini-2.5-flash`, `mistral`, `mistral-ocr`.
- Native Gemini PDF path (`gemini-2.5-flash-pdf`, inline PDF bytes) without silent fallback to text-only formatting; oversized PDFs return **413** where applicable.
- Formatter path (`gemini-2.5-flash-text`: PyPDF text → Gemini markdown) documented; migration notes in `README.md`.
- Scanned / image-heavy PDF behavior documented; tests for low-text cases (e.g. `tests/test_pr_fr_scanned_pdf.py`).
- `mistral-ocr`: PyMuPDF rasters → Mistral vision per page (`MISTRAL_OCR_MAX_PAGES`, `MISTRAL_OCR_RASTER_ZOOM`); mock supports vision payloads for local runs.

### Concurrency, backpressure, and resilience (API + worker)

- Blocking PDF/LLM work off the asyncio event loop via bounded `ThreadPoolExecutor` (`BLOCKING_POOL_MAX_WORKERS`, `_run_blocking` / `_run_blocking_timed`).
- LLM capacity: `LLM_MAX_INFLIGHT`, `LLM_SLOT_ACQUIRE_TIMEOUT_SECONDS`; **503** + `Retry-After` when saturated; per-file errors on multi-file sync under pressure.
- Multi-file synchronous extract: bounded parallelism (`SYNC_EXTRACT_MAX_CONCURRENT`, `asyncio.gather`).
- Timeouts: Gemini, PyPDF parse, Mistral HTTP (see `.env.example`).
- Worker uses the same processing and LLM slot behavior as the API.

### Redis Streams queue hardening

- Stream semantics documented: `docs/STREAMS_CONTRACT.md`.
- Retries with backoff/jitter; `attempt` / `process_attempt` / `correlation_id` on jobs and stream fields.
- Pending reclaim (`XAUTOCLAIM`, `JOB_STREAM_CLAIM_IDLE_MS`); DLQ after max reclaims (`JOB_MAX_RECLAIMS_PER_MESSAGE`).
- Dead-letter stream `REDIS_STREAM_DLQ`; replay policy in the streams contract.
- Structured JSON logs (`backend/app/worker_observability.py`).
- Prometheus `/metrics` on worker (`WORKER_METRICS_PORT`, default `9464`); `XPENDING`-based gauges.
- Optional OTLP tracing when `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
- Multiple workers (`docker compose up --scale worker=N`); idempotent handling under duplicate delivery.

### Testing and automation

- pytest as primary integration suite (`python3 tests/run_pytest.py`, reports under `tests/report/`).
- Redis Streams tests with Testcontainers (`tests/test_redis_streams_integration.py`, `@pytest.mark.streams`); see `docs/TESTS.md`.
- FR-ordered runner: `python3 tests/run_fr_tests.py`.
- PDF fixtures under `tests/fixtures/pdf/`; `tests/download_pdf_fixtures.py`.
- CI helper: `scripts/ci_build_and_test.sh` (Compose build, strict fixture download, pytest).

### Documentation

- Post-review tables §9.1–§9.2 in `docs/IMPLEMENTATION_STATUS.md` track closure of PR-FR-* / PR-TR-* items for this release.

---

## v.0.0.1 — 26 March 2026

First integrated delivery (**baseline**, before the v.0.0.2 hardening pass). Summarized from the “Top Strengths” in `docs/TODO.md` (evaluation context).

### Delivered scope

- Docker Compose stack: **backend**, **worker**, **Redis**, **frontend**, and **mistral-mock** for local Mistral-compatible testing.
- End-to-end upload → extract → summarize flow with Redis caching by SHA256.
- **Redis Streams** async jobs (`POST /api/jobs/extract`, `GET /api/jobs/{job_id}`), worker consumer group, job lifecycle.
- Multi-file upload, parser selection in API/UI, Gemini summarization and Q&A, multilingual frontend (`frontend/src/locales/*`).
- Test automation and smoke/integration verification (later largely superseded by pytest-first tooling in v.0.0.2).

### Known limitations (addressed in v.0.0.2)

- Advanced parsing was effectively **Gemini-as-formatter over PyPDF text**, not a clearly separated native-PDF vs formatter product story.
- Blocking PDF/LLM work in async contexts with limited concurrency controls and timeouts.
- Queue path without full retry/reclaim/DLQ story and weaker operational observability.
- Heavy reliance on shell/curl for integration checks instead of a pytest-centric suite.

---

## References

| Topic | Document |
|--------|----------|
| Task spec and v.0.0.1 evaluation | `docs/TODO.md` |
| Requirement matrix and §9 backlog | `docs/IMPLEMENTATION_STATUS.md` |
| Streams semantics | `docs/STREAMS_CONTRACT.md` |
| How to run tests | `docs/TESTS.md` |
| Operator / developer guide | `README.md` |

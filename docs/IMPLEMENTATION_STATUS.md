# Implementation Status vs Requirements

This document tracks what is already implemented in the repository compared to `docs/REQUIREMENTS.md`, and records **post–code-review gaps** (external bar-raising feedback) with a concrete remediation outline in [Section 9](#9-post-review-remediation-roadmap).

Status legend:
- `DONE` - fully implemented
- `PARTIAL` - implemented in simplified form or missing key parts
- `TODO` - not implemented yet
- `N/A` - explicitly out of scope or declined (use mainly in [Section 9](#9-post-review-remediation-roadmap))
---

## 1. Functional Requirements

| Requirement | Status | Notes |
|---|---|---|
| FR-1: Document upload (one or more PDFs + parser selection) | DONE | Multi-file upload is implemented (`/api/pdf/extract` accepts `files[]`) and parser selection is available in both backend API and frontend UI. |
| FR-2: Parser selection (`pypdf`, Gemini variants, Mistral) | DONE | Parser selection is implemented end-to-end in API/UI: `pypdf`, `gemini-2.5-flash-pdf`, `gemini-2.5-flash-text`, legacy `gemini-2.5-flash`, `mistral`, and `mistral-ocr` (external keys required for Mistral parsers). |
| FR-3: Asynchronous processing with Redis Streams | DONE | Added async job processing via Redis Streams (`POST /api/jobs/extract`, `GET /api/jobs/{job_id}`) with a dedicated worker service. |
| FR-4: Parsed output per file (markdown when possible) | DONE | Backend returns per-page content in `pages[]`. For `gemini-2.5-flash-pdf`, `gemini-2.5-flash-text`, legacy `gemini-2.5-flash`, `mistral`, and `mistral-ocr` this is markdown (split by page markers), while `pypdf` returns plain text. |
| FR-5: One summary per uploaded file using Gemini 2.5 Flash | DONE | Backend generates and returns `summary` per uploaded file during extraction (sync) and job processing (async), using Gemini 2.5 Flash. |
| FR-6: Store parser/content/summary/status in Redis | DONE | Parsed content (`pdf:{parser}:{sha}`) and summaries (`pdf:summary:gemini:...`) are cached together with `generated_at` timestamps. Async job results (`doc:job:{job_id}`) include status plus the full `result` (text/pages/summary) with `content_generated_at`/`summary_generated_at`. |
| FR-7: Result retrieval after processing | DONE | Frontend supports async extraction via `POST /api/jobs/extract` and polls `GET /api/jobs/{job_id}` until `done/failed`, then renders parsed `text/pages/summary` per file. |

---

## 2. Technical Requirements

| Requirement | Status | Notes |
|---|---|---|
| TR-1: Python 3.12+ + FastAPI + concurrent API handling | DONE | Implemented in backend (`python:3.12-slim-bookworm`, FastAPI + Uvicorn). Blocking PyPDF / PyMuPDF and Gemini SDK work runs in bounded thread pools off the event loop (`_get_pdf_cpu_executor`, `_get_gemini_blocking_executor`; optional `GEMINI_POOL_MAX_WORKERS` isolates Gemini threads from PDF CPU work). Historical post-review context: [Section 9](#9-post-review-remediation-roadmap). |
| TR-2: Redis v7+ + Streams for async jobs | DONE | Redis Streams-based queue processing is implemented via `doc_jobs` stream and a worker consumer group. |
| TR-3: PyPDF + Gemini 2.5 Flash for advanced parsing and summarization | DONE | **PyPDF:** `pypdf.PdfReader` in `backend/app/main.py` for basic text extraction and (for native Gemini) page-count metadata. **Gemini 2.5 Flash:** `GEMINI_MODEL` (default `gemini-2.5-flash`) via `google-generativeai` — **formatter** path (`gemini-2.5-flash-text`, legacy `gemini-2.5-flash`): `_extract_markdown_with_gemini`; **native PDF** path (`gemini-2.5-flash-pdf`): `_extract_markdown_with_gemini_native_pdf` with inline `application/pdf`. Summaries: `_summarize_with_gemini` (via `_gemini_generate_content` when using the SDK wrapper). Sync and async worker share `_process_pdf_bytes`. **Post-review gap closed:** explicit parser ids + docs; see Section 9.1 PR-FR-1–PR-FR-4. |
| TR-4: Frontend in React/TS (minimal acceptable) | DONE | React + TypeScript + Vite frontend is implemented, including multi-file upload UI, ask flow, and modular localization (`frontend/src/locales/*`). |
| TR-5: All components wrapped in Docker Compose | DONE | Backend, worker, frontend, Redis, and `mistral-mock` are dockerized and run via `docker-compose.yml`. |

---

## 3. API Expectations (High-Level)

| Requirement | Status | Notes |
|---|---|---|
| Upload endpoint with parser selection and job ID | DONE | Async upload endpoint `POST /api/jobs/extract` accepts files + `parser` and returns `job_id` with initial status. |
| Status/result endpoint (`queued`, `processing`, `done`, `failed`) | DONE | `GET /api/jobs/{job_id}` returns status; when `done`, `result` is the full `_process_pdf_bytes` payload (`text`, `pages[]`, `summary`, timestamps, `sha256`, `parser`). |

---

## 4. Priority Order Progress

From `docs/REQUIREMENTS.md` priority list:

1. Backend concurrent app - **DONE**
2. Upload + PyPDF processing - **DONE (multi-file endpoint)**
3. Redis Streams async queue - **DONE**
4. Gemini summarization - **DONE** (`_summarize_with_gemini` in `_process_pdf_bytes`; used by sync extract and async worker jobs)
5. Mistral OCR processing - **DONE** (`mistral-ocr`: PyMuPDF raster + Mistral vision per page; `mistral`: text formatter via API/mock)
6. Frontend - **DONE (minimal + multilingual UI)**

---

## 5. What Is Working Today

- Dockerized stack: backend, worker, frontend, Redis, and `mistral-mock`.
- PDF extraction endpoint with Redis cache by SHA256.
- Multi-file upload support end-to-end (`files[]` in API + multi-select in frontend input).
- Parser selection support in extraction flow (`pypdf`, `gemini-2.5-flash-pdf`, `gemini-2.5-flash-text`, legacy `gemini-2.5-flash`, `mistral`, `mistral-ocr`).
- Local Mistral mock service is available for no-account testing (`mistral-mock` in Docker Compose).
- Gemini answer endpoint with configurable response language (`en/pl/es/pt/fr/ru`).
- Localization architecture extracted to separate per-language files (`frontend/src/locales/`), ready for easy language additions.
- Frontend workflow:
  - upload PDF,
  - extract text,
  - ask Gemini with extracted context,
  - switch full interface language.
- Localization docs and template are available:
  - `docs/LOCALIZATION.md`
  - `frontend/src/locales/template.ts`
- Async processing via Redis Streams:
  - `POST /api/jobs/extract` creates jobs
  - `GET /api/jobs/{job_id}` returns status/result
  - `pdf-proc-worker` consumes `doc_jobs`; transient retries **`XADD` / `XACK`** after backoff run in a **background task** so the **`XREADGROUP`** loop keeps draining other messages (see `docs/STREAMS_CONTRACT.md`).
- **TR-3 stack:** PyPDF extraction + Gemini 2.5 Flash for advanced markdown conversion and per-file summarization (same code path for sync and worker).

---

## 6. Main Gaps / Hardening (non-blocking for core FR/TR)

1. Improve parser-specific resilience (timeouts, retries, rate-limit handling for Gemini/Mistral).
2. (Optional) Add validation and limits for large multi-file batches (count/size/timeout) beyond LLM / per-request concurrency caps.
3. `mistral` is HTTP text→markdown; **`mistral-ocr`** adds raster + vision OCR-style parsing (PR-FR-5). Not Mistral Document AI batch OCR.

For a **structured post-review backlog** (native PDF parsing expectations, async isolation, Streams reclaim/DLQ, pytest migration, worker depth), see [Section 9](#9-post-review-remediation-roadmap).

---

## 7. Recommended Next Steps

Short-term hardening overlaps with [Section 9](#9-post-review-remediation-roadmap). In order:

1. Section **9.2** — rows **PR-TR-1–PR-TR-5** and **PR-TR-16** (non-blocking PDF/LLM work, backpressure) for the largest win on API concurrency.
2. Section **9.2** — rows **PR-TR-6–PR-TR-12**, **PR-TR-14**, and **PR-TR-17–PR-TR-18** — **DONE** (see Section 9.2 table).
3. Section **9.1** — **PR-FR-1–PR-FR-4** — **DONE** (see Section 9.1 table).

---

## 8. Testing References

- Overview of all test scripts and how to run them: `docs/TESTS.md`
- Pytest suite and reports: `python3 tests/run_pytest.py`, `tests/report/junit.xml`, `tests/report/report.html`
- PDF fixtures: `tests/fixtures/pdf/` (optional `PDF_FILE`); download: `python3 tests/download_pdf_fixtures.py`
- FR order / subset runner: `python3 tests/run_fr_tests.py` (replaces old shell orchestration)
- Manual verification checklist: `docs/TEST_CHECKLIST.md`
- Requirements-level test plan: `docs/REQUIREMENTS.md` (Section 9)

---

## 9. Post-review remediation roadmap

This section maps **external review “rejection reasons”** to **traceable backlog items** so progress can be tracked the same way as Sections 1–2 (`TODO` → `PARTIAL` → `DONE`, or `N/A` when explicitly out of scope). It does not change formal FR/TR status in Sections 1–5.

**Status legend (Section 9 only):** same as document header: `TODO` | `PARTIAL` | `DONE` | `N/A`.

When you complete work, update the **Status** cell and optionally add a short pointer in **Notes** (PR number, commit, or doc section).

---

### 9.1 Post-review functional requirements (parsing & product clarity)

| ID | Requirement | Status | Notes |
|---|---|---|---|
| PR-FR-1 | **Product decision recorded:** either (A) Gemini consumes **PDF bytes** (or page images) as the primary “advanced” parse input, or (B) the product explicitly exposes a **formatter** mode (PyPDF text → Gemini markdown) with distinct parser names and docs. | DONE | **Both modes are supported** with explicit parser ids and aligned docs: `README.md`, `docs/REQUIREMENTS.md`, `docs/TODO.md`. |
| PR-FR-2 | If **(A) native / multimodal PDF:** implement upload path via supported **Generative AI file / multimodal** APIs for `gemini-2.5-flash`; add regression tests so the path cannot silently fall back to text-only. | DONE | `gemini-2.5-flash-pdf` → `_extract_markdown_with_gemini_native_pdf` (inline `application/pdf`). Oversized PDF → **413** (no silent formatter fallback). Unit tests: `tests/test_pr_fr_gemini_paths.py` (native vs formatter payloads, SDK **`RequestOptions`** timeout on **`_gemini_generate_content`**, optional dedicated Gemini thread pool). |
| PR-FR-3 | **Scanned / image-only PDFs:** documented behavior (reject, OCR pipeline, or rasterize+vision) and tests for at least one chosen behavior. | DONE | Documented in `docs/REQUIREMENTS.md` + `README.md` (no OCR for text-based parsers; native PDF path uses multimodal bytes). Tests: `tests/test_pr_fr_scanned_pdf.py` (blank-page PDF → empty PyPDF text). |
| PR-FR-4 | If **(B) formatter-only:** add API + UI parser identifiers (e.g. split `gemini-2.5-flash-text` vs `gemini-2.5-flash-pdf`) and migration notes for existing clients. | DONE | API `ParserType`, worker allow-list, frontend select + locales; migration notes in `README.md` (`POST /api/pdf/extract` section). Legacy `gemini-2.5-flash` unchanged. |
| PR-FR-5 | **Optional OCR / layout pipeline** for “Mistral OCR” / scan-heavy use cases (rasterize pages, external OCR, layout engine, then markdown). | DONE | Parser `mistral-ocr`: PyMuPDF page rasters → Mistral chat vision (`image_url` per page, `MISTRAL_OCR_MODEL`). Caps: `MISTRAL_OCR_MAX_PAGES`, `MISTRAL_OCR_RASTER_ZOOM`. Mock supports vision payloads. Unit: `tests/test_mistral_ocr_raster_unit.py`. |

---

### 9.2 Post-review technical requirements (engineering, queue, tests, worker)

| ID | Requirement | Status | Notes |
|---|---|---|---|
| PR-TR-1 | Run **PyPDF** extraction (`_extract_page_texts_from_pdf` and related CPU work) **off the asyncio event loop** (`asyncio.to_thread` and/or bounded `ThreadPoolExecutor` on app state). | DONE | `backend/app/main.py`: `_run_blocking` + PDF CPU `ThreadPoolExecutor` (`BLOCKING_POOL_MAX_WORKERS`, `_get_pdf_cpu_executor`); worker calls `_init_blocking_executors()` at startup. |
| PR-TR-2 | Run **synchronous Gemini SDK** calls (`generate_content`, etc.) **off the event loop** (dedicated small executor or `to_thread`). | DONE | Gemini paths use `_run_blocking` / `_run_blocking_timed` with `_get_gemini_blocking_executor()` (optional dedicated pool via `GEMINI_POOL_MAX_WORKERS`; otherwise shares the PDF CPU pool). |
| PR-TR-3 | **Concurrency cap / backpressure:** global semaphore (or similar) for in-flight LLM operations; defined behavior when saturated (`429` / `503` + `Retry-After` or queue); document limits. | DONE | `LLM_MAX_INFLIGHT` + `LLM_SLOT_ACQUIRE_TIMEOUT_SECONDS`; `asyncio.Semaphore` via `_llm_slot()`; `503` + `Retry-After` on `LlmCapacityExceededError`; multi-file sync reports per-file `error` when saturated. |
| PR-TR-4 | **Multi-file sync extract:** bounded parallelism (`asyncio.gather` + semaphore), not unbounded sequential loop, where safe. | DONE | `SYNC_EXTRACT_MAX_CONCURRENT` + `asyncio.gather` in `POST /api/pdf/extract`. |
| PR-TR-5 | **Timeouts:** per-request and per-provider timeouts for HTTP clients and LLM calls (SDK-level where supported). | DONE | `GEMINI_CALL_TIMEOUT_SECONDS` via `_gemini_generate_content` (`RequestOptions` when supported) plus `_run_blocking_timed` / `504`; `PDF_PARSE_TIMEOUT_SECONDS` for PyPDF; `MISTRAL_HTTP_TIMEOUT_SECONDS` via `httpx.Timeout` for Mistral. |
| PR-TR-6 | **Stream processing contract** documented: at-least-once + idempotent handlers vs at-most-once; when `XACK` is allowed relative to success / DLQ. | DONE | [`docs/STREAMS_CONTRACT.md`](STREAMS_CONTRACT.md). |
| PR-TR-7 | **Retries** for transient failures (Redis, network, provider 5xx): bounded attempts, backoff, persisted `attempt` on job or stream fields. | DONE | `attempt` on stream + `process_attempt` / `correlation_id` on job; exponential backoff + jitter in `backend/app/worker.py`; backoff + retry `XADD` + `XACK` run in a **background task** so the consumer loop is not blocked during backoff (`docs/STREAMS_CONTRACT.md`). |
| PR-TR-8 | **Pending reclaim:** `XAUTOCLAIM` and/or `XPENDING` + `XCLAIM` for stale pending messages past a **visibility timeout**, with reclaim attempt caps. | DONE | `XAUTOCLAIM` + `JOB_STREAM_CLAIM_IDLE_MS`; `reclaim_count` on job → DLQ when `JOB_MAX_RECLAIMS_PER_MESSAGE` exceeded. |
| PR-TR-9 | **Dead-letter queue:** after max retries, move payload + diagnostics to a DLQ stream (e.g. `doc_jobs_dlq`) and `XACK` primary; define replay tooling or policy. | DONE | `REDIS_STREAM_DLQ` + replay policy in `docs/STREAMS_CONTRACT.md`. |
| PR-TR-10 | **Structured logs** (JSON): include `job_id` / `msg_id` correlation from enqueue through worker to provider. | DONE | `backend/app/worker_observability.py` (`log_json`); enqueue sets `correlation_id` in `main.py` + stream fields. |
| PR-TR-11 | **Metrics:** counters/histograms for job states, stream lag, provider latency; document scrape or export path. | DONE | Prometheus `/metrics` on worker (`WORKER_METRICS_PORT`, default `9464`); `pdf_worker_process_seconds` covers end-to-end handler time (includes provider calls); pending gauge via `XPENDING`; README + `.env.example`. |
| PR-TR-12 | **Optional tracing:** OpenTelemetry (or equivalent) spans on worker → external APIs. | DONE | OTLP HTTP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (`worker_observability.py`); disable with `OTEL_SDK_DISABLED=true`. |
| PR-TR-13 | **pytest** suite for core flows: health, single-file sync extract, async job lifecycle, `POST /api/gemini/answer` (fixtures for PDF bytes). | DONE | `tests/test_*.py`, `httpx` against live stack; `python3 tests/run_pytest.py`; reports under `tests/report/`. |
| PR-TR-14 | **Redis Streams integration tests** (Testcontainers Redis, or CI-only Compose profile) covering consumer group, happy path, and at least one failure path. | DONE | `tests/test_redis_streams_integration.py` (`@pytest.mark.streams`); Testcontainers `redis:7.2-alpine`; see `docs/TESTS.md`. |
| PR-TR-15 | **Reduce bash/curl surface:** migrate or thin-wrap `tests/*.sh` so CI runs `pytest` as primary; keep bash only as orchestration if needed. | DONE | Integration tests are Python-only; `scripts/ci_build_and_test.sh` remains shell for Docker Compose plus **readiness** `curl` polls before pytest (see `docs/TESTS.md`). |
| PR-TR-16 | **Worker:** apply PR-TR-1–PR-TR-3 (offload + limits) inside `pdf-proc-worker` so the worker process does not block its event loop on PDF/LLM. | DONE | Same `_process_pdf_bytes` + `_llm_slot()` as API; explicit `LlmCapacityExceededError` → failed job (no silent drop). |
| PR-TR-17 | **Worker:** implement PR-TR-7–PR-TR-9 (retry, reclaim, DLQ) in worker or companion supervisor process. | DONE | Implemented in `backend/app/worker.py` (same process). |
| PR-TR-18 | **Optional horizontal scale:** multiple consumers, tuned `BLOCK`/`COUNT`, idempotent job execution verified under duplicate delivery. | DONE | `WORKER_XREADGROUP_*` envs; idempotent `done` skip in worker; `docker compose up --scale worker=N` (fixed `container_name` removed from worker service). |

---

### 9.3 Reference: gap narrative (by original review theme)

Use this block for **context** when filling the tables above; status tracking lives in **Section 9.1–9.2** only.

1. **Advanced parsing** — `gemini-2.5-flash-pdf` uses inline PDF bytes; `gemini-2.5-flash-text` and legacy `gemini-2.5-flash` use the PyPDF→Gemini formatter; **`mistral-ocr`** rasterizes pages then Mistral vision (PR-FR-5).

2. **Async / senior bar** — Blocking PyPDF / PyMuPDF and sync Gemini are offloaded to bounded pools (optional dedicated Gemini pool via **`GEMINI_POOL_MAX_WORKERS`**); LLM concurrency and multi-file sync parallelism are capped (**PR-TR-1–PR-TR-5**, **PR-TR-16**). Further tuning is optional (batch size limits, provider rate limits).

3. **Queue hardening** — Retry, reclaim, DLQ, structured logs, Prometheus metrics, optional OTLP, multi-consumer tuning, and **PR-TR-14** Redis Streams tests (**PR-TR-6–PR-TR-12**, **PR-TR-14**, **PR-TR-17–PR-TR-18**).

4. **Tests in shell** — Former bash + curl suite replaced by pytest (**PR-TR-13–PR-TR-15**); further hardening is optional (e.g. in-process ASGI tests).

5. **Worker loop** — Linear read → process → `XACK`; overlaps items 2–3. Address via **PR-TR-16–PR-TR-18**.

**Acceptance themes (cross-cutting):** (a) Under load, `/api/health` stays responsive while heavy jobs run. (b) Kill worker mid-job → pending message is reclaimed or fails loudly within policy. (c) Poison message ends in DLQ after retries. (d) `pytest` runs core FR paths without manual curl.

---

**Async PDF Processor** v.0.0.2 · 14 April 2026 · Code author: Arkadiusz Czerwinski

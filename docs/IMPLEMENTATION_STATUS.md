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
| FR-2: Parser selection (`pypdf`, `gemini-2.5-flash`, `mistral`) | DONE | Parser selection is implemented end-to-end in API/UI. `pypdf`, `gemini-2.5-flash`, and `mistral` parser paths are implemented (external keys required for provider-based parsers). |
| FR-3: Asynchronous processing with Redis Streams | DONE | Added async job processing via Redis Streams (`POST /api/jobs/extract`, `GET /api/jobs/{job_id}`) with a dedicated worker service. |
| FR-4: Parsed output per file (markdown when possible) | DONE | Backend returns per-page content in `pages[]`. For `gemini-2.5-flash` and `mistral` this is markdown (split by page markers), while `pypdf` returns plain text. |
| FR-5: One summary per uploaded file using Gemini 2.5 Flash | DONE | Backend generates and returns `summary` per uploaded file during extraction (sync) and job processing (async), using Gemini 2.5 Flash. |
| FR-6: Store parser/content/summary/status in Redis | DONE | Parsed content (`pdf:{parser}:{sha}`) and summaries (`pdf:summary:gemini:...`) are cached together with `generated_at` timestamps. Async job results (`doc:job:{job_id}`) include status plus the full `result` (text/pages/summary) with `content_generated_at`/`summary_generated_at`. |
| FR-7: Result retrieval after processing | DONE | Frontend supports async extraction via `POST /api/jobs/extract` and polls `GET /api/jobs/{job_id}` until `done/failed`, then renders parsed `text/pages/summary` per file. |

---

## 2. Technical Requirements

| Requirement | Status | Notes |
|---|---|---|
| TR-1: Python 3.12+ + FastAPI + concurrent API handling | DONE | Implemented in backend (`python:3.12-slim-bookworm`, FastAPI + Uvicorn). **Post-review:** synchronous PyPDF/Gemini work inside `async` paths limits effective concurrency; see Section 9.2 in [§9](#9-post-review-remediation-roadmap). |
| TR-2: Redis v7+ + Streams for async jobs | DONE | Redis Streams-based queue processing is implemented via `doc_jobs` stream and a worker consumer group. |
| TR-3: PyPDF + Gemini 2.5 Flash for advanced parsing and summarization | DONE | **PyPDF:** `pypdf.PdfReader` in `backend/app/main.py` (`_extract_page_texts_from_pdf`, etc.) for basic text extraction. **Gemini 2.5 Flash:** `GEMINI_MODEL` (default `gemini-2.5-flash`) via `google-generativeai` for markdown-oriented page conversion (`_extract_markdown_with_gemini`) and per-file summaries (`_summarize_with_gemini`). Sync (`/api/pdf/extract`) and async worker (`pdf-proc-worker` → `_process_pdf_bytes`) both use this pipeline. **Post-review:** Gemini “parser” path is **text-in → markdown-out** over PyPDF page text, not native PDF parsing; see Section 9.1 in [§9](#9-post-review-remediation-roadmap). |
| TR-4: Frontend in React/TS (minimal acceptable) | DONE | React + TypeScript + Vite frontend is implemented, including multi-file upload UI, ask flow, and modular localization (`frontend/src/locales/*`). |
| TR-5: All components wrapped in Docker Compose | DONE | Backend, frontend, and Redis are dockerized and run via `docker-compose.yml`. |

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
5. Mistral OCR processing - **PARTIAL (Mistral parser path implemented via API/mock; OCR-specific path not implemented)**
6. Frontend - **DONE (minimal + multilingual UI)**

---

## 5. What Is Working Today

- Dockerized stack: backend, worker, frontend, Redis, and `mistral-mock`.
- PDF extraction endpoint with Redis cache by SHA256.
- Multi-file upload support end-to-end (`files[]` in API + multi-select in frontend input).
- Parser selection support in extraction flow (`pypdf`, `gemini-2.5-flash`, `mistral`).
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
  - `pdf-proc-worker` consumes `doc_jobs`
- **TR-3 stack:** PyPDF extraction + Gemini 2.5 Flash for advanced markdown conversion and per-file summarization (same code path for sync and worker).

---

## 6. Main Gaps / Hardening (non-blocking for core FR/TR)

1. Improve parser-specific resilience (timeouts, retries, rate-limit handling for Gemini/Mistral).
2. (Optional) Add validation and limits for large multi-file batches (count/size/timeout) and backpressure.
3. Mistral path is HTTP markdown conversion (via API/mock), not a separate OCR pipeline — acceptable as “nice-to-have” per requirements.

For a **structured post-review backlog** (native PDF parsing expectations, async isolation, Streams reclaim/DLQ, pytest migration, worker depth), see [Section 9](#9-post-review-remediation-roadmap).

---

## 7. Recommended Next Steps

Short-term hardening overlaps with [Section 9](#9-post-review-remediation-roadmap). In order:

1. Section **9.2** — rows **PR-TR-1–PR-TR-5** and **PR-TR-16** (non-blocking PDF/LLM work, backpressure) for the largest win on API concurrency.
2. Section **9.2** — rows **PR-TR-6–PR-TR-12** and **PR-TR-17–PR-TR-18** (queue contract, retry, reclaim, DLQ, observability, worker scale).
3. Section **9.1** — **PR-FR-1–PR-FR-4** if the product must treat Gemini as a true PDF parser or must explicitly label formatter vs native modes.

---

## 8. Testing References

- Overview of all test scripts and how to run them: `docs/TESTS.md`
- Shared PDF discovery (`tests/fixtures/pdf/`, optional `PDF_FILE`): `tests/lib/fr_common.sh`
- Automated smoke tests: `tests/run_smoke_tests.sh`
- Per-FR scripts + `multi` (all fixtures in one sync/async request): `tests/run_all_fr_tests.sh`, `tests/test_multi_pdf_all_fixtures.sh`
- Full integration sweep: `tests/test_integration_all_fr.sh`
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
| PR-FR-1 | **Product decision recorded:** either (A) Gemini consumes **PDF bytes** (or page images) as the primary “advanced” parse input, or (B) the product explicitly exposes a **formatter** mode (PyPDF text → Gemini markdown) with distinct parser names and docs. | TODO | Align `README.md`, `docs/REQUIREMENTS.md`, `docs/TODO.md` after the decision. |
| PR-FR-2 | If **(A) native / multimodal PDF:** implement upload path via supported **Generative AI file / multimodal** APIs for `gemini-2.5-flash`; add regression tests so the path cannot silently fall back to text-only. | TODO | Keep PyPDF (or explicit error) as fallback when API rejects file or quotas bite. |
| PR-FR-3 | **Scanned / image-only PDFs:** documented behavior (reject, OCR pipeline, or rasterize+vision) and tests for at least one chosen behavior. | TODO | Depends on PR-FR-1 / cost constraints. |
| PR-FR-4 | If **(B) formatter-only:** add API + UI parser identifiers (e.g. split `gemini-2.5-flash-text` vs `gemini-2.5-flash-pdf`) and migration notes for existing clients. | TODO | Optional if PR-FR-2 is fully implemented instead. |
| PR-FR-5 | **Optional OCR / layout pipeline** for “Mistral OCR” / scan-heavy use cases (rasterize pages, external OCR, layout engine, then markdown). | TODO | Mark `N/A` if product explicitly declines OCR scope. |

---

### 9.2 Post-review technical requirements (engineering, queue, tests, worker)

| ID | Requirement | Status | Notes |
|---|---|---|---|
| PR-TR-1 | Run **PyPDF** extraction (`_extract_page_texts_from_pdf` and related CPU work) **off the asyncio event loop** (`asyncio.to_thread` and/or bounded `ThreadPoolExecutor` on app state). | TODO | Applies to API and worker. |
| PR-TR-2 | Run **synchronous Gemini SDK** calls (`generate_content`, etc.) **off the event loop** (dedicated small executor or `to_thread`). | TODO | Same pattern for any other blocking SDK in `async def` paths. |
| PR-TR-3 | **Concurrency cap / backpressure:** global semaphore (or similar) for in-flight LLM operations; defined behavior when saturated (`429` / `503` + `Retry-After` or queue); document limits. | TODO | |
| PR-TR-4 | **Multi-file sync extract:** bounded parallelism (`asyncio.gather` + semaphore), not unbounded sequential loop, where safe. | TODO | `POST /api/pdf/extract` |
| PR-TR-5 | **Timeouts:** per-request and per-provider timeouts for HTTP clients and LLM calls (SDK-level where supported). | TODO | |
| PR-TR-6 | **Stream processing contract** documented: at-least-once + idempotent handlers vs at-most-once; when `XACK` is allowed relative to success / DLQ. | TODO | Informs PR-TR-7–9. |
| PR-TR-7 | **Retries** for transient failures (Redis, network, provider 5xx): bounded attempts, backoff, persisted `attempt` on job or stream fields. | TODO | |
| PR-TR-8 | **Pending reclaim:** `XAUTOCLAIM` and/or `XPENDING` + `XCLAIM` for stale pending messages past a **visibility timeout**, with reclaim attempt caps. | TODO | |
| PR-TR-9 | **Dead-letter queue:** after max retries, move payload + diagnostics to a DLQ stream (e.g. `doc_jobs_dlq`) and `XACK` primary; define replay tooling or policy. | TODO | |
| PR-TR-10 | **Structured logs** (JSON): include `job_id` / `msg_id` correlation from enqueue through worker to provider. | TODO | |
| PR-TR-11 | **Metrics:** counters/histograms for job states, stream lag, provider latency; document scrape or export path. | TODO | |
| PR-TR-12 | **Optional tracing:** OpenTelemetry (or equivalent) spans on enqueue → worker → external APIs. | TODO | Mark `N/A` if not adopted. |
| PR-TR-13 | **pytest** suite for core flows: health, single-file sync extract, async job lifecycle, `POST /api/gemini/answer` (fixtures for PDF bytes). | TODO | `httpx` + `ASGITransport` and/or HTTP against stack. |
| PR-TR-14 | **Redis Streams integration tests** (Testcontainers Redis, or CI-only Compose profile) covering consumer group, happy path, and at least one failure path. | TODO | |
| PR-TR-15 | **Reduce bash/curl surface:** migrate or thin-wrap `tests/*.sh` so CI runs `pytest` as primary; keep bash only as orchestration if needed. | TODO | |
| PR-TR-16 | **Worker:** apply PR-TR-1–PR-TR-3 (offload + limits) inside `pdf-proc-worker` so the worker process does not block its event loop on PDF/LLM. | TODO | |
| PR-TR-17 | **Worker:** implement PR-TR-7–PR-TR-9 (retry, reclaim, DLQ) in worker or companion supervisor process. | TODO | |
| PR-TR-18 | **Optional horizontal scale:** multiple consumers, tuned `BLOCK`/`COUNT`, idempotent job execution verified under duplicate delivery. | TODO | Mark `N/A` for single-node only. |

---

### 9.3 Reference: gap narrative (by original review theme)

Use this block for **context** when filling the tables above; status tracking lives in **§9.1–9.2** only.

1. **Advanced parsing** — Today `gemini-2.5-flash` uses PyPDF page text then Gemini for markdown; `pdf_bytes` are not the primary model input. Address via **PR-FR-1–PR-FR-5**.

2. **Async / senior bar** — Blocking PyPDF and sync Gemini inside `async def` without executors; limited backpressure. Address via **PR-TR-1–PR-TR-5** and **PR-TR-16**.

3. **Queue hardening** — No systematic retry, reclaim, DLQ, or rich ops signals. Address via **PR-TR-6–PR-TR-12** and **PR-TR-17**.

4. **Tests in shell** — Heavy bash + curl. Address via **PR-TR-13–PR-TR-15**.

5. **Worker loop** — Linear read → process → `XACK`; overlaps items 2–3. Address via **PR-TR-16–PR-TR-18**.

**Acceptance themes (cross-cutting):** (a) Under load, `/api/health` stays responsive while heavy jobs run. (b) Kill worker mid-job → pending message is reclaimed or fails loudly within policy. (c) Poison message ends in DLQ after retries. (d) `pytest` runs core FR paths without manual curl.

---

**Async PDF Processor** v.0.0.1 · 26 March 2026 · Code author: Arkadiusz Czerwinski

# Implementation Status vs Requirements

This document tracks what is already implemented in the repository compared to `docs/REQUIREMENTS.md`.

Status legend:
- `DONE` - fully implemented
- `PARTIAL` - implemented in simplified form or missing key parts
- `TODO` - not implemented yet
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
| TR-1: Python 3.12+ + FastAPI + concurrent API handling | DONE | Implemented in backend (`python:3.12-slim-bookworm`, FastAPI + Uvicorn). |
| TR-2: Redis v7+ + Streams for async jobs | DONE | Redis Streams-based queue processing is implemented via `doc_jobs` stream and a worker consumer group. |
| TR-3: PyPDF + Gemini 2.5 Flash for advanced parsing and summarization | DONE | **PyPDF:** `pypdf.PdfReader` in `backend/app/main.py` (`_extract_page_texts_from_pdf`, etc.) for basic text extraction. **Gemini 2.5 Flash:** `GEMINI_MODEL` (default `gemini-2.5-flash`) via `google-generativeai` for markdown-oriented page conversion (`_extract_markdown_with_gemini`) and per-file summaries (`_summarize_with_gemini`). Sync (`/api/pdf/extract`) and async worker (`pdf-proc-worker` → `_process_pdf_bytes`) both use this pipeline. |
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

---

## 7. Recommended Next Steps

1. Operational hardening for external APIs (Gemini/Mistral): timeouts, structured errors, optional retries.
2. Batch/upload limits and clearer `413`/`422` responses for oversized payloads.
3. Additional observability (structured logs, metrics) for queue and provider latency.

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

**Async PDF Processor** v.0.0.1 · 26 March 2026 · Code author: Arkadiusz Czerwinski

# Async PDF Processor

An asynchronous document processing application: users upload one or more PDFs through the web UI; extraction and summarization run in the background via Redis Streams. Built with Docker Compose.

Stack highlights:
- PDF text extraction with FastAPI and `pypdf`
- Redis caching and async jobs (worker service)
- Gemini 2.5 Flash for summaries and Q&A
- React + TypeScript frontend with multi-language UI

## Table of contents
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [Run the project](#run-the-project)
- [How to use](#how-to-use)
- [Testing](#testing)
- [Backend API](#backend-api)
- [Language support](#language-support)
- [Localization](#localization)
- [Troubleshooting](#troubleshooting)
- [Security notes](#security-notes)

## Architecture

The app runs as several services with Docker Compose:

0. `mistral-mock`
   - local mock API for Mistral-compatible chat completions
   - used by default for local development/testing (no external Mistral account required)
1. `backend` (container `pdf-proc-backend`)
   - FastAPI app
   - PDF parsing via `pypdf`
   - Gemini calls via `google-generativeai`
   - Redis integration for cache
2. `worker` (Compose service; scale with `docker compose up --scale worker=N`)
   - consumes Redis Streams (`doc_jobs`) with at-least-once semantics; see [`docs/STREAMS_CONTRACT.md`](docs/STREAMS_CONTRACT.md)
   - exposes Prometheus metrics on port **9464** (`/metrics`) when `WORKER_METRICS_PORT` is non-zero
3. `frontend` (container `pdf-proc-frontend`)
   - React + TypeScript (Vite dev server)
   - calls backend through `/api` proxy
   - interface language switcher
4. `redis`
   - Redis 7.x
   - cache and Streams queue for async jobs

## Tech stack

- Python 3.12 (`python:3.12-slim-bookworm`)
- FastAPI + Uvicorn
- Redis 7 (`redis:7.2-alpine`)
- PyPDF (`pypdf`)
- Google Gemini 2.5 Flash
- React 18 + TypeScript + Vite
- Docker + Docker Compose

## Project structure

```text
async-pdf-proc/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── worker.py
│   │   └── worker_observability.py
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── Dockerfile
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── tests/
│   ├── fixtures/pdf/     # sample PDFs; pytest discovers *.pdf (see docs/TESTS.md)
│   ├── run_pytest.py     # CI + local: venv, pytest, HTML/JUnit reports
│   ├── run_fr_tests.py   # optional ordered FR runs (-m fr1 … -m multi)
│   ├── download_pdf_fixtures.py
│   ├── test_*.py
│   └── support/          # httpx helpers + JSON checks
├── pytest.ini
├── docker-compose.yml
├── .env.example
└── README.md
```

## Prerequisites

- Docker Engine installed
- Docker Compose available as either:
  - `docker compose` (plugin), or
  - `docker-compose` (standalone v1)
- A valid Gemini API key (`GOOGLE_API_KEY`)

## Configuration

### 1) API key

Create a local `.env` file in project root:

```bash
cp .env.example .env
```

Then set:

```env
GOOGLE_API_KEY=your_real_key_here
```

You can also export it in shell:

```bash
export GOOGLE_API_KEY="your_real_key_here"
```

### 2) Optional environment variables

Defined in `docker-compose.yml` / backend:
- `GOOGLE_API_KEY` - required for Gemini endpoint
- `MISTRAL_API_KEY` - required when using `parser=mistral`
- `GEMINI_MODEL` - default: `gemini-2.5-flash`
- `MISTRAL_MODEL` - default: `mistral-small-latest`
- `MISTRAL_API_BASE_URL` - default: `http://mistral-mock:8001` (local mock)
- `MISTRAL_OCR_MODEL` - vision model for `parser=mistral-ocr` (default: `mistral-small-latest`)
- `MISTRAL_OCR_MAX_PAGES` - max pages processed for `mistral-ocr` (default: `25`)
- `MISTRAL_OCR_RASTER_ZOOM` - PyMuPDF render scale for OCR raster (default: `1.75`)
- `REDIS_URL` - default: `redis://redis:6379/0`
- `CORS_ORIGINS` - default includes local frontend URLs
- `GEMINI_CALL_TIMEOUT_SECONDS` - wall-clock cap for each blocking Gemini SDK call (default: `180`)
- `PDF_PARSE_TIMEOUT_SECONDS` - wall-clock cap for PyPDF extraction in the thread pool (default: `120`)
- `MISTRAL_HTTP_TIMEOUT_SECONDS` - `httpx` read/write timeout for Mistral HTTP calls (default: `120`; connect uses `min(30, value)` seconds)
- `BLOCKING_POOL_MAX_WORKERS` - thread pool size for PyPDF + Gemini blocking work (default: `8`)
- `SYNC_EXTRACT_MAX_CONCURRENT` - max PDFs processed in parallel within one `POST /api/pdf/extract` (default: `min(8, BLOCKING_POOL_MAX_WORKERS)`)
- `LLM_MAX_INFLIGHT` - global cap on concurrent LLM operations per process (Gemini SDK calls, Mistral markdown HTTP, and `POST /api/gemini/answer`; default: `min(8, BLOCKING_POOL_MAX_WORKERS)`)
- `LLM_SLOT_ACQUIRE_TIMEOUT_SECONDS` - seconds to wait for a free LLM slot when saturated (`0` ≈ fail fast → `503` + `Retry-After`; `inf` or `-1` = queue until available)
- **Worker / Streams** — `REDIS_STREAM_DLQ`, `JOB_MAX_PROCESS_ATTEMPTS`, `JOB_MAX_RECLAIMS_PER_MESSAGE`, `JOB_STREAM_CLAIM_IDLE_MS`, `WORKER_XREADGROUP_COUNT`, `WORKER_XREADGROUP_BLOCK_MS`, `WORKER_METRICS_PORT`, `JOB_RETRY_BASE_DELAY_SECONDS`; optional OpenTelemetry: `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_SDK_DISABLED`. See [`docs/STREAMS_CONTRACT.md`](docs/STREAMS_CONTRACT.md).

## Run the project

From project root:

```bash
# From the repository root (directory containing docker-compose.yml)
docker-compose up --build
```

If your environment supports the plugin syntax, this is equivalent:

```bash
docker compose up --build
```

To scrape metrics from the host with a **single** worker, add a `docker-compose.override.yml` (not committed) such as:

```yaml
services:
  worker:
    ports:
      - "9464:9464"
```

### Service URLs

- Frontend: [http://localhost:5173](http://localhost:5173)
- Backend health: [http://localhost:8000/api/health](http://localhost:8000/api/health)
- Worker Prometheus scrape: `http://worker:9464/metrics` from another Compose service, or publish the port in a local override (see below). The default Compose file **exposes** `9464` only so `docker compose up --scale worker=N` does not collide on the host.
- Redis: `localhost:6379`

## How to use

1. Open the frontend at `http://localhost:5173`.
2. Select the interface language from the top-right dropdown.
3. Upload a PDF and click **Extract**.
4. Enter a question and click **Ask Gemini**.
5. Review:
   - extracted text
   - Gemini answer
   - status messages

## Testing

Primary automated suite: **pytest** (`python3 tests/run_pytest.py` — JUnit XML and HTML report under `tests/report/`). This includes **Redis Streams** checks via Testcontainers (`-m streams`; needs Docker). HTTP integration tests expect a running stack. Details: **[`docs/TESTS.md`](docs/TESTS.md)**. Run commands from the project root.

For a manual demo checklist, see [`docs/TEST_CHECKLIST.md`](docs/TEST_CHECKLIST.md).

**Version / footer:** The UI footer at `http://localhost:5173/` uses [`frontend/src/appMeta.ts`](frontend/src/appMeta.ts) (single place to change version, fixed release date, and code author). When you cut a release, update `appMeta.ts` and keep the Markdown footers in `README.md` and `docs/*.md` aligned with the same values.

## Backend API

### `GET /api/health`

Health check endpoint.

Example response:

```json
{ "status": "ok" }
```

### `POST /api/pdf/extract`

Extracts parsed content from uploaded PDF files and caches each file in Redis.

Request:
- `multipart/form-data`
- field: `files` (one or more PDF files)
- field: `parser` (`pypdf` | `gemini-2.5-flash-pdf` | `gemini-2.5-flash-text` | `gemini-2.5-flash` | `mistral` | `mistral-ocr`)
- field: `language` (optional, default: `en`) - language for Gemini summary output

Response:

```json
{
  "results": [
    {
      "filename": "example.pdf",
      "parser": "pypdf",
      "sha256": "file_hash",
      "cached": true,
      "text": "extracted text",
      "pages": [
        { "page": 1, "content": "..." }
      ],
      "summary": "one summary per uploaded file"
    }
  ]
}
```

Notes:
- `pypdf` returns plain extracted text (per page in `pages[]`).
- `gemini-2.5-flash-pdf` sends the **PDF bytes** to Gemini as inline `application/pdf` and returns markdown-oriented output (per page in `pages[]`). Oversized inputs fail with **413** and an explicit message; tune `GEMINI_INLINE_PDF_MAX_BYTES` (default 20 MiB) when appropriate.
- `gemini-2.5-flash-text` runs the **text formatter** path: PyPDF page text → Gemini markdown (per page in `pages[]`).
- `gemini-2.5-flash` is a **legacy alias** for the same formatter pipeline as `gemini-2.5-flash-text` (kept for existing clients).
- `mistral` returns markdown-oriented output generated by Mistral from **PyPDF page text** (per page in `pages[]`).
- `mistral-ocr` **rasterizes** each PDF page to PNG (PyMuPDF), then calls a **Mistral vision** model (`MISTRAL_OCR_MODEL`, default `mistral-small-latest`) once per page with `image_url` data URLs. Suited to scan-heavy PDFs; capped by `MISTRAL_OCR_MAX_PAGES` (default 25). Raster zoom: `MISTRAL_OCR_RASTER_ZOOM` (default `1.75`).
- `summary` is generated using Gemini 2.5 Flash and returned once per uploaded file.
- By default, local Docker uses `mistral-mock` service, so no external Mistral account is required for parser testing.

**Client migration (Gemini parser ids):** prefer `gemini-2.5-flash-text` instead of `gemini-2.5-flash` when you intend the PyPDF→Gemini formatter. Use `gemini-2.5-flash-pdf` when the model should read the PDF as binary. Cache keys are `pdf:{parser}:{sha256}`, so switching parser ids may recompute once per file.

**Scanned PDFs:** text-based parsers (`pypdf`, `gemini-2.5-flash-text`, `mistral`, legacy `gemini-2.5-flash`) only see what PyPDF extracts; image-only pages are often empty. Use **`mistral-ocr`**, **`gemini-2.5-flash-pdf`**, or an external OCR service for raster-first workflows (see `docs/REQUIREMENTS.md`).

### Use real Mistral API instead of local mock

Set the following environment values before starting containers:

```bash
export MISTRAL_API_KEY="your_real_mistral_key"
export MISTRAL_API_BASE_URL="https://api.mistral.ai"
docker-compose up -d --build --force-recreate backend
```

### `POST /api/gemini/answer`

Generates an answer using Gemini, optionally with extracted PDF context.

Request JSON:

```json
{
  "prompt": "Your question",
  "context": "optional extracted text",
  "language": "en"
}
```

Response JSON:

```json
{
  "model": "gemini-2.5-flash",
  "text": "model answer"
}
```

## Language support

Supported language codes for both UI and Gemini answer selection:

- `en` - English
- `pl` - Polish
- `es` - Spanish
- `pt` - Portuguese
- `fr` - French
- `ru` - Russian

Default language: `en`.

## Localization

To edit or add UI languages, see:

- `docs/LOCALIZATION.md`

Locale files are in:

- `frontend/src/locales/`

## Troubleshooting

### Gemini returns `GOOGLE_API_KEY is not set`

- Ensure `.env` exists in project root and contains `GOOGLE_API_KEY=...`
- Recreate backend container:

```bash
docker-compose up -d --build --force-recreate backend
```

### Gemini returns `API_KEY_IP_ADDRESS_BLOCKED` (HTTP 403)

Your API key has IP restrictions in Google Cloud.

Options:
- remove IP restrictions for local testing, or
- allow the actual egress IP used by the backend container

### Frontend does not show latest UI changes

Force refresh browser:
- Linux/Windows: `Ctrl + F5`

If needed, rebuild frontend:

```bash
docker-compose up -d --build --force-recreate frontend
```

## Security notes

- Do not commit `.env` with real secrets.
- Keep API key restricted in production.
- For production environments, prefer stronger auth and secret management over plain API keys in env files.

---

**Async PDF Processor** v.0.0.2 · 14 April 2026 · Code author: Arkadiusz Czerwinski

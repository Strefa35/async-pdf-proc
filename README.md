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
2. `worker` (container `pdf-proc-worker`)
   - consumes Redis Streams (`doc_jobs`) and completes async extraction jobs
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
async-pdf-processor/
├── backend/
│   ├── app/
│   │   └── main.py
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
│   ├── fixtures/
│   │   └── pdf/          # copy sample PDFs here; tests discover all *.pdf in this folder
│   └── ...
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
- `REDIS_URL` - default: `redis://redis:6379/0`
- `CORS_ORIGINS` - default includes local frontend URLs

## Run the project

From project root:

```bash
cd async-pdf-processor
docker-compose up --build
```

If your environment supports the plugin syntax, this is equivalent:

```bash
docker compose up --build
```

### Service URLs

- Frontend: [http://localhost:5173](http://localhost:5173)
- Backend health: [http://localhost:8000/api/health](http://localhost:8000/api/health)
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

Automated tests (`run_smoke_tests.sh`, `run_all_fr_tests.sh` including per-FR scripts and the all-fixtures multi-PDF check, `test_integration_all_fr.sh`), environment variables, and troubleshooting are documented in **[`docs/TESTS.md`](docs/TESTS.md)**. Run commands from the project root.

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
- field: `parser` (`pypdf` | `gemini-2.5-flash` | `mistral`)
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
- `gemini-2.5-flash` returns markdown-oriented output generated by Gemini (per page in `pages[]`).
- `mistral` returns markdown-oriented output generated by Mistral (per page in `pages[]`).
- `summary` is generated using Gemini 2.5 Flash and returned once per uploaded file.
- By default, local Docker uses `mistral-mock` service, so no external Mistral account is required for parser testing.

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

**Async PDF Processor** v.0.0.1 · 26 March 2026 · Code author: Arkadiusz Czerwinski

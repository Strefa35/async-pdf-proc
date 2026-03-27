# Automated tests

This document describes the test scripts under `tests/`, how to run them, and common dependencies. Unless noted, run commands from the **project repository root**. Functional requirements are defined in [`docs/REQUIREMENTS.md`](REQUIREMENTS.md); a manual checklist lives in [`docs/TEST_CHECKLIST.md`](TEST_CHECKLIST.md).

## Prerequisites

| Item | Notes |
|------|--------|
| Running stack | Typically `docker-compose up` (backend, frontend, Redis, worker, optional Mistral mock). |
| PDF files | Place one or more `*.pdf` files under `tests/fixtures/pdf/`. If `PDF_FILE` is **not** set, every PDF in that directory is used (sorted); each smoke / FR / integration block runs once per file. If the directory is empty (or missing) and `PDF_FILE` is unset, scripts exit with a short message (Polish) asking you to add PDFs there. Set `PDF_FILE` to force a single file. |
| `GOOGLE_API_KEY` | Required for summaries (FR-5) and parts of the extraction tests; without it, tests that assert `summary` may fail. |
| `MISTRAL_API_KEY` | Optional; Mistral tests also accept a clear “missing key” response (same idea as in `test_fr2.sh` / smoke). |

Scripts use **bash**, **curl**, and **Python 3** (JSON parsing).

## Environment variables

Shared by most FR and integration tests (see `tests/lib/fr_common.sh`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `BACKEND_URL` | `http://localhost:8000` | Backend API base URL |
| `FRONTEND_URL` | `http://localhost:5173` | Frontend URL (`/api` proxy, FR-7) |
| `PDF_FILE` | *(unset)* | If set, only this path is used. If unset, all `*.pdf` files under `tests/fixtures/pdf/` are discovered (case-insensitive); tests repeat for each file. |
| `PARSER` | `pypdf` | Async multi-PDF batch in `test_integration_all_fr.sh` and `test_multi_pdf_all_fixtures.sh` (`pypdf`, `gemini-2.5-flash`, or `mistral`). |

The smoke test (`run_smoke_tests.sh`) uses the same `BACKEND_URL`, `FRONTEND_URL`, and PDF discovery rules via `tests/lib/fr_common.sh`.

## Script overview

### Smoke — quick end-to-end pass

| Script | Description |
|--------|-------------|
| [`tests/run_smoke_tests.sh`](../tests/run_smoke_tests.sh) | One run: backend and frontend health; for **each** discovered fixture PDF: single- and multi-file extraction, parser selection (`pypdf`, `gemini-2.5-flash`, `mistral`), Redis cache observation, one async job (FR-3); then frontend proxy health and `POST /api/gemini/answer`. |

**Run from the project root:**

```bash
./tests/run_smoke_tests.sh
```

With overrides:

```bash
BACKEND_URL=http://localhost:8000 \
FRONTEND_URL=http://localhost:5173 \
PDF_FILE=/path/to/file.pdf \
./tests/run_smoke_tests.sh
```

Exit code: `0` when `FAIL=0`, otherwise `1`.

---

### Per-requirement tests (FR-1 … FR-7)

| Script | Scope |
|--------|--------|
| [`test_fr1.sh`](../tests/test_fr1.sh) | FR-1: multiple files in one request + `parser` field |
| [`test_fr2.sh`](../tests/test_fr2.sh) | FR-2: `pypdf`, `gemini-2.5-flash`, `mistral` |
| [`test_fr3.sh`](../tests/test_fr3.sh) | FR-3: async `POST /api/jobs/extract`, poll until `done` |
| [`test_fr4.sh`](../tests/test_fr4.sh) | FR-4: `pages[]` in sync response |
| [`test_fr5.sh`](../tests/test_fr5.sh) | FR-5: non-empty `summary` (Gemini) |
| [`test_fr6.sh`](../tests/test_fr6.sh) | FR-6: timestamps, `sha256`, `parser` in sync result |
| [`test_fr7.sh`](../tests/test_fr7.sh) | FR-7: poll `GET /api/jobs/{id}` + optional frontend proxy |
| [`test_multi_pdf_all_fixtures.sh`](../tests/test_multi_pdf_all_fixtures.sh) | **Multi-PDF:** one `POST /api/pdf/extract` and one `POST /api/jobs/extract`, each attaching **every** discovered fixture PDF (requires ≥2 PDFs; otherwise skips with exit 0). Async parser: `PARSER` (default `pypdf`). |

**Run all:**

```bash
./tests/run_all_fr_tests.sh
```

**`run_all_fr_tests.sh` options:**

- `--reverse` — order fr7 … fr1, then `multi`  
- `--shuffle` — random order (includes `multi`)  
- `--order fr7,fr5,…` — custom order (include `multi` to run the all-fixtures multi-PDF script)  
- `--only fr3,fr5` — subset only (`--only multi` runs only that script)  

`./tests/run_all_fr_tests.sh` runs FR tags **once per fixture PDF**, then runs tag **`multi` once** (all PDFs in one sync + one async request), unless you omit `multi` from `--order` / `--only`.

Shared JSON / poll helpers and PDF fixture discovery: [`tests/lib/fr_common.sh`](../tests/lib/fr_common.sh). Smoke tests keep additional inline check helpers in `run_smoke_tests.sh`.

---

### Integration test (“all FRs”)

| Script | Description |
|--------|-------------|
| [`tests/test_integration_all_fr.sh`](../tests/test_integration_all_fr.sh) | One run: job API edge cases (404, empty file, no files), then FR-1 and FR-4…FR-7 on sync and async paths for **each** discovered fixture PDF (including `pages[]`, `summary`, timestamps, `sha256` / `parser` on job results), FR-2, FR-7 (proxy), optional **multi-PDF async batch** when at least two PDFs exist under `tests/fixtures/pdf/` (posts all discovered files). Override batch parser with `PARSER`. |

```bash
./tests/test_integration_all_fr.sh
# Optional: exercise batch with another parser
PARSER=gemini-2.5-flash ./tests/test_integration_all_fr.sh
```

This is the broadest single-script end-to-end requirement sweep; slower than an individual `test_frN.sh`, but one report with many assertions.

---

## What to run when

| Situation | Suggestion |
|-----------|------------|
| Quick check after containers start | `./tests/run_smoke_tests.sh` |
| Requirement-by-requirement regression or custom order | `./tests/run_all_fr_tests.sh` (+ options) |
| Single report covering FR-1…FR-7, edges, optional multi-file async batch | `./tests/test_integration_all_fr.sh` (fixture PDFs live under `tests/fixtures/pdf/`) |

## Troubleshooting

- **No PDF fixtures** — add at least one `*.pdf` under `tests/fixtures/pdf/`, or set `PDF_FILE` to a specific path.  
- **Job timeout / `failed`** — ensure the worker (`pdf-proc-worker`) and Redis are running; check Compose logs.  
- **Empty `summary` / Gemini errors** — `GOOGLE_API_KEY` on the backend; API quotas or restrictions on Google’s side.  
- **FR-7 / proxy** — the frontend must listen on `FRONTEND_URL`; backend-only setups may show a warning without failing the whole `test_fr7.sh` (depends on the script).  
- **Mistral** — without a key, tests may pass on the “expected missing-key message” instead of full extraction.

## Related files

- [`docs/REQUIREMENTS.md`](REQUIREMENTS.md) — requirements (including FR-1…FR-7).  
- [`docs/IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) — implementation vs requirements.  
- [`docs/TEST_CHECKLIST.md`](TEST_CHECKLIST.md) — manual checklist.  
- [`README.md`](../README.md) — project overview; points here for testing details.

---

**Async PDF Processor** v.0.0.1 · 26 March 2026 · Code author: Arkadiusz Czerwinski

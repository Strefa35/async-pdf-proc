# Automated tests

This document describes how to run the **Python (pytest + httpx)** integration suite. Unless noted, run commands from the **project repository root**. Functional requirements are in [`docs/REQUIREMENTS.md`](REQUIREMENTS.md); a manual checklist is in [`docs/TEST_CHECKLIST.md`](TEST_CHECKLIST.md).

## Prerequisites

| Item | Notes |
|------|--------|
| Running stack | For `integration` / FR tests: typically `docker compose up` (backend, frontend, Redis, worker, optional Mistral mock). For `-m unit` only: **Redis** must accept TCP connections at `REDIS_URL` (default host port `6379`). |
| PDF files | Place one or more `*.pdf` files under `tests/fixtures/pdf/`. If `PDF_FILE` is **not** set, every PDF in that directory is used (sorted); parametrized tests run once per file. If the directory is empty (or missing) and `PDF_FILE` is unset, PDF-dependent tests are **skipped**. Set `PDF_FILE` to force a single file. |
| `GOOGLE_API_KEY` | Required for summaries (FR-5) and parts of the extraction tests; without it, tests that assert `summary` may fail. |
| `MISTRAL_API_KEY` | Optional; Mistral tests also accept a clear “missing key” response (same idea as in FR-2 / smoke). |

**Docker container names (local Compose):** `docker-compose.yml` sets Compose project name `async-pdf-proc` and explicit `container_name` values `async-pdf-proc-backend`, `async-pdf-proc-frontend`, `async-pdf-proc-redis`, and `async-pdf-proc-mistral-mock`. The `worker` service has no fixed `container_name`, so instances appear as `async-pdf-proc-worker-1`, `async-pdf-proc-worker-2`, … when scaled. Service DNS names inside the stack remain `backend`, `frontend`, `redis`, `worker`, and `mistral-mock`.

**Download fixtures** (small PrinceXML sample PDFs):

```bash
python3 tests/download_pdf_fixtures.py
```

Options:

- `--force` — re-download even if files exist  
- `--strict` — exit with non-zero status if any download fails  

## Pytest suite

| Item | Notes |
|------|--------|
| Dependencies | [`tests/requirements-pytest.txt`](../tests/requirements-pytest.txt) (includes [`backend/requirements.txt`](../backend/requirements.txt) for `unit` tests that import the FastAPI app) |
| Runner | [`tests/run_pytest.py`](../tests/run_pytest.py) — creates `.pytest-venv/` (override with `PYTEST_VENV`), installs requirements, runs pytest |
| Reports | `tests/report/junit.xml` (JUnit) and `tests/report/report.html` (self-contained HTML via `pytest-html`) |
| Markers | See [`pytest.ini`](../pytest.ini). Highlights: `unit` (in-process ASGI; needs **Redis** reachable at `REDIS_URL`, default `redis://127.0.0.1:6379/0`), `streams` (Redis Streams + **Testcontainers**; needs **Docker**), `integration` (live HTTP), `smoke`, `fr1`…`fr7`, `multi` |
| Worker retry (unit, PR-TR-7) | [`tests/test_worker_failure_classification.py`](../tests/test_worker_failure_classification.py) — `test_transient_retry_defers_xadd_until_after_backoff_task` checks that retry **`XADD`** runs only after the delayed backoff task (main consumer path not blocked). Mocks Redis and `_process_pdf_bytes`; patches **`app.worker._retry_backoff_sleep`** (avoids patching global `asyncio.sleep`). No Docker. |

**Run the full suite** (stack must be up for `integration` tests; `unit` tests only need Redis):

```bash
python3 tests/run_pytest.py
```

Examples:

```bash
python3 tests/run_pytest.py -m unit
python3 tests/run_pytest.py -k "health or edges"
python3 tests/run_pytest.py -m smoke
```

Extra arguments are forwarded to pytest.

### Redis Streams (`streams` marker, PR-TR-14)

[`tests/test_redis_streams_integration.py`](../tests/test_redis_streams_integration.py) starts a disposable **Redis 7** container via **Testcontainers** and exercises consumer groups, `XREADGROUP` / `XACK`, `XAUTOCLAIM` on stale pending entries, a DLQ-style `XADD` + primary `XACK`, and duplicate `XGROUP CREATE` (`BUSYGROUP`).

- **Requires:** a working Docker daemon (same as CI after `docker compose` is available on the host).
- **Skip:** `SKIP_STREAMS_TESTS=1` or `python3 tests/run_pytest.py -m "not streams"` if you cannot run Docker locally.
- **Run only Streams tests:** `python3 tests/run_pytest.py -m streams`

### FR-only runner (ordered subprocesses)

[`tests/run_fr_tests.py`](../tests/run_fr_tests.py) reproduces the old `run_all_fr_tests.sh` behavior: one pytest invocation per tag so order is deterministic. The `multi` tag runs with `PDF_FILE` removed so all fixtures in `tests/fixtures/pdf/` are visible.

```bash
python3 tests/run_fr_tests.py
python3 tests/run_fr_tests.py --reverse
python3 tests/run_fr_tests.py --shuffle
python3 tests/run_fr_tests.py --order fr7,fr5,fr1
python3 tests/run_fr_tests.py --only fr3,fr5,multi
python3 tests/run_fr_tests.py --only fr1 -- -x
```

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `BACKEND_URL` | `http://localhost:8000` | Backend API base URL |
| `FRONTEND_URL` | `http://localhost:5173` | Frontend URL (`/api` proxy, FR-7) |
| `PDF_FILE` | *(unset)* | If set, only this path is used for parametrized tests. If unset, all `*.pdf` under `tests/fixtures/pdf/` are used. |
| `PARSER` | `pypdf` | Parser for the **multi-PDF async** test (`pypdf`, `gemini-2.5-flash-pdf`, `gemini-2.5-flash-text`, `gemini-2.5-flash`, `mistral`, or `mistral-ocr`). |
| `E2E_HTTP_TIMEOUT` | `180` | Default `httpx` timeout (seconds). |
| `PYTEST_VENV` | *(unset → `.pytest-venv/`)* | Virtualenv path used by `run_pytest.py` / `run_fr_tests.py`. |

## What each area covers

| Area | Pytest modules |
|------|----------------|
| Health | `test_health.py` — backend `/api/health`, frontend `/`, frontend `/api/health` |
| Smoke | `test_smoke.py` — extract, parsers, cache hint, async job, Gemini answer |
| FR-1 … FR-7 | `test_fr1_upload.py` … `test_fr7_proxy.py` (markers `fr1`…`fr7`) |
| Integration edges | `test_integration_edges.py` — unknown job 404, empty file, no files |
| Integration sweep | `test_integration_per_pdf.py` — broad sync + async checks per PDF |
| Multi-PDF all fixtures | `test_multi_pdf_all_fixtures.py` (marker `multi`) — one sync + one async request with every fixture PDF |

Shared helpers: `tests/support/checks.py`, `tests/support/http_api.py`, `tests/support/pdf_fixtures.py`, `tests/conftest.py`.

## CI

[`scripts/ci_build_and_test.sh`](../scripts/ci_build_and_test.sh) builds and starts the Compose stack, waits until services are ready, runs `python3 tests/download_pdf_fixtures.py --force --strict`, then `python3 tests/run_pytest.py`. GitHub Actions uploads `tests/report/` as the **pytest-reports** artifact.

**Stack readiness**

- If `docker compose up` supports **`--wait`**, the script uses **`up -d --build --wait --wait-timeout 120`** so Compose blocks until healthchecks pass (when defined).
- Regardless of `--wait`, the script then polls with **`curl`** until:
  - `http://127.0.0.1:8000/api/health` (backend), and  
  - `http://127.0.0.1:5173/api/health` (frontend Vite proxy to backend health)  
  return HTTP 200. **`curl`** must be on `PATH`.
- Tune polling (optional):

| Variable | Default | Purpose |
|----------|---------|---------|
| `CI_STACK_READY_TIMEOUT_SECONDS` | `120` | Max seconds to wait for each readiness URL |
| `CI_STACK_READY_POLL_INTERVAL_SECONDS` | `2` | Sleep between polls |

## Troubleshooting

- **No PDF fixtures** — run `python3 tests/download_pdf_fixtures.py` or add PDFs under `tests/fixtures/pdf/`, or set `PDF_FILE`.  
- **Job timeout / `failed`** — ensure the `worker` service and Redis are running; check Compose logs.  
- **Empty `summary` / Gemini errors** — `GOOGLE_API_KEY` on the backend; API quotas or restrictions on Google’s side.  
- **FR-7 / proxy** — the frontend must listen on `FRONTEND_URL`; if the proxy path is wrong, related checks may **skip** without failing the suite.  
- **Mistral** — without a key, tests may pass on the “expected missing-key message” instead of full extraction.

## Related files

- [`docs/REQUIREMENTS.md`](REQUIREMENTS.md) — requirements (including FR-1…FR-7).  
- [`docs/IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) — implementation vs requirements.  
- [`docs/TEST_CHECKLIST.md`](TEST_CHECKLIST.md) — manual checklist.  
- [`README.md`](../README.md) — project overview.

---

**Async PDF Processor** v.0.0.2 · 14 April 2026 · Code author: Arkadiusz Czerwinski

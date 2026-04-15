# Test Checklist

Use this checklist during local validation and demo sessions.

Date: `__________`  
Tester: `__________`  
Environment: `local / staging / other: __________`

**Automated regression (optional):** primary suite is **pytest** via `python3 tests/run_pytest.py` (see [`docs/TESTS.md`](TESTS.md): markers, Streams tests, FR-ordered runner).

---

## 1) Preconditions

- [ ] Docker Compose stack is running (`async-pdf-proc-backend`, `async-pdf-proc-frontend`, `async-pdf-proc-redis`, `async-pdf-proc-mistral-mock`, workers `async-pdf-proc-worker-<n>` per `docker-compose.yml`)
- [ ] `GOOGLE_API_KEY` is configured
- [ ] At least one sample PDF is under `tests/fixtures/pdf/` (copy your own files; example path for commands below: `tests/fixtures/pdf/drylab.pdf`)

---

## 2) Smoke Tests

- [ ] **Health endpoint** returns `200` and `{"status":"ok"}`
  - Command: `curl -s http://localhost:8000/api/health`
- [ ] **Frontend URL** is reachable (`http://localhost:5173`)

---

## 3) PDF Extraction Tests

Commands below assume the **repository root** (directory containing `docker-compose.yml`; clone folder name may differ). Place sample PDFs under `tests/fixtures/pdf/` (not necessarily committed); example filenames in curl commands use `drylab.pdf` if present.

- [ ] **Single-file extraction** works
  - Command:
    `curl -s -X POST http://localhost:8000/api/pdf/extract -F "files=@tests/fixtures/pdf/drylab.pdf"`
- [ ] Response contains `results[0].filename`, `sha256`, `cached`, `text`, `pages`
- [ ] Response contains `results[0].summary` and `results[0].summary` is non-empty
- [ ] `results[0]` contains `content_generated_at` and `summary_generated_at` fields
- [ ] `pages[]` entries contain `page` and `content`

- [ ] **Multi-file extraction (FR-1)** works in one request
  - Command:
    `curl -s -X POST http://localhost:8000/api/pdf/extract -F "files=@tests/fixtures/pdf/drylab.pdf" -F "files=@tests/fixtures/pdf/drylab.pdf"`
- [ ] Response contains two entries in `results`

- [ ] **Parser selection (FR-2)** works for extraction
  - [ ] `parser=pypdf` returns extracted plain text
  - [ ] `parser=gemini-2.5-flash-text` (or legacy `parser=gemini-2.5-flash`) returns markdown from the PyPDF→Gemini formatter
  - [ ] `parser=gemini-2.5-flash-pdf` returns markdown from Gemini native inline PDF input
  - [ ] `parser=mistral` returns markdown-oriented output (local `mistral-mock` by default)
  - [ ] `parser=mistral-ocr` returns markdown from raster + vision mock (one request per page)
  - [ ] (Optional) with real external Mistral API configured, `parser=mistral` still returns markdown output
- [ ] **FR-4 Parsed output per page** works
  - [ ] Response contains `results[0].pages` with one entry per PDF page (best effort)
  - [ ] `pages[].content` is non-empty for pages that have extractable text

- [ ] **Cache behavior** verified for same file
  - [ ] First extraction can produce `cached=false` (after cache reset)
  - [ ] Next extraction returns `cached=true`

---

## 3b) Async Processing Tests (FR-3)

- [ ] **Async job submission** works (`POST /api/jobs/extract`)
  - Command:
    `curl -s -X POST http://localhost:8000/api/jobs/extract -F "parser=pypdf" -F "files=@tests/fixtures/pdf/drylab.pdf"`
  - Expected: response contains `jobs[0].job_id`

- [ ] **Async job completion** (poll until `status=done`)
  - Command example:
    `curl -s http://localhost:8000/api/jobs/<job_id>`
  - Expected:
    - `status` becomes `done`
    - `result.text` is non-empty
    - `result.summary` is non-empty
    - `result.content_generated_at` and `result.summary_generated_at` fields exist
    - `result.parser` matches selected parser

---
## 3c) Async Frontend Polling (FR-7)

- [ ] UI async extraction works
  - [ ] Click `Extract async`
  - [ ] UI shows a list of `async jobs` with `queued/processing/done/failed`
  - [ ] After `done`, the corresponding file result is rendered (pages/text/summary)
  - [ ] After `failed`, the UI shows a clear error for that file

---

## 4) Gemini Tests

- [ ] **Gemini endpoint basic call** works (`200`, non-empty `text`)
  - Command:
    `curl -s -X POST http://localhost:8000/api/gemini/answer -H "content-type: application/json" -d '{"prompt":"Short test in English.","context":"","language":"en"}'`

- [ ] **Language switching for model output** works
  - [ ] `en` response is in English
  - [ ] `pl` response is in Polish
  - [ ] `es` response is in Spanish
  - [ ] `pt` response is in Portuguese
  - [ ] `fr` response is in French
  - [ ] `ru` response is in Russian

---

## 5) Frontend Integration Tests

- [ ] `/api` proxy from frontend to backend works
  - Command: `curl -s http://localhost:5173/api/health`

- [ ] Extraction through frontend proxy works
  - Command:
    `curl -s -X POST http://localhost:5173/api/pdf/extract -F "files=@tests/fixtures/pdf/drylab.pdf"`

- [ ] **UI language switcher** updates interface labels
  - [ ] Header and section titles update
  - [ ] Status label/messages update
  - [ ] Placeholder/labels update

- [ ] **UI multi-file upload UX** works
  - [ ] Multiple files can be selected in picker
  - [ ] Selected file names are visible in UI
  - [ ] Extract result is shown per file

---

## 6) Negative / Error Tests

- [ ] Missing `GOOGLE_API_KEY` returns clear error
- [ ] Invalid/empty upload returns `400` with useful message
- [ ] Provider-side key restriction error is surfaced clearly (e.g. IP restriction)

---

## 7) Regression Quick Pass

- [ ] Backend still starts correctly
- [ ] Multi-file extraction still works
- [ ] Redis cache still works
- [ ] Gemini endpoint still works
- [ ] Frontend still renders and can call backend

---

## 8) Result Summary

- Passed: `____`
- Failed: `____`
- Blocked: `____`

Notes:

- `____________________________________________________________`
- `____________________________________________________________`

---

**Async PDF Processor** v.0.0.2 · 14 April 2026 · Code author: Arkadiusz Czerwinski

# Project Requirements

## 1. Goal

Build an asynchronous document processing application where users upload one or more PDF files and later receive:
- parsed content per page (text or markdown),
- one summary per uploaded file.

The system must prioritize backend implementation and asynchronous processing.

---

## 2. Core Functional Requirements

### FR-1: Document Upload
- The application must accept one or more PDF files from the user.
- The upload request must include the desired parser selection.

### FR-2: Parser Selection
- The user must be able to choose a parser method.
- Supported parser methods:
  - `pypdf` (text extraction),
  - `gemini-2.5-flash-pdf` (Gemini multimodal input: PDF bytes → markdown per page),
  - `gemini-2.5-flash-text` (formatter: PyPDF page text → Gemini markdown),
  - `gemini-2.5-flash` (**legacy identifier**, same pipeline as `gemini-2.5-flash-text`; retained for backward compatibility),
  - `mistral` (nice-to-have, lowest priority: PyPDF text → Mistral chat markdown),
  - `mistral-ocr` (optional OCR-style path: rasterize pages with PyMuPDF → Mistral vision chat per page → markdown).

#### Gemini parsing modes (product clarity)
- **Native PDF (`gemini-2.5-flash-pdf`):** the model receives `application/pdf` inline data as the primary document signal. Page boundaries for splitting use PyPDF **page count only** (not page text as model input).
- **Text formatter (`gemini-2.5-flash-text` and legacy `gemini-2.5-flash`):** PyPDF extracts per-page text, then Gemini formats it to markdown. This path does **not** perform separate OCR; scanned or image-only pages often yield empty PyPDF text (see scanned-PDF note below).

#### Mistral OCR pipeline (`mistral-ocr`)
- Pages are rendered to PNG bitmaps (PyMuPDF) and sent to the Mistral Chat Completions API as `image_url` parts (base64 data URLs), **one HTTP request per page** (same endpoint as `mistral`, different message shape).
- Vision model id comes from `MISTRAL_OCR_MODEL`. Page count is limited by `MISTRAL_OCR_MAX_PAGES` (HTTP **400** if the PDF exceeds the cap).
- This is **not** Mistral Document AI / batch OCR; it is an in-process raster + vision transcription path suitable for scan-heavy PDFs within cost and latency constraints.

#### Scanned / image-heavy PDFs
- **`pypdf`, `gemini-2.5-flash-text`, `mistral`, legacy `gemini-2.5-flash`:** rely on PyPDF (or equivalent text-in) for page content. Pages with no extractable text produce empty strings; downstream markdown may be empty or unhelpful. There is **no PyPDF-text OCR** for those parsers.
- **`gemini-2.5-flash-pdf`:** the model can often read rasterized page content from the PDF bytes, subject to provider limits, policy, and document size (`GEMINI_INLINE_PDF_MAX_BYTES`). Oversized files receive HTTP `413` with a clear message (no silent fallback to the text formatter).
- **`mistral-ocr`:** uses rendered page images, so scanned pages are visible to the vision model subject to Mistral limits and `MISTRAL_OCR_MAX_PAGES`.

### FR-3: Asynchronous Processing
- Processing must be asynchronous (not blocking the upload request).
- Redis Streams must be used as the processing queue mechanism.

### FR-4: Parsed Output
- For each uploaded PDF, the backend must produce parsed document content.
- The output format should be markdown when possible; plain text is acceptable for `pypdf`.

### FR-5: Summarization
- The backend must generate one summary per uploaded PDF file.
- Summarization must use Google Gemini 2.5 Flash.

### FR-6: Persistence / Cache
- Processing results must be stored in Redis.
- At minimum, store:
  - parser type used,
  - parsed content,
  - generated summary,
  - processing status.

### FR-7: Result Retrieval
- The user must be able to retrieve processing results after completion.
- Frontend delivery options may use polling, SSE, or WebSockets.
- If frontend is incomplete, result retrieval via Postman/cURL is acceptable for demo.

---

## 3. Technical Requirements

### TR-1: Backend
- Language/runtime: Python 3.12+
- Framework: FastAPI
- Must support concurrent API requests.

### TR-2: Queue and Data Store
- Redis version: v7+
- Redis Streams must be used for async job processing.

### TR-3: PDF Processing Libraries / Services
- PyPDF for basic parsing.
- Google Gemini 2.5 Flash for advanced markdown parsing and summarization.

### TR-4: Frontend
- React (or Next.js), JavaScript or TypeScript.
- Frontend is lower priority than backend and may be minimal.

### TR-5: Containerization
- All application components must run in Docker Compose.
- Implemented stack: backend API, async **worker**, Redis, frontend, and local **mistral-mock** (Mistral-compatible HTTP for local parser tests).

---

## 4. API Expectations (High-Level)

The API should support:
1. Upload endpoint:
   - accepts one or more PDFs,
   - accepts parser selection (`pypdf`, `gemini-2.5-flash-pdf`, `gemini-2.5-flash-text`, `gemini-2.5-flash`, `mistral`, `mistral-ocr`),
   - returns job identifier(s) and initial status.
2. Status/result endpoint(s):
   - returns job status (`queued`, `processing`, `done`, `failed`),
   - returns parsed output and summary when ready.

---

## 5. Priority Order

Implementation priority (highest to lowest):
1. Backend application serving concurrent requests.
2. Document upload and processing with PyPDF.
3. Async processing queue with Redis Streams.
4. Summarization via Gemini 2.5 Flash.
5. Document processing via Mistral OCR.
6. Frontend.

---

## 6. Non-Functional Requirements

- Reliability: Jobs should not be lost during normal operation.
- Observability: Processing status should be traceable per job/document.
- Scalability: Design should allow adding worker instances for queue consumers.
- Error handling: Failed jobs should return clear failure details.

---

## 7. Assumptions

- Public sample PDFs can be used for demonstration.
- If some details are ambiguous, reasonable implementation assumptions are allowed.
- If blocked by technical limitations, practical workarounds are acceptable to keep progress.

---

## 8. Acceptance Criteria

The requirements are considered met when:

1. A client can upload one or more PDFs and choose parser type.
2. Upload request is handled asynchronously through Redis Streams.
3. Each file eventually produces:
   - parsed content,
   - one summary.
4. Results can be queried by API and displayed to the user (or demonstrated via Postman/cURL).
5. Services run in Docker Compose with backend + Redis (+ frontend if included).

---

## 9. Test Plan

This section defines the minimum test scope to validate the implementation.

**Automated tests** (pytest + `tests/run_pytest.py`, `tests/run_fr_tests.py`, `tests/download_pdf_fixtures.py`) and how to run them are documented in **`docs/TESTS.md`**.

### 9.1 Preconditions

- Services are running via Docker Compose.
- `GOOGLE_API_KEY` is configured for Gemini tests.
- At least one sample PDF is available under `tests/fixtures/pdf/` (for example `drylab.pdf`; testers typically copy PDFs into that folder — see `docs/TESTS.md`).

### 9.2 Smoke Tests

#### TP-01: Backend health endpoint
**Goal:** Verify backend is alive.  
**Command:**

```bash
curl -s http://localhost:8000/api/health
```

**Expected result:** HTTP `200`, body contains `{"status":"ok"}`.

#### TP-02: Frontend availability
**Goal:** Verify frontend is accessible.  
**Command:**

```bash
curl -I http://localhost:5173/
```

**Expected result:** HTTP `200`.

### 9.3 PDF Processing Tests

#### TP-03: Single PDF extraction
**Goal:** Verify extraction pipeline for one file.  
**Command** (from project root; path is relative to that directory):

```bash
curl -s -X POST http://localhost:8000/api/pdf/extract \
  -F "files=@tests/fixtures/pdf/drylab.pdf"
```

**Expected result:** HTTP `200`, `results[0]` contains `filename`, `sha256`, `cached`, `text`, `pages`, and `summary`.

#### TP-04: Multi-PDF extraction (FR-1 validation)
**Goal:** Verify multiple files in one request are processed.  
**Command** (from project root):

```bash
curl -s -X POST http://localhost:8000/api/pdf/extract \
  -F "files=@tests/fixtures/pdf/drylab.pdf" \
  -F "files=@tests/fixtures/pdf/drylab.pdf"
```

**Expected result:** HTTP `200`, response has `results` array with 2 entries.

#### TP-05: Redis cache behavior
**Goal:** Verify first extraction is uncached and second is cached (for the same file hash).  
**Procedure:**
1. Delete Redis key for the file hash (optional reset).
2. Call extraction twice for same file.

**Expected result:** First call returns `cached=false`, second returns `cached=true`.

### 9.4 Gemini Tests

#### TP-06: Gemini endpoint basic request
**Goal:** Verify Gemini integration works.  
**Command:**

```bash
curl -s -X POST http://localhost:8000/api/gemini/answer \
  -H "content-type: application/json" \
  -d '{"prompt":"Short test in English.","context":"","language":"en"}'
```

**Expected result:** HTTP `200`, response contains `model` and non-empty `text`.

#### TP-07: Language selection for Gemini response
**Goal:** Verify language routing in backend prompt generation.  
**Command example (`es`):**

```bash
curl -s -X POST http://localhost:8000/api/gemini/answer \
  -H "content-type: application/json" \
  -d '{"prompt":"Respond in Spanish.","context":"","language":"es"}'
```

**Expected result:** HTTP `200`, response text is in selected language (Spanish in this case).

### 9.5 Frontend Integration Tests

#### TP-08: Frontend proxy to backend health
**Goal:** Verify frontend `/api` proxy path.  
**Command:**

```bash
curl -s http://localhost:5173/api/health
```

**Expected result:** HTTP `200`, body `{"status":"ok"}`.

#### TP-09: Frontend-driven extraction API path
**Goal:** Verify extraction works through frontend proxy.  
**Command** (from project root):

```bash
curl -s -X POST http://localhost:5173/api/pdf/extract \
  -F "files=@tests/fixtures/pdf/drylab.pdf"
```

**Expected result:** HTTP `200`, response includes `results[0].text`, `results[0].pages`, and `results[0].summary`.

#### TP-10: UI language switch
**Goal:** Verify interface strings change when selecting language in top-right dropdown.  
**Procedure:**
1. Open `http://localhost:5173`.
2. Change language (for example `en -> pl -> fr`).
3. Observe section titles, labels, status text.

**Expected result:** UI labels update to selected language.

### 9.6 Negative / Error Tests

#### TP-11: Missing API key for Gemini
**Goal:** Verify proper error handling when `GOOGLE_API_KEY` is not configured.  
**Expected result:** Endpoint returns clear error (`GOOGLE_API_KEY is not set` or equivalent).

#### TP-12: Invalid/empty file upload
**Goal:** Verify extraction endpoint rejects invalid payloads cleanly.  
**Expected result:** HTTP `400` with meaningful error details.

#### TP-13: Restricted API key (IP-restricted)
**Goal:** Verify diagnostics are understandable when provider blocks requests.  
**Expected result:** Backend returns HTTP `502` with propagated Gemini error details.

### 9.7 Regression Checklist (After Every Major Change)

- Backend starts and health endpoint is green.
- Multi-file upload still works.
- Cache still works (`cached` transitions are correct).
- Gemini endpoint still returns responses in selected language.
- Frontend can call backend via `/api` proxy.

---

**Async PDF Processor** v.0.0.2 · 14 April 2026 · Code author: Arkadiusz Czerwinski

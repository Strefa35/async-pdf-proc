# Architecture

This document describes how **Async PDF Processor** is structured at runtime, how requests flow through the stack, and how asynchronous jobs use **Redis Streams**. For stream semantics (retries, `XACK`, DLQ), see [`STREAMS_CONTRACT.md`](STREAMS_CONTRACT.md).

---

## 1. System context

The application is a small **document ingestion and LLM-assisted extraction** system: users upload PDFs, choose a parser, and receive per-page text or markdown plus a **Gemini 2.5 Flash** summary per file. Processing may run **synchronously** in the API or **asynchronously** via a dedicated worker.

```mermaid
flowchart LR
  subgraph Users
    U[Browser / API client]
  end

  subgraph DockerCompose["Docker Compose stack"]
    FE[Frontend\nVite + React]
    API[Backend\nFastAPI]
    W[Worker\nasync-pdf-proc-worker-*]
    R[(Redis 7+\nStreams + cache)]
    MM[Mistral mock\noptional local LLM]
  end

  subgraph External["External providers"]
    G[Google Gemini API]
    M[Mistral API\nor mock]
  end

  U --> FE
  U --> API
  FE -->|HTTP /api proxy| API
  API --> R
  W --> R
  API --> G
  W --> G
  API --> M
  W --> M
  MM -.->|same HTTP surface| M
```

---

## 2. Containers and ports

| Service | Docker container name | Role | Default host port |
|--------|----------------------|------|-------------------|
| `frontend` | `async-pdf-proc-frontend` | React UI; dev server proxies `/api` to backend | `5173` |
| `backend` | `async-pdf-proc-backend` | FastAPI: health, sync extract, async job API, Gemini Q&A | `8000` |
| `worker` | `async-pdf-proc-worker-<n>` | Async consumer: `XREADGROUP` on job stream, metrics on `9464` (expose) | metrics only |
| `redis` | `async-pdf-proc-redis` | Job stream, consumer group, job state JSON, PDF blob staging, content cache | `6379` |
| `mistral-mock` | `async-pdf-proc-mistral-mock` | Local HTTP server mimicking Mistral chat for tests / no-key demos | `8001` |

```mermaid
flowchart TB
  subgraph compose["docker-compose.yml"]
    FE[frontend]
    BE[backend]
    WRK[worker]
    RD[(redis)]
    MOCK[mistral-mock]
  end

  FE -->|depends_on| BE
  BE --> RD
  BE --> MOCK
  WRK --> RD
  WRK --> MOCK
```

---

## 3. Backend and worker processes

Both **backend** and **worker** are built from the same `backend/` image. They import shared logic from `app.main` (notably `_process_pdf_bytes`, Redis helpers, blocking executor, LLM slot semaphore).

```mermaid
flowchart LR
  subgraph api_proc["Process: uvicorn → app.main:app"]
    R1[FastAPI routes]
    B1[_run_blocking /\nThreadPoolExecutor]
    S1[LLM semaphore\n_llm_slot]
    C1[Redis read/write]
  end

  subgraph worker_proc["Process: python -m app.worker"]
    L1[XREADGROUP /\nXAUTOCLAIM loop]
    P1[_process_pdf_bytes]
    B2[same blocking + LLM limits]
    O1[JSON logs, Prometheus,\noptional OTLP]
  end

  R1 --> B1
  R1 --> S1
  R1 --> C1
  L1 --> P1 --> B2
  L1 --> O1
```

**Why two processes?** The API stays responsive for uploads, polling, and health checks while long-running PDF and LLM work drains from the stream in the worker. Both paths enforce **bounded** blocking work and **capped** in-flight LLM calls (see `IMPLEMENTATION_STATUS.md`, PR-TR-1–PR-TR-5).

---

## 4. API surface (logical)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | Liveness for stack / tests |
| `POST` | `/api/pdf/extract` | Synchronous multi-file extract + summary |
| `POST` | `/api/jobs/extract` | Enqueue async job (PDF bytes staged in Redis) |
| `GET` | `/api/jobs/{job_id}` | Poll job status and result |
| `POST` | `/api/gemini/answer` | Q&A over user text with optional language |

---

## 5. Synchronous extract flow

```mermaid
sequenceDiagram
  participant C as Client
  participant API as Backend
  participant Pool as Blocking pool
  participant R as Redis
  participant G as Gemini

  C->>API: POST /api/pdf/extract multipart
  API->>R: cache lookup by sha256 + parser
  alt cache hit
    API-->>C: cached text / pages / summary
  else cache miss
    API->>Pool: PyPDF / raster / HTTP as needed
    Pool-->>API: raw page texts or assets
    API->>G: markdown format + summarize (parser-dependent)
    G-->>API: markdown + summary
    API->>R: SET cache keys + job metadata if any
    API-->>C: text, pages[], summary, timestamps
  end
```

**Concurrency:** Multiple files in one request are processed with bounded parallelism (`SYNC_EXTRACT_MAX_CONCURRENT`). LLM steps acquire a global semaphore; saturation yields `503` + `Retry-After` or per-file errors depending on the route.

---

## 6. Asynchronous job flow (Redis Streams)

High-level stages: **enqueue → stream message → worker claims → process → job record → client polls**.

```mermaid
flowchart TD
  A[POST /api/jobs/extract] --> B[Create job_id\nstatus queued]
  B --> C[Store PDF blob in Redis\nTTL]
  C --> D[XADD doc_jobs\nfields: job_id, attempt, ...]
  D --> E[Return job_id to client]

  W[Worker loop] --> F[XREADGROUP / XAUTOCLAIM]
  F --> G{Job already done?}
  G -->|yes| H[XACK skip idempotent]
  G -->|no| I[status processing]
  I --> J[_process_pdf_bytes\nsame as sync path]
  J --> K{Outcome}
  K -->|success| L[status done + result\nXACK]
  K -->|transient + attempts left| M[Backoff + XADD new message\nXACK old]
  K -->|terminal failure| N[status failed\nXACK]
  K -->|max attempts / reclaims| O[XADD doc_jobs_dlq\nXACK]

  P[GET /api/jobs/job_id] --> Q[Read doc:job:...]
```

**Stream names (defaults):** `doc_jobs` (primary queue), `doc_jobs_dlq` (dead letter). **Consumer group:** `doc_workers`. Job state: Redis key `doc:job:{job_id}` (JSON).

---

## 7. Worker internal loop (simplified)

```mermaid
stateDiagram-v2
  [*] --> Read: XREADGROUP COUNT BLOCK
  Read --> Claim: optional XAUTOCLAIM idle messages
  Claim --> Handle: for each message id
  Handle --> Idempotent: if job done
  Idempotent --> AckSkip: XACK
  Handle --> Process: load blob, run pipeline
  Process --> Success: XACK
  Process --> Retry: transient, attempt++
  Retry --> Reenqueue: XADD then XACK
  Process --> Fail: XACK + job failed
  Process --> DLQ: poison / max reclaim
  AckSkip --> Read
  Success --> Read
  Reenqueue --> Read
  Fail --> Read
  DLQ --> Read
```

Exact ordering and policies are specified in [`STREAMS_CONTRACT.md`](STREAMS_CONTRACT.md).

---

## 8. Parser pipelines (conceptual)

All parsers converge on **per-page arrays** and a **single summary per file** (Gemini). Paths differ in how markdown is produced.

```mermaid
flowchart TB
  PDF[PDF bytes]

  PDF --> P1[pypdf]
  P1 --> T1[Plain text pages]
  T1 --> S1[Summary only via Gemini]

  PDF --> P2[gemini-2.5-flash-text\nlegacy gemini-2.5-flash]
  P2 --> PT[PyPDF page texts]
  PT --> G2[Gemini: format to markdown]
  G2 --> S2[Gemini summary]

  PDF --> P3[gemini-2.5-flash-pdf]
  P3 --> G3[Gemini multimodal\ninline application/pdf]
  G3 --> S3[Gemini summary]

  PDF --> P4[mistral]
  P4 --> PT2[PyPDF texts]
  PT2 --> M1[Mistral HTTP\ntext to markdown]
  M1 --> S4[Gemini summary]

  PDF --> P5[mistral-ocr]
  P5 --> RAST[PyMuPDF raster\nper page]
  RAST --> M2[Mistral vision\nper page]
  M2 --> S5[Gemini summary]
```

Oversized PDFs for the native Gemini PDF path return **413** (no silent fallback to text-only). See `README.md` and `docs/REQUIREMENTS.md` for parser IDs and env limits (`MISTRAL_OCR_MAX_PAGES`, etc.).

---

## 9. Caching and content addressing

```mermaid
flowchart LR
  H[sha256 of PDF bytes] --> K1["pdf:{parser}:{sha}"]
  H --> K2["pdf:summary:gemini:..."]
  K1 --> V1[markdown or text + metadata]
  K2 --> V2[summary + generated_at]
```

Async jobs additionally use a **short-lived blob key** so the worker can fetch bytes after upload without holding large payloads in the stream payload itself.

---

## 10. Observability

```mermaid
flowchart LR
  subgraph worker["Worker process"]
    L[Structured JSON logs\ncorrelation_id, job_id, msg_id]
    M[Prometheus /metrics\nhistograms, counters, pending gauge]
    T[Optional OTLP HTTP\nOpenTelemetry]
  end

  L --> OPS[Operators / CI logs]
  M --> PROM[Prometheus scrape]
  T --> COL[OTLP collector]
```

---

## 11. Frontend integration

```mermaid
sequenceDiagram
  participant U as User
  participant FE as Frontend
  participant API as Backend

  U->>FE: Select PDFs + parser
  FE->>API: POST /api/jobs/extract
  API-->>FE: job_id
  loop Poll until terminal
    FE->>API: GET /api/jobs/{job_id}
    API-->>FE: queued | processing | done | failed
  end
  FE-->>U: Render pages + summary
```

The Vite dev server proxies `/api` to the backend (`VITE_API_BASE_URL` in compose).

---

## 12. Scaling and failure modes

- **Scale workers:** `docker compose up --scale worker=N` (same consumer group). Idempotent `done` handling avoids duplicate side effects.
- **API vs worker LLM caps:** Both use the same slot model; tune `LLM_MAX_INFLIGHT` for combined cluster behavior.
- **Redis AOF:** Default compose command enables append-only file for durability of streams and keys (subject to Redis configuration).

---

## 13. Related documents

| Document | Topic |
|----------|--------|
| [`STREAMS_CONTRACT.md`](STREAMS_CONTRACT.md) | At-least-once delivery, `XACK`, retries, DLQ, reclaim |
| [`REQUIREMENTS.md`](REQUIREMENTS.md) | Formal FR/TR |
| [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) | What is implemented vs backlog |
| [`TESTS.md`](TESTS.md) | How integration tests assume a running stack |

---

**Async PDF Processor** — architecture overview for operators and contributors.

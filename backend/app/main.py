import asyncio
import functools
import hashlib
import io
import os
import base64
import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any, Callable, Literal, Optional, TypeVar

T = TypeVar("T")

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pypdf import PdfReader
from redis.asyncio import Redis

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None  # type: ignore[misc, assignment]

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
MISTRAL_API_BASE_URL = os.getenv("MISTRAL_API_BASE_URL", "https://api.mistral.ai")
MISTRAL_OCR_MODEL = os.getenv("MISTRAL_OCR_MODEL", "mistral-small-latest")
REDIS_STREAM_NAME = os.getenv("REDIS_STREAM_NAME", "doc_jobs")
REDIS_CONSUMER_GROUP = os.getenv("REDIS_CONSUMER_GROUP", "doc_workers")
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", str(60 * 60 * 24 * 7)))  # 7 days
BLOCKING_POOL_MAX_WORKERS = int(os.getenv("BLOCKING_POOL_MAX_WORKERS", "8"))


def _gemini_dedicated_pool_max_workers() -> int | None:
    """
    When set to a positive integer, blocking Gemini SDK calls use a dedicated pool
    so pathological PyMuPDF/PyPDF work cannot exhaust threads used for generate_content.
    When unset or non-positive, Gemini shares the PDF CPU pool (legacy behavior).
    """
    raw = os.getenv("GEMINI_POOL_MAX_WORKERS", "").strip()
    if not raw:
        return None
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return max(1, v)


def _env_int_min(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name, str(default))
    try:
        v = int(raw)
    except (TypeError, ValueError):
        v = default
    return max(minimum, v)


SYNC_EXTRACT_MAX_CONCURRENT = _env_int_min(
    "SYNC_EXTRACT_MAX_CONCURRENT",
    max(1, min(8, BLOCKING_POOL_MAX_WORKERS)),
    minimum=1,
)


def _llm_max_inflight() -> int:
    default_cap = max(1, min(8, BLOCKING_POOL_MAX_WORKERS))
    return _env_int_min("LLM_MAX_INFLIGHT", default_cap, minimum=1)


def _llm_slot_acquire_wait_timeout_s() -> float | None:
    """
    Max seconds to wait for an LLM concurrency slot.
    None = wait until a slot is free (queued). 0 = fail almost immediately when saturated.
    """
    raw = os.getenv("LLM_SLOT_ACQUIRE_TIMEOUT_SECONDS", "60").strip().lower()
    if raw in ("inf", "infinite", "-1"):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        v = 60.0
    if v < 0:
        return None
    if v == 0:
        return 0.001
    return v


_llm_semaphore: asyncio.Semaphore | None = None


def _init_llm_semaphore() -> asyncio.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(_llm_max_inflight())
    return _llm_semaphore


class LlmCapacityExceededError(Exception):
    """Raised when the global LLM concurrency limit is saturated (backpressure)."""

    def __init__(self, *, retry_after_s: int = 10) -> None:
        self.retry_after_s = max(1, int(retry_after_s))
        super().__init__("LLM capacity saturated; retry later.")


@asynccontextmanager
async def _llm_slot() -> AsyncIterator[None]:
    sem = _init_llm_semaphore()
    timeout = _llm_slot_acquire_wait_timeout_s()
    try:
        await asyncio.wait_for(sem.acquire(), timeout=timeout)
    except asyncio.TimeoutError as e:
        t = _llm_slot_acquire_wait_timeout_s()
        if t is None:
            retry_after = 60
        else:
            retry_after = int(max(1, min(120, round(t))))
        raise LlmCapacityExceededError(retry_after_s=retry_after) from e
    try:
        yield
    finally:
        sem.release()


def _env_float_positive(name: str, default: str) -> float:
    raw = os.getenv(name, default)
    try:
        v = float(raw)
    except (TypeError, ValueError):
        v = float(default)
    if v <= 0:
        v = float(default)
    return v


# Gemini: HTTP deadline via SDK RequestOptions(_gemini_generate_content). PDF/CPU: asyncio.wait_for only.
GEMINI_CALL_TIMEOUT_SECONDS = _env_float_positive("GEMINI_CALL_TIMEOUT_SECONDS", "180")
PDF_PARSE_TIMEOUT_SECONDS = _env_float_positive("PDF_PARSE_TIMEOUT_SECONDS", "120")
def _gemini_inline_pdf_max_bytes() -> int:
    default = 20 * 1024 * 1024
    raw = os.getenv("GEMINI_INLINE_PDF_MAX_BYTES", str(default)).strip()
    try:
        v = int(raw)
    except (TypeError, ValueError):
        v = default
    return max(1024 * 1024, v)
MISTRAL_HTTP_TIMEOUT_SECONDS = _env_float_positive("MISTRAL_HTTP_TIMEOUT_SECONDS", "120")

MISTRAL_HTTPX_TIMEOUT = httpx.Timeout(
    MISTRAL_HTTP_TIMEOUT_SECONDS,
    connect=min(30.0, MISTRAL_HTTP_TIMEOUT_SECONDS),
)

MISTRAL_OCR_MAX_PAGES = _env_int_min("MISTRAL_OCR_MAX_PAGES", 25, minimum=1)

_pdf_cpu_executor: ThreadPoolExecutor | None = None
_gemini_blocking_executor: ThreadPoolExecutor | None = None


def _get_pdf_cpu_executor() -> ThreadPoolExecutor:
    """
    Bounded thread pool for CPU-heavy PyPDF / PyMuPDF work.
    Shared by the FastAPI app and the worker process (separate processes each get their own pool).
    """
    global _pdf_cpu_executor
    if _pdf_cpu_executor is None:
        _pdf_cpu_executor = ThreadPoolExecutor(
            max_workers=max(1, BLOCKING_POOL_MAX_WORKERS),
            thread_name_prefix="pdf-cpu-",
        )
    return _pdf_cpu_executor


def _get_gemini_blocking_executor() -> ThreadPoolExecutor:
    """
    Thread pool for synchronous Gemini SDK calls. Uses a dedicated pool when
    GEMINI_POOL_MAX_WORKERS is set; otherwise shares the PDF CPU pool.
    """
    n = _gemini_dedicated_pool_max_workers()
    if n is None:
        return _get_pdf_cpu_executor()
    global _gemini_blocking_executor
    if _gemini_blocking_executor is None:
        _gemini_blocking_executor = ThreadPoolExecutor(
            max_workers=n,
            thread_name_prefix="gemini-blocking-",
        )
    return _gemini_blocking_executor


def _get_blocking_executor() -> ThreadPoolExecutor:
    """Backward-compatible alias for the PDF CPU thread pool."""
    return _get_pdf_cpu_executor()


def _init_blocking_executors() -> None:
    """Eagerly create executor(s) used for blocking PDF and Gemini work."""
    _get_pdf_cpu_executor()
    _get_gemini_blocking_executor()


def _shutdown_blocking_executor() -> None:
    global _pdf_cpu_executor, _gemini_blocking_executor
    if _pdf_cpu_executor is not None:
        _pdf_cpu_executor.shutdown(wait=True, cancel_futures=False)
        _pdf_cpu_executor = None
    if _gemini_blocking_executor is not None:
        _gemini_blocking_executor.shutdown(wait=True, cancel_futures=False)
        _gemini_blocking_executor = None


def _gemini_generate_content(model: Any, contents: Any) -> Any:
    """
    Invoke Gemini ``generate_content`` with an SDK-level HTTP deadline when supported.
    This lets stuck requests fail inside the worker thread instead of relying only on
    ``asyncio.wait_for``, which does not cancel the underlying thread.
    """
    try:
        from google.generativeai.types import RequestOptions
    except Exception:
        return model.generate_content(contents)
    return model.generate_content(
        contents,
        request_options=RequestOptions(timeout=GEMINI_CALL_TIMEOUT_SECONDS),
    )


async def _run_blocking(
    func: Callable[..., T],
    *args: Any,
    thread_pool: ThreadPoolExecutor | None = None,
    **kwargs: Any,
) -> T:
    loop = asyncio.get_running_loop()
    executor = thread_pool if thread_pool is not None else _get_pdf_cpu_executor()
    if kwargs:
        return await loop.run_in_executor(executor, functools.partial(func, *args, **kwargs))
    if not args:
        return await loop.run_in_executor(executor, func)
    return await loop.run_in_executor(executor, func, *args)


async def _run_blocking_timed(
    timeout_s: float,
    func: Callable[..., T],
    *args: Any,
    thread_pool: ThreadPoolExecutor | None = None,
    **kwargs: Any,
) -> T:
    """
    Run blocking callable in a bounded thread pool with an asyncio-level deadline.

    ``asyncio.wait_for`` alone does not stop the worker thread; combine with provider
    deadlines (e.g. Gemini ``RequestOptions`` in ``_gemini_generate_content``) so slots
    free promptly. For Gemini, pass ``thread_pool=_get_gemini_blocking_executor()`` to
    isolate SDK threads from PDF CPU work when ``GEMINI_POOL_MAX_WORKERS`` is set.
    """
    label = getattr(func, "__name__", "blocking_call")
    try:
        return await asyncio.wait_for(
            _run_blocking(func, *args, thread_pool=thread_pool, **kwargs),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError as e:
        raise HTTPException(
            status_code=504,
            detail=f"Timed out after {timeout_s:.0f}s ({label})",
        ) from e


app = FastAPI(title="Async PDF Processor")


@app.exception_handler(LlmCapacityExceededError)
async def _llm_capacity_handler(request: Request, exc: LlmCapacityExceededError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc)},
        headers={"Retry-After": str(exc.retry_after_s)},
    )


origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

redis: Optional[Redis] = None


@app.on_event("startup")
async def _startup() -> None:
    global redis
    _init_blocking_executors()
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await redis.ping()
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"Redis connection failed: {e}") from e


@app.on_event("shutdown")
async def _shutdown() -> None:
    global redis
    if redis is not None:
        await redis.aclose()
        redis = None
    _shutdown_blocking_executor()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _extract_text_from_pdf(pdf_bytes: bytes, max_chars: int = 20000) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
        if sum(len(p) for p in parts) >= max_chars:
            break
    text = "\n".join(parts).strip()
    return text[:max_chars]


def _pdf_page_count(pdf_bytes: bytes) -> int:
    """Return page count from PDF structure (PyPDF metadata only; no OCR)."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return max(1, len(reader.pages))


def _extract_page_texts_from_pdf(pdf_bytes: bytes, max_chars_total: int = 24000) -> list[str]:
    """
    Extract text per page. Enforces an overall character budget to keep prompts small.
    Returns a list of page strings in natural page order.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_texts: list[str] = []
    total = 0
    for page in reader.pages:
        t = (page.extract_text() or "").strip()
        if not t:
            page_texts.append("")
            continue
        if total >= max_chars_total:
            page_texts.append("")
            continue
        remaining = max_chars_total - total
        if len(t) > remaining:
            t = t[:remaining]
        page_texts.append(t)
        total += len(t)
    return page_texts


def _split_markdown_by_page_markers(markdown: str, expected_pages: int) -> list[str]:
    """
    Split markdown into page blocks using markers like: <!-- PAGE 1 -->.
    If markers are missing, fall back to page 1 containing the whole markdown.
    """
    if expected_pages <= 0:
        return [markdown.strip()]

    marker_re = re.compile(r"<!--\s*PAGE\s+(\d+)\s*-->", re.IGNORECASE)
    matches = list(marker_re.finditer(markdown))
    if not matches:
        pages = [""] * expected_pages
        pages[0] = markdown.strip()
        return pages

    # Build segments between markers.
    pages_map: dict[int, str] = {}
    for idx, m in enumerate(matches):
        page_no = int(m.group(1))
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        chunk = markdown[start:end].strip()
        if 1 <= page_no <= expected_pages:
            pages_map[page_no] = chunk

    pages: list[str] = []
    for i in range(1, expected_pages + 1):
        pages.append(pages_map.get(i, ""))
    return pages


def _extract_markdown_with_gemini(
    pdf_bytes: bytes,
    *,
    filename: str,
    page_texts: list[str],
) -> str:
    if genai is None:
        raise HTTPException(status_code=500, detail="google-generativeai not available")
    if not GOOGLE_API_KEY:
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY is not set")

    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)
    expected_pages = len(page_texts)
    # Build a deterministic per-page prompt so the model can output markers.
    pages_block = []
    for i, t in enumerate(page_texts, start=1):
        pages_block.append(f"<!-- SOURCE PAGE {i} -->\n{t or ''}")

    prompt = (
        "You will be given extracted text for each PDF page.\n"
        "Convert EACH source page text into clean markdown, preserving structure as much as possible.\n"
        "IMPORTANT OUTPUT RULES:\n"
        "1) Output ONLY page blocks.\n"
        "2) Before every page's markdown, include exactly one marker line: `<!-- PAGE i -->`.\n"
        "3) After that marker, output only the markdown for that page (no extra markers or explanations).\n"
        "4) Do not add facts not present in the source.\n\n"
        f"Filename: {filename}\n\n"
        f"Expected pages: {expected_pages}\n\n"
        "SOURCE:\n"
        f"{chr(10).join(pages_block)}"
    )
    try:
        resp = _gemini_generate_content(model, prompt)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini parser request failed: {e}") from e

    md = _safe_gemini_text(resp)
    if not md:
        raise HTTPException(status_code=502, detail="Gemini parser returned no text")
    return md


def _extract_markdown_with_gemini_native_pdf(
    pdf_bytes: bytes,
    *,
    filename: str,
    expected_pages: int,
) -> str:
    """
    Advanced parsing: send the PDF bytes to Gemini as inline multimodal input.

    This path must not substitute PyPDF page text as the model input (PR-FR-2).
    Page count is taken from PDF structure only to guide marker-based splitting.
    """
    if genai is None:
        raise HTTPException(status_code=500, detail="google-generativeai not available")
    if not GOOGLE_API_KEY:
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY is not set")
    max_inline = _gemini_inline_pdf_max_bytes()
    if len(pdf_bytes) > max_inline:
        raise HTTPException(
            status_code=413,
            detail=(
                "PDF too large for native Gemini inline PDF input "
                f"(max {max_inline} bytes). "
                "Use parser gemini-2.5-flash-text or raise GEMINI_INLINE_PDF_MAX_BYTES if appropriate."
            ),
        )

    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)
    prompt = (
        "You are given a PDF document as binary input (application/pdf).\n"
        "Extract content as clean markdown, page by page, using only what is visible in the PDF.\n"
        "IMPORTANT OUTPUT RULES:\n"
        "1) Output ONLY page blocks.\n"
        "2) Before every page's markdown, include exactly one marker line: `<!-- PAGE i -->` "
        "where i is the 1-based page index.\n"
        "3) After that marker, output only the markdown for that page (no extra markers or explanations).\n"
        "4) Do not invent facts that are not supported by the document.\n\n"
        f"Filename: {filename}\n\n"
        f"Expected pages: {expected_pages}\n"
    )
    contents: list[object] = [
        {"inline_data": {"mime_type": "application/pdf", "data": pdf_bytes}},
        prompt,
    ]
    try:
        resp = _gemini_generate_content(model, contents)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Gemini native PDF parser request failed: {e}",
        ) from e

    md = _safe_gemini_text(resp)
    if not md:
        raise HTTPException(status_code=502, detail="Gemini native PDF parser returned no text")
    return md


def _mistral_ocr_raster_zoom() -> float:
    return _env_float_positive("MISTRAL_OCR_RASTER_ZOOM", "1.75")


def _rasterize_pdf_pages_to_png_bytes(pdf_bytes: bytes) -> list[bytes]:
    """
    Rasterize each PDF page to a PNG (for Mistral vision / OCR-style parsing).
    """
    if fitz is None:
        raise HTTPException(
            status_code=500,
            detail="PyMuPDF (pymupdf) is not available; mistral-ocr cannot rasterize pages.",
        )
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        total = len(doc)
        if total > MISTRAL_OCR_MAX_PAGES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"PDF has {total} pages; mistral-ocr allows at most {MISTRAL_OCR_MAX_PAGES} "
                    "(raise MISTRAL_OCR_MAX_PAGES if you accept higher cost/latency)."
                ),
            )
        zoom = _mistral_ocr_raster_zoom()
        mat = fitz.Matrix(zoom, zoom)
        out: list[bytes] = []
        for i in range(total):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            out.append(pix.tobytes("png"))
        return out
    finally:
        doc.close()


def _mistral_extract_assistant_text(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise HTTPException(status_code=502, detail="Mistral parser returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
        merged = "\n".join(parts).strip()
        if merged:
            return merged
    raise HTTPException(status_code=502, detail="Mistral parser returned no text")


async def _mistral_chat_completions_post(payload: dict) -> dict:
    if not MISTRAL_API_KEY:
        raise HTTPException(status_code=500, detail="MISTRAL_API_KEY is not set")
    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{MISTRAL_API_BASE_URL.rstrip('/')}/v1/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=MISTRAL_HTTPX_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        body = e.response.text
        raise HTTPException(status_code=502, detail=f"Mistral parser request failed: {body}") from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Mistral parser request failed: {e}") from e


async def _extract_markdown_with_mistral(
    pdf_bytes: bytes,
    *,
    filename: str,
    page_texts: list[str],
) -> str:
    expected_pages = len(page_texts)
    pages_block = []
    for i, t in enumerate(page_texts, start=1):
        pages_block.append(f"<!-- SOURCE PAGE {i} -->\n{t or ''}")

    prompt = (
        "You will be given extracted text for each PDF page.\n"
        "Convert EACH source page text into clean markdown.\n"
        "IMPORTANT OUTPUT RULES:\n"
        "1) Output ONLY page blocks.\n"
        "2) Before every page's markdown, include exactly one marker line: `<!-- PAGE i -->`.\n"
        "3) After that marker, output only the markdown for that page (no extra markers or explanations).\n"
        "4) Do not add facts not present in the source.\n\n"
        f"Filename: {filename}\n\n"
        f"Expected pages: {expected_pages}\n\n"
        "SOURCE:\n"
        f"{chr(10).join(pages_block)}"
    )
    payload = {
        "model": MISTRAL_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
    }
    data = await _mistral_chat_completions_post(payload)
    return _mistral_extract_assistant_text(data)


async def _extract_markdown_with_mistral_ocr(page_pngs: list[bytes], *, filename: str) -> str:
    """
    Raster page images -> Mistral chat vision (one request per page) -> combined markdown with PAGE markers.
    """
    if not page_pngs:
        return ""
    total = len(page_pngs)
    blocks: list[str] = []
    for idx, png in enumerate(page_pngs, start=1):
        b64 = base64.b64encode(png).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"
        prompt = (
            "You are performing OCR and light layout recovery for a single PDF page image.\n"
            "Transcribe visible text and simple structure as clean markdown.\n"
            "IMPORTANT OUTPUT RULES:\n"
            f"1) First line must be exactly: `<!-- PAGE {idx} -->`.\n"
            "2) Then markdown only for this page (no other PAGE markers).\n"
            "3) If there is no readable text, output the marker and a single short line stating that the page has no readable text.\n\n"
            f"Filename: {filename} — page {idx} of {total}.\n"
        )
        payload = {
            "model": MISTRAL_OCR_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": data_url},
                    ],
                }
            ],
            "temperature": 0.0,
        }
        data = await _mistral_chat_completions_post(payload)
        blocks.append(_mistral_extract_assistant_text(data))
    return "\n\n".join(blocks)


def _safe_gemini_text(resp: object) -> str:
    """
    google-generativeai sometimes returns a response without text parts
    (e.g. finish_reason != stop). In that case `resp.text` may raise.
    """
    # 1) Try the "quick accessor" (may raise)
    try:
        text = getattr(resp, "text", "") or ""
        if text.strip():
            return text
    except Exception:
        pass

    # 2) Try extracting text from candidates->parts
    candidates = getattr(resp, "candidates", None) or []
    texts: list[str] = []
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            t = getattr(part, "text", None)
            if t:
                texts.append(str(t))

    return "\n".join(texts).strip()


def _summary_cache_key(*, parser: str, language: Optional[str], file_hash: str) -> str:
    lang = language or "en"
    return f"pdf:summary:gemini:{parser}:{lang}:{file_hash}"


def _summarize_with_gemini(
    *,
    extracted_text: str,
    filename: str,
    language: Optional[str],
) -> str:
    """
    Create one summary per uploaded file using Gemini 2.5 Flash.
    Output is returned as markdown/plain text (provider-dependent).
    """
    if genai is None:
        raise HTTPException(status_code=500, detail="google-generativeai not available")
    if not GOOGLE_API_KEY:
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY is not set")
    if not extracted_text.strip():
        return ""

    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)

    answer_lang = _answer_language_name(language)
    snippet = extracted_text[:12000]

    prompt = (
        "You are summarizing extracted content from a PDF.\n"
        f"Write in: {answer_lang}.\n\n"
        "Rules:\n"
        "- Use ONLY information from the provided text.\n"
        "- Do not invent facts.\n"
        "- Keep it concise (max ~200 words).\n"
        "- Output in markdown.\n\n"
        f"Filename: {filename}\n\n"
        "Extracted document text:\n"
        f"{snippet}"
    )

    try:
        resp = _gemini_generate_content(model, prompt)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini summarization request failed: {e}") from e

    summary = _safe_gemini_text(resp)
    if not summary:
        raise HTTPException(status_code=502, detail="Gemini summarization returned no text")
    return summary.strip()


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


ParserType = Literal[
    "pypdf",
    "gemini-2.5-flash",
    "gemini-2.5-flash-text",
    "gemini-2.5-flash-pdf",
    "mistral",
    "mistral-ocr",
]


def _job_key(job_id: str) -> str:
    return f"doc:job:{job_id}"


def _blob_b64_key(job_id: str) -> str:
    return f"doc:blob_b64:{job_id}"


async def _process_pdf_bytes(
    pdf_bytes: bytes,
    *,
    filename: str,
    parser: ParserType,
    language: Optional[str],
    redis_client: Redis,
) -> dict:
    file_hash = _sha256_bytes(pdf_bytes)
    cache_key = f"pdf:{parser}:{file_hash}"
    content_cached = False

    pages: list[dict] = []
    text: str = ""
    content_generated_at: Optional[int] = None

    cached = await redis_client.get(cache_key)
    if cached:
        try:
            cached_obj = json.loads(cached)
            pages = cached_obj.get("pages") or []
            text = cached_obj.get("text") or ""
            content_generated_at = cached_obj.get("generated_at")
        except Exception:
            # Backward compatibility for old cache values.
            pages = [{"page": 1, "content": str(cached)}]
            text = str(cached)
            content_generated_at = None

        content_cached = True
        if content_generated_at is None:
            # Backward compatible cache refresh: old Redis entries might not have timestamps.
            now_ts = int(time.time())
            content_generated_at = now_ts
            await redis_client.set(
                cache_key,
                json.dumps(
                    {
                        "status": "done",
                        "text": text,
                        "pages": pages,
                        "generated_at": content_generated_at,
                        "parser": parser,
                        "sha256": file_hash,
                    }
                ),
                ex=60 * 60 * 24,
            )
    if not content_cached:
        if parser == "pypdf":
            try:
                page_texts = await _run_blocking_timed(
                    PDF_PARSE_TIMEOUT_SECONDS,
                    _extract_page_texts_from_pdf,
                    pdf_bytes,
                )
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"PDF parse failed: {e}") from e
            pages = [{"page": i + 1, "content": t} for i, t in enumerate(page_texts)]
            text = "\n\n".join(t for t in page_texts if t).strip()
        elif parser in ("gemini-2.5-flash", "gemini-2.5-flash-text"):
            # Formatter: PyPDF page text -> Gemini markdown (legacy id: gemini-2.5-flash).
            source_page_texts = await _run_blocking_timed(
                PDF_PARSE_TIMEOUT_SECONDS,
                _extract_page_texts_from_pdf,
                pdf_bytes,
            )
            async with _llm_slot():
                md = await _run_blocking_timed(
                    GEMINI_CALL_TIMEOUT_SECONDS,
                    _extract_markdown_with_gemini,
                    pdf_bytes,
                    filename=filename or "unknown.pdf",
                    page_texts=source_page_texts,
                    thread_pool=_get_gemini_blocking_executor(),
                )
            page_strings = _split_markdown_by_page_markers(md, len(source_page_texts))
            pages = [{"page": i + 1, "content": c} for i, c in enumerate(page_strings)]
            text = "\n\n".join(c for c in page_strings if c).strip()
        elif parser == "gemini-2.5-flash-pdf":
            expected_pages = await _run_blocking_timed(
                PDF_PARSE_TIMEOUT_SECONDS,
                _pdf_page_count,
                pdf_bytes,
            )
            async with _llm_slot():
                md = await _run_blocking_timed(
                    GEMINI_CALL_TIMEOUT_SECONDS,
                    _extract_markdown_with_gemini_native_pdf,
                    pdf_bytes,
                    filename=filename or "unknown.pdf",
                    expected_pages=expected_pages,
                    thread_pool=_get_gemini_blocking_executor(),
                )
            page_strings = _split_markdown_by_page_markers(md, expected_pages)
            pages = [{"page": i + 1, "content": c} for i, c in enumerate(page_strings)]
            text = "\n\n".join(c for c in page_strings if c).strip()
        elif parser == "mistral":
            source_page_texts = await _run_blocking_timed(
                PDF_PARSE_TIMEOUT_SECONDS,
                _extract_page_texts_from_pdf,
                pdf_bytes,
            )
            async with _llm_slot():
                md = await _extract_markdown_with_mistral(
                    pdf_bytes,
                    filename=filename or "unknown.pdf",
                    page_texts=source_page_texts,
                )
            page_strings = _split_markdown_by_page_markers(md, len(source_page_texts))
            pages = [{"page": i + 1, "content": c} for i, c in enumerate(page_strings)]
            text = "\n\n".join(c for c in page_strings if c).strip()
        elif parser == "mistral-ocr":
            page_pngs = await _run_blocking_timed(
                PDF_PARSE_TIMEOUT_SECONDS,
                _rasterize_pdf_pages_to_png_bytes,
                pdf_bytes,
            )
            async with _llm_slot():
                md = await _extract_markdown_with_mistral_ocr(
                    page_pngs,
                    filename=filename or "unknown.pdf",
                )
            page_strings = _split_markdown_by_page_markers(md, len(page_pngs))
            pages = [{"page": i + 1, "content": c} for i, c in enumerate(page_strings)]
            text = "\n\n".join(c for c in page_strings if c).strip()
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported parser: {parser}")

        content_generated_at = int(time.time())
        cached_obj = {
            "status": "done",
            "text": text,
            "pages": pages,
            "generated_at": content_generated_at,
            "parser": parser,
            "sha256": file_hash,
        }
        await redis_client.set(cache_key, json.dumps(cached_obj), ex=60 * 60 * 24)

    summary_key = _summary_cache_key(parser=parser, language=language, file_hash=file_hash)
    cached_summary = await redis_client.get(summary_key)
    summary_cached = False
    summary_generated_at: Optional[int] = None
    summary = ""
    if cached_summary and str(cached_summary).strip():
        try:
            cached_summary_obj = json.loads(cached_summary)
            summary = str(cached_summary_obj.get("summary") or "").strip()
            summary_generated_at = cached_summary_obj.get("generated_at")
            summary_cached = bool(summary)
        except Exception:
            # Backward compatibility: old cache stored summary as a plain string.
            summary = str(cached_summary).strip()
            summary_cached = bool(summary)
            summary_generated_at = None

    if summary_cached and summary_generated_at is None:
        # Backward compatible cache refresh: old Redis entries might not have timestamps.
        now_ts = int(time.time())
        summary_generated_at = now_ts
        await redis_client.set(
            summary_key,
            json.dumps({"status": "done", "summary": summary, "generated_at": summary_generated_at}),
            ex=60 * 60 * 24,
        )

    if not summary:
        now = int(time.time())
        async with _llm_slot():
            summary = await _run_blocking_timed(
                GEMINI_CALL_TIMEOUT_SECONDS,
                _summarize_with_gemini,
                extracted_text=text,
                filename=filename or "unknown.pdf",
                language=language,
                thread_pool=_get_gemini_blocking_executor(),
            )
        summary_generated_at = now
        await redis_client.set(
            summary_key,
            json.dumps({"status": "done", "summary": summary, "generated_at": now}),
            ex=60 * 60 * 24,
        )

    return {
        "filename": filename or "unknown.pdf",
        "parser": parser,
        "sha256": file_hash,
        "cached": content_cached,
        "text": text,
        "pages": pages,
        "summary": summary,
        "summary_cached": summary_cached,
        "content_generated_at": content_generated_at,
        "summary_generated_at": summary_generated_at,
    }


async def _extract_single_pdf(file: UploadFile, parser: ParserType, language: Optional[str]) -> dict:
    if redis is None:
        raise HTTPException(status_code=503, detail="Redis not ready")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail=f"Empty file: {file.filename}")

    return await _process_pdf_bytes(
        content,
        filename=file.filename or "unknown.pdf",
        parser=parser,
        language=language,
        redis_client=redis,
    )


@app.post("/api/pdf/extract")
async def extract_pdf(
    files: list[UploadFile] = File(...),
    parser: ParserType = Form("pypdf"),
    language: Optional[str] = Form("en"),
) -> dict:
    if redis is None:
        raise HTTPException(status_code=503, detail="Redis not ready")
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    payloads: list[tuple[str, bytes]] = []
    for file in files:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail=f"Empty file: {file.filename}")
        payloads.append((file.filename or "unknown.pdf", content))

    conc_sem = asyncio.Semaphore(SYNC_EXTRACT_MAX_CONCURRENT)

    async def process_one(filename: str, content: bytes) -> dict:
        async with conc_sem:
            try:
                return await _process_pdf_bytes(
                    content,
                    filename=filename,
                    parser=parser,
                    language=language,
                    redis_client=redis,  # type: ignore[arg-type]
                )
            except HTTPException as e:
                return {"filename": filename, "parser": parser, "error": e.detail}
            except LlmCapacityExceededError as e:
                return {"filename": filename, "parser": parser, "error": str(e)}

    results = await asyncio.gather(*[process_one(fn, blob) for fn, blob in payloads])
    return {"results": list(results)}


@app.post("/api/jobs/extract")
async def create_extract_jobs(
    files: list[UploadFile] = File(...),
    parser: ParserType = Form("pypdf"),
    language: Optional[str] = Form("en"),
) -> dict:
    if redis is None:
        raise HTTPException(status_code=503, detail="Redis not ready")
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    jobs: list[dict] = []
    for file in files:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail=f"Empty file: {file.filename}")

        job_id = uuid.uuid4().hex
        filename = file.filename or "unknown.pdf"
        blob_key = _blob_b64_key(job_id)
        job_key = _job_key(job_id)
        correlation_id = uuid.uuid4().hex

        pdf_b64 = base64.b64encode(content).decode("ascii")

        job_data = {
            "job_id": job_id,
            "status": "queued",
            "filename": filename,
            "parser": parser,
            "language": language,
            "correlation_id": correlation_id,
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
            "result": None,
            "error": None,
        }

        await redis.set(blob_key, pdf_b64, ex=JOB_TTL_SECONDS)
        await redis.set(job_key, json.dumps(job_data), ex=JOB_TTL_SECONDS)

        await redis.xadd(
            REDIS_STREAM_NAME,
            {
                "job_id": job_id,
                "parser": parser,
                "filename": filename,
                "language": language or "en",
                "attempt": "0",
                "correlation_id": correlation_id,
            },
        )

        jobs.append({"job_id": job_id, "filename": filename, "parser": parser})

    return {"jobs": jobs}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    if redis is None:
        raise HTTPException(status_code=503, detail="Redis not ready")
    raw = await redis.get(_job_key(job_id))
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")
    return json.loads(raw)


class GeminiAnswerRequest(BaseModel):
    prompt: str
    context: Optional[str] = None
    # en, pl, es, pt, fr, ru
    language: Optional[str] = "en"


_LANGUAGE_TO_NAME = {
    "en": "English",
    "pl": "Polish",
    "es": "Spanish",
    "pt": "Portuguese",
    "fr": "French",
    "ru": "Russian",
}


def _answer_language_name(language: Optional[str]) -> str:
    # Default to English for safety when unknown/empty.
    if not language:
        return "English"
    return _LANGUAGE_TO_NAME.get(language, "English")


def _gemini_answer_sync(payload: GeminiAnswerRequest) -> dict:
    if genai is None:
        raise HTTPException(status_code=500, detail="google-generativeai not available")
    if not GOOGLE_API_KEY:
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY is not set")

    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)

    answer_lang = _answer_language_name(payload.language)

    if payload.context:
        full_prompt = (
            "Context (from PDF):\n"
            f"{payload.context}\n\n"
            f"User question:\n{payload.prompt}\n\n"
            f"Answer in {answer_lang}."
        )
    else:
        full_prompt = f"User question:\n{payload.prompt}\n\nAnswer in {answer_lang}."

    try:
        resp = _gemini_generate_content(model, full_prompt)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini request failed: {e}") from e

    text = _safe_gemini_text(resp)
    if not text:
        candidates = getattr(resp, "candidates", None) or []
        finish_reason = None
        if candidates:
            finish_reason = getattr(candidates[0], "finish_reason", None)
        raise HTTPException(
            status_code=502,
            detail=f"Gemini returned no text (finish_reason={finish_reason})",
        )

    return {"model": GEMINI_MODEL, "text": text}


@app.post("/api/gemini/answer")
async def gemini_answer(payload: GeminiAnswerRequest) -> dict:
    async with _llm_slot():
        return await _run_blocking_timed(
            GEMINI_CALL_TIMEOUT_SECONDS,
            _gemini_answer_sync,
            payload,
            thread_pool=_get_gemini_blocking_executor(),
        )


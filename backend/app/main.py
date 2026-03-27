import hashlib
import io
import os
import base64
import json
import re
import time
import uuid
from typing import Literal, Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pypdf import PdfReader
from redis.asyncio import Redis

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
REDIS_STREAM_NAME = os.getenv("REDIS_STREAM_NAME", "doc_jobs")
REDIS_CONSUMER_GROUP = os.getenv("REDIS_CONSUMER_GROUP", "doc_workers")
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", str(60 * 60 * 24 * 7)))  # 7 days


app = FastAPI(title="Async PDF Processor")

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
        resp = model.generate_content(prompt)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini parser request failed: {e}") from e

    md = _safe_gemini_text(resp)
    if not md:
        raise HTTPException(status_code=502, detail="Gemini parser returned no text")
    return md


async def _extract_markdown_with_mistral(
    pdf_bytes: bytes,
    *,
    filename: str,
    page_texts: list[str],
) -> str:
    if not MISTRAL_API_KEY:
        raise HTTPException(status_code=500, detail="MISTRAL_API_KEY is not set")
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
    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{MISTRAL_API_BASE_URL.rstrip('/')}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        body = e.response.text
        raise HTTPException(status_code=502, detail=f"Mistral parser request failed: {body}") from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Mistral parser request failed: {e}") from e

    choices = data.get("choices") or []
    if not choices:
        raise HTTPException(status_code=502, detail="Mistral parser returned no choices")

    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        # Some providers may return structured content blocks.
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
        resp = model.generate_content(prompt)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini summarization request failed: {e}") from e

    summary = _safe_gemini_text(resp)
    if not summary:
        raise HTTPException(status_code=502, detail="Gemini summarization returned no text")
    return summary.strip()


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


ParserType = Literal["pypdf", "gemini-2.5-flash", "mistral"]


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
                page_texts = _extract_page_texts_from_pdf(pdf_bytes)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"PDF parse failed: {e}") from e
            pages = [{"page": i + 1, "content": t} for i, t in enumerate(page_texts)]
            text = "\n\n".join(t for t in page_texts if t).strip()
        elif parser == "gemini-2.5-flash":
            # page-level markdown conversion via marker-based splitting
            source_page_texts = _extract_page_texts_from_pdf(pdf_bytes)
            md = _extract_markdown_with_gemini(
                pdf_bytes,
                filename=filename or "unknown.pdf",
                page_texts=source_page_texts,
            )
            # best-effort: split using markers; if markers are missing, keep as page 1
            page_strings = _split_markdown_by_page_markers(md, len(source_page_texts))
            pages = [{"page": i + 1, "content": c} for i, c in enumerate(page_strings)]
            text = "\n\n".join(c for c in page_strings if c).strip()
        else:
            source_page_texts = _extract_page_texts_from_pdf(pdf_bytes)
            md = await _extract_markdown_with_mistral(
                pdf_bytes,
                filename=filename or "unknown.pdf",
                page_texts=source_page_texts,
            )
            page_strings = _split_markdown_by_page_markers(md, len(source_page_texts))
            pages = [{"page": i + 1, "content": c} for i, c in enumerate(page_strings)]
            text = "\n\n".join(c for c in page_strings if c).strip()

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
        summary = _summarize_with_gemini(
            extracted_text=text,
            filename=filename or "unknown.pdf",
            language=language,
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

    results: list[dict] = []
    for file in files:
        try:
            content = await file.read()
            if not content:
                raise HTTPException(status_code=400, detail=f"Empty file: {file.filename}")
            result = await _process_pdf_bytes(
                content,
                filename=file.filename or "unknown.pdf",
                parser=parser,
                language=language,
                redis_client=redis,  # type: ignore[arg-type]
            )
            results.append(result)
        except HTTPException as e:
            results.append(
                {
                    "filename": file.filename or "unknown.pdf",
                    "parser": parser,
                    "error": e.detail,
                }
            )

    return {"results": results}


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

        pdf_b64 = base64.b64encode(content).decode("ascii")

        job_data = {
            "job_id": job_id,
            "status": "queued",
            "filename": filename,
            "parser": parser,
            "language": language,
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
            "result": None,
            "error": None,
        }

        await redis.set(blob_key, pdf_b64, ex=JOB_TTL_SECONDS)
        await redis.set(job_key, json.dumps(job_data), ex=JOB_TTL_SECONDS)

        await redis.xadd(
            REDIS_STREAM_NAME,
            {"job_id": job_id, "parser": parser, "filename": filename, "language": language or "en"},
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


@app.post("/api/gemini/answer")
async def gemini_answer(payload: GeminiAnswerRequest) -> dict:
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
        resp = model.generate_content(full_prompt)
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


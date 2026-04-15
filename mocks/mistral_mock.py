import re

from fastapi import FastAPI, Request


app = FastAPI(title="mistral-mock")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def _first_user_message_content(payload: dict) -> object:
    for msg in payload.get("messages") or []:
        if isinstance(msg, dict) and msg.get("role") == "user":
            return msg.get("content")
    return ""


def _count_image_parts(content: object) -> int:
    if not isinstance(content, list):
        return 0
    n = 0
    for part in content:
        if isinstance(part, dict) and part.get("type") == "image_url":
            n += 1
    return n


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> dict:
    payload = await request.json()
    model = payload.get("model") or "mistral-small-latest"
    user_content = _first_user_message_content(payload)

    # Vision / OCR-style request: one image per call in mistral-ocr pipeline.
    if _count_image_parts(user_content) >= 1:
        text_part = ""
        if isinstance(user_content, list):
            for part in user_content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_part = str(part.get("text") or "")
                    break
        m = re.search(r"page\s+(\d+)\s+of\s+(\d+)", text_part, flags=re.I)
        page_idx = int(m.group(1)) if m else 1
        page_total = int(m.group(2)) if m and m.lastindex and m.lastindex >= 2 else 1
        snippet = text_part[:200].strip().replace("\n", " ") if text_part else "(no text prompt)"
        body = (
            f"<!-- PAGE {page_idx} -->\n"
            f"# Mock Mistral OCR (page {page_idx}/{page_total})\n\n"
            "Rasterized page image received; this is **mock** markdown (replace with real Mistral API).\n\n"
            f"Prompt snippet: {snippet}"
        )
        return {
            "id": "mock-chatcmpl-ocr",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": body},
                    "finish_reason": "stop",
                }
            ],
        }

    # Text-only formatter path (parser mistral).
    user_text = user_content if isinstance(user_content, str) else ""

    page_numbers = [int(m.group(1)) for m in re.finditer(r"<!--\s*SOURCE PAGE\s+(\d+)\s*-->", user_text, flags=re.I)]
    expected_pages = max(page_numbers) if page_numbers else 1

    page_blocks: list[str] = []
    for i in range(1, expected_pages + 1):
        page_blocks.append(f"<!-- PAGE {i} -->")
        if i == 1:
            snippet = user_text[:300].strip().replace("\n", " ")
            page_blocks.append(
                f"# Mock Mistral Markdown Output (page {i})\n\n"
                "Converted from extracted text.\n\n"
                f"Snippet: {snippet}"
            )
        else:
            page_blocks.append(f"## Mock content for page {i}\n\nConverted from extracted text.")

    content = "\n\n".join(page_blocks).strip()

    return {
        "id": "mock-chatcmpl-1",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
    }

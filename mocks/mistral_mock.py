import re

from fastapi import FastAPI
from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float | None = None


app = FastAPI(title="mistral-mock")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(payload: ChatRequest) -> dict:
    user_text = ""
    for msg in payload.messages:
        if msg.role == "user":
            user_text = msg.content
            break

    # Determine how many SOURCE pages are present in the prompt.
    page_numbers = [int(m.group(1)) for m in re.finditer(r"<!--\s*SOURCE PAGE\s+(\d+)\s*-->", user_text, flags=re.I)]
    expected_pages = max(page_numbers) if page_numbers else 1

    # Build marker-based per-page output so backend can split by `<!-- PAGE i -->`.
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
        "model": payload.model,
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

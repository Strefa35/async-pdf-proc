"""In-process ASGI checks for LLM concurrency (no live backend on BACKEND_URL)."""

from __future__ import annotations

import asyncio
import importlib
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"


def _redis_tcp_reachable(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


@pytest.fixture
def asgi_app_llm_pressure(monkeypatch: pytest.MonkeyPatch):
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    if not _redis_tcp_reachable(redis_url):
        pytest.skip(f"Redis not reachable at {redis_url} (required for app startup)")

    monkeypatch.setenv("LLM_MAX_INFLIGHT", "1")
    monkeypatch.setenv("LLM_SLOT_ACQUIRE_TIMEOUT_SECONDS", "0")
    monkeypatch.setenv("GOOGLE_API_KEY", "unit-test-placeholder")
    monkeypatch.setenv("REDIS_URL", redis_url)

    root = str(BACKEND_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)

    import app.main as main

    importlib.reload(main)

    async def fake_run_blocking_timed(
        timeout_s: float,
        func: object,
        *args: object,
        **kwargs: object,
    ) -> dict:
        await asyncio.sleep(1.0)
        fn = getattr(func, "__name__", "")
        if fn == "_gemini_answer_sync":
            return {"model": "stub", "text": "ok"}
        raise AssertionError(f"unexpected blocking target: {fn!r}")

    monkeypatch.setattr(main, "_run_blocking_timed", fake_run_blocking_timed, raising=True)
    yield main.app


def test_parallel_gemini_answer_hits_llm_capacity(asgi_app_llm_pressure: object) -> None:
    async def run() -> None:
        transport = httpx.ASGITransport(app=asgi_app_llm_pressure)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            results = await asyncio.gather(
                client.post("/api/gemini/answer", json={"prompt": "one"}),
                client.post("/api/gemini/answer", json={"prompt": "two"}),
            )
        codes = {r.status_code for r in results}
        assert 200 in codes, [r.text for r in results]
        assert 503 in codes, [r.text for r in results]
        for r in results:
            if r.status_code == 503:
                assert r.headers.get("retry-after") is not None

    asyncio.run(run())

"""JSON assertions for sync extract and async job payloads."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def sync_results_len(data: dict[str, Any], expected: int) -> bool:
    results = data.get("results")
    return isinstance(results, list) and len(results) == expected


def sync_parser_all(data: dict[str, Any], expected_parser: str) -> bool:
    results = data.get("results")
    if not isinstance(results, list) or len(results) == 0:
        return False
    for r in results:
        if not isinstance(r, dict):
            return False
        if r.get("error"):
            continue
        if r.get("parser") != expected_parser:
            return False
    return True


def sync_first_pages_ok(data: dict[str, Any]) -> bool:
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return False
    r = results[0]
    if not isinstance(r, dict) or r.get("error"):
        return False
    pages = r.get("pages")
    if not isinstance(pages, list) or len(pages) < 1:
        return False
    p0 = pages[0]
    return isinstance(p0, dict) and "page" in p0 and "content" in p0


def sync_first_summary_nonempty(data: dict[str, Any]) -> bool:
    for r in data.get("results") or []:
        if isinstance(r, dict) and not r.get("error"):
            s = r.get("summary")
            return isinstance(s, str) and bool(s.strip())
    return False


def sync_first_timestamps_ok(data: dict[str, Any]) -> bool:
    for r in data.get("results") or []:
        if not isinstance(r, dict) or r.get("error"):
            continue
        return "content_generated_at" in r and "summary_generated_at" in r
    return False


def sync_first_sha_parser(data: dict[str, Any]) -> tuple[str, str]:
    results = data.get("results") or []
    if not results or not isinstance(results[0], dict):
        return "", ""
    r = results[0]
    sha = r.get("sha256") or ""
    parser = r.get("parser") or ""
    return (str(sha), str(parser))


def job_done_payload(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("result") or {}


def job_result_ok(data: dict[str, Any]) -> bool:
    res = job_done_payload(data)
    if not isinstance(res, dict):
        return False
    text = res.get("text")
    summary = res.get("summary")
    if not (isinstance(text, str) and text.strip()):
        return False
    if not (isinstance(summary, str) and summary.strip()):
        return False
    return "content_generated_at" in res and "summary_generated_at" in res


def job_result_pages_ok(data: dict[str, Any]) -> bool:
    res = job_done_payload(data)
    pages = res.get("pages")
    if not isinstance(pages, list) or len(pages) < 1:
        return False
    p0 = pages[0]
    return isinstance(p0, dict) and "page" in p0 and "content" in p0


def job_result_sha_parser_ok(data: dict[str, Any]) -> bool:
    res = job_done_payload(data)
    sha = res.get("sha256")
    parser = res.get("parser")
    return isinstance(sha, str) and bool(sha.strip()) and isinstance(parser, str) and bool(parser.strip())


def any_result_cached_true(data: dict[str, Any]) -> bool:
    for r in data.get("results") or []:
        if isinstance(r, dict) and r.get("cached") is True:
            return True
    return False


def mistral_missing_key_response(text: str) -> bool:
    return "MISTRAL_API_KEY is not set" in text


def read_pdf_bytes(path: Path) -> bytes:
    return path.read_bytes()

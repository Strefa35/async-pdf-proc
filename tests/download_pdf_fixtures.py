#!/usr/bin/env python3
"""
Download a small set of PDF fixtures into tests/fixtures/pdf (replaces download_pdf_fixtures.sh).

Usage:
  python3 tests/download_pdf_fixtures.py
  python3 tests/download_pdf_fixtures.py --force
  python3 tests/download_pdf_fixtures.py --strict
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIR = PROJECT_ROOT / "tests" / "fixtures" / "pdf"

# filename -> url (keep list small for fast CI)
PDF_SOURCES: list[tuple[str, str]] = [
    ("drylab.pdf", "https://princexml.com/samples/newsletter/drylab.pdf"),
    ("example.pdf", "https://princexml.com/samples/usenix/example.pdf"),
    ("flyer.pdf", "https://princexml.com/samples/flyer/flyer.pdf"),
    ("somatosensory.pdf", "https://princexml.com/samples/textbook/somatosensory.pdf"),
]


def download_one(filename: str, url: str, *, force: bool) -> bool:
    dest = TARGET_DIR / filename
    tmp = dest.with_suffix(dest.suffix + ".part")
    if dest.is_file() and not force:
        print(f"SKIP  {filename} (already exists)")
        return True

    print(f"GET   {filename}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "async-pdf-proc-fixtures/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
    except (urllib.error.URLError, OSError) as e:
        print(f"FAIL  {filename} ({e})", file=sys.stderr)
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return False

    if not data:
        print(f"FAIL  {filename} (empty response)", file=sys.stderr)
        return False

    tmp.write_bytes(data)
    tmp.replace(dest)
    print(f"OK    {filename}")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true", help="Re-download even if file exists")
    p.add_argument("--strict", action="store_true", help="Exit non-zero if any download fails")
    args = p.parse_args()

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    ok = fail = 0
    for filename, url in PDF_SOURCES:
        if download_one(filename, url, force=args.force):
            ok += 1
        else:
            fail += 1

    print()
    print(f"Done. Success: {ok}, Failed: {fail}")
    print(f"Fixtures dir: {TARGET_DIR}")
    if args.strict and fail > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

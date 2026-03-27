#!/usr/bin/env bash
# Shared helpers for FR-1..FR-7 tests (sourced by tests/test_fr*.sh).

FR_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FR_PDF_FIXTURES_DIR="$FR_PROJECT_ROOT/tests/fixtures/pdf"
FR_BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:5173}"

# Populated by fr_init_pdf_fixtures: all PDFs under tests/fixtures/pdf (sorted), or a single path when PDF_FILE is set.
FR_PDF_FILES=()
FR_PDF_FILE=""

# If PDF_FILE is set, use that file only. Otherwise collect every *.pdf under FR_PDF_FIXTURES_DIR (case-insensitive).
fr_init_pdf_fixtures() {
  FR_PDF_FILES=()
  if [[ -n "${PDF_FILE:-}" ]]; then
    if [[ ! -f "$PDF_FILE" ]]; then
      echo "Missing PDF: $PDF_FILE" >&2
      exit 1
    fi
    FR_PDF_FILES=("$PDF_FILE")
    FR_PDF_FILE="$PDF_FILE"
    return 0
  fi

  if [[ ! -d "$FR_PDF_FIXTURES_DIR" ]]; then
    echo "Brak plików PDF.  Umieść tam pliki pdf" >&2
    exit 1
  fi

  local f
  while IFS= read -r -d '' f; do
    FR_PDF_FILES+=("$f")
  done < <(find "$FR_PDF_FIXTURES_DIR" -maxdepth 1 -type f -iname '*.pdf' -print0 2>/dev/null | sort -z)

  if [[ ${#FR_PDF_FILES[@]} -eq 0 ]]; then
    echo "Brak plików PDF.  Umieść tam pliki pdf" >&2
    exit 1
  fi
  FR_PDF_FILE="${FR_PDF_FILES[0]}"
}

fr_require_pdf() {
  if [[ ! -f "$FR_PDF_FILE" ]]; then
    echo "Missing PDF: $FR_PDF_FILE" >&2
    exit 1
  fi
}

fr_init_pdf_fixtures

# Args: json_body expected_len
fr_json_extract_results_len() {
  echo "$1" | python3 -c 'import json,sys; data=json.loads(sys.stdin.read()); expected=int(sys.argv[1]); results=data.get("results", []); print("ok" if isinstance(results, list) and len(results)==expected else "bad")' "$2"
}

# Args: json_body expected_parser
fr_json_parser_all() {
  echo "$1" | python3 -c 'import json,sys; data=json.loads(sys.stdin.read()); expected=sys.argv[1]; results=data.get("results", []); ok=isinstance(results, list) and len(results)>0 and all((r.get("parser")==expected) for r in results if isinstance(r, dict)); print("ok" if ok else "bad")' "$2"
}

fr_json_pages_nonempty_first() {
  echo "$1" | python3 -c 'import json,sys; data=json.loads(sys.stdin.read()); results=data.get("results", []);
if not results or not isinstance(results[0], dict): print("bad"); raise SystemExit
r=results[0]
if r.get("error"): print("bad"); raise SystemExit
pages=r.get("pages")
if not isinstance(pages, list) or len(pages)<1: print("bad"); raise SystemExit
p0=pages[0]
ok=isinstance(p0, dict) and "page" in p0 and "content" in p0
print("ok" if ok else "bad")'
}

fr_json_summary_nonempty_first() {
  echo "$1" | python3 -c 'import json,sys; data=json.loads(sys.stdin.read()); results=data.get("results", [])
for r in results:
  if isinstance(r, dict) and not r.get("error"):
    s=r.get("summary")
    print("ok" if isinstance(s, str) and s.strip() else "bad")
    raise SystemExit
print("bad")'
}

fr_json_timestamp_fields_first() {
  echo "$1" | python3 -c 'import json,sys; data=json.loads(sys.stdin.read()); results=data.get("results", [])
for r in results:
  if not isinstance(r, dict) or r.get("error"):
    continue
  if "content_generated_at" not in r or "summary_generated_at" not in r:
    print("bad")
    raise SystemExit
  print("ok")
  raise SystemExit
print("bad")'
}

fr_poll_job_done() {
  local job_id="$1"
  local max_attempts="${2:-45}"
  local interval_s="${3:-1}"
  local attempt
  for ((attempt = 1; attempt <= max_attempts; attempt++)); do
    local job_json
    job_json="$(curl -sS "$FR_BACKEND_URL/api/jobs/$job_id" || true)"
    local status
    status="$(echo "$job_json" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("status",""))')"
    if [[ "$status" == "done" ]]; then
      echo "$job_json"
      return 0
    fi
    if [[ "$status" == "failed" ]]; then
      echo "$job_json"
      return 1
    fi
    sleep "$interval_s"
  done
  return 2
}

fr_job_result_ok() {
  echo "$1" | python3 -c 'import json,sys; data=json.loads(sys.stdin.read()); res=data.get("result") or {}
if not isinstance(res, dict): print("bad"); raise SystemExit
text=res.get("text"); summary=res.get("summary")
if not (isinstance(text, str) and text.strip()): print("bad"); raise SystemExit
if not (isinstance(summary, str) and summary.strip()): print("bad"); raise SystemExit
if "content_generated_at" not in res or "summary_generated_at" not in res: print("bad"); raise SystemExit
print("ok")'
}

# Args: full GET /api/jobs/{id} JSON when status is done (FR-4 async)
fr_job_result_pages_ok() {
  echo "$1" | python3 -c 'import json,sys; data=json.loads(sys.stdin.read()); res=data.get("result") or {}
if not isinstance(res, dict): print("bad"); raise SystemExit
pages=res.get("pages")
if not isinstance(pages, list) or len(pages)<1: print("bad"); raise SystemExit
p0=pages[0]
ok=isinstance(p0, dict) and "page" in p0 and "content" in p0
print("ok" if ok else "bad")'
}

# Args: full GET /api/jobs/{id} JSON when status is done (FR-6 async: sha256 + parser on result)
fr_job_result_sha_parser_ok() {
  echo "$1" | python3 -c 'import json,sys; data=json.loads(sys.stdin.read()); res=data.get("result") or {}
if not isinstance(res, dict): print("bad"); raise SystemExit
sha=res.get("sha256"); parser=res.get("parser")
print("ok" if (isinstance(sha, str) and sha.strip() and isinstance(parser, str) and parser.strip()) else "bad")'
}

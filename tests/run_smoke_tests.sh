#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:5173}"
# shellcheck source=lib/fr_common.sh
source "$SCRIPT_DIR/lib/fr_common.sh"

pass_count=0
fail_count=0

log() { printf "\n[%s] %s\n" "$1" "$2"; }
pass() { log "PASS" "$1"; pass_count=$((pass_count + 1)); }
fail() { log "FAIL" "$1"; fail_count=$((fail_count + 1)); }

check_contains_status_ok() {
  python3 - "$1" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
print("ok" if data.get("status") == "ok" else "bad")
PY
}

check_extract_results_len() {
  python3 - "$1" "$2" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
expected = int(sys.argv[2])
results = data.get("results", [])
print("ok" if isinstance(results, list) and len(results) == expected else "bad")
PY
}

check_extract_any_cached_true() {
  python3 - "$1" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
results = data.get("results", [])
print("ok" if any(r.get("cached") is True for r in results if isinstance(r, dict)) else "bad")
PY
}

check_extract_summary_nonempty() {
  python3 - "$1" <<'PY'
import json, sys
data=json.loads(sys.argv[1])
results=data.get("results",[])
ok=False
for r in results:
  if isinstance(r,dict) and not r.get("error"):
    s=r.get("summary")
    ok=isinstance(s,str) and bool(s.strip())
    break
print("ok" if ok else "bad")
PY
}

check_extract_timestamp_fields_present() {
  python3 - "$1" <<'PY'
import json, sys
data=json.loads(sys.argv[1])
results=data.get("results",[])
ok=True
for r in results:
  if not isinstance(r,dict) or r.get("error"):
    continue
  if "content_generated_at" not in r or "summary_generated_at" not in r:
    ok=False
    break
print("ok" if ok else "bad")
PY
}

check_extract_parser_value() {
  python3 - "$1" "$2" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
expected = sys.argv[2]
results = data.get("results", [])
ok = isinstance(results, list) and len(results) > 0 and all((r.get("parser") == expected) for r in results if isinstance(r, dict))
print("ok" if ok else "bad")
PY
}

check_gemini_payload() {
  python3 - "$1" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
ok = isinstance(data.get("model"), str) and isinstance(data.get("text"), str) and len(data["text"].strip()) > 0
print("ok" if ok else "bad")
PY
}

check_job_status() {
  python3 - "$1" "$2" <<'PY'
import json, sys
data=json.loads(sys.argv[1])
expected=sys.argv[2]
print("ok" if data.get("status")==expected else "bad")
PY
}

check_job_result_text_nonempty() {
  python3 - "$1" <<'PY'
import json, sys
data=json.loads(sys.argv[1])
res=data.get("result") or {}
text=res.get("text") if isinstance(res, dict) else None
print("ok" if isinstance(text,str) and text.strip() else "bad")
PY
}

check_job_result_summary_nonempty() {
  python3 - "$1" <<'PY'
import json, sys
data=json.loads(sys.argv[1])
res=data.get("result") or {}
summary=res.get("summary") if isinstance(res, dict) else None
print("ok" if isinstance(summary,str) and summary.strip() else "bad")
PY
}

check_job_result_timestamp_fields_present() {
  python3 - "$1" <<'PY'
import json, sys
data=json.loads(sys.argv[1])
res=data.get("result") or {}
ok=isinstance(res,dict) and "content_generated_at" in res and "summary_generated_at" in res
print("ok" if ok else "bad")
PY
}

log "INFO" "Running smoke tests"
echo "PROJECT_ROOT=$PROJECT_ROOT"
echo "BACKEND_URL=$BACKEND_URL"
echo "FRONTEND_URL=$FRONTEND_URL"
if [[ -n "${PDF_FILE:-}" ]]; then
  echo "PDF_FILE=$PDF_FILE (single file)"
else
  echo "PDF fixtures (${#FR_PDF_FILES[@]} file(s)):"
  for _p in "${FR_PDF_FILES[@]}"; do
    echo "  $_p"
  done
fi

# 1) Backend health
health_json="$(curl -sS "$BACKEND_URL/api/health" || true)"
if [[ "$(check_contains_status_ok "$health_json")" == "ok" ]]; then
  pass "Backend health endpoint"
else
  fail "Backend health endpoint"
fi

# 2) Frontend availability
frontend_status="$(curl -sS -o /dev/null -w "%{http_code}" "$FRONTEND_URL/" || true)"
if [[ "$frontend_status" == "200" ]]; then
  pass "Frontend availability"
else
  fail "Frontend availability (HTTP $frontend_status)"
fi

for PDF_FILE in "${FR_PDF_FILES[@]}"; do
  if [[ ${#FR_PDF_FILES[@]} -gt 1 ]]; then
    log "INFO" "---- PDF: $(basename "$PDF_FILE") ----"
  fi

  # 3) Single-file extract
  single_extract="$(curl -sS -X POST "$BACKEND_URL/api/pdf/extract" -F "files=@$PDF_FILE" || true)"
  if [[ "$(check_extract_results_len "$single_extract" 1)" == "ok" ]]; then
    if [[ "$(check_extract_summary_nonempty "$single_extract")" == "ok" ]]; then
      if [[ "$(check_extract_timestamp_fields_present "$single_extract")" == "ok" ]]; then
        pass "Single-file extraction (summary + timestamps present)"
      else
        fail "Single-file extraction (timestamps missing fields)"
      fi
    else
      fail "Single-file extraction (summary missing/empty)"
    fi
  else
    fail "Single-file extraction"
  fi

  # 4) Multi-file extract (same file twice)
  multi_extract="$(curl -sS -X POST "$BACKEND_URL/api/pdf/extract" -F "files=@$PDF_FILE" -F "files=@$PDF_FILE" || true)"
  if [[ "$(check_extract_results_len "$multi_extract" 2)" == "ok" ]]; then
    pass "Multi-file extraction (FR-1)"
  else
    fail "Multi-file extraction (FR-1)"
  fi

  # 4b) Parser selection - pypdf
  pypdf_extract="$(curl -sS -X POST "$BACKEND_URL/api/pdf/extract" -F "parser=pypdf" -F "files=@$PDF_FILE" || true)"
  if [[ "$(check_extract_parser_value "$pypdf_extract" "pypdf")" == "ok" ]]; then
    if [[ "$(check_extract_summary_nonempty "$pypdf_extract")" == "ok" ]]; then
      if [[ "$(check_extract_timestamp_fields_present "$pypdf_extract")" == "ok" ]]; then
        pass "Parser selection: pypdf (summary + timestamps present)"
      else
        fail "Parser selection: pypdf (timestamps missing fields)"
      fi
    else
      fail "Parser selection: pypdf (summary missing/empty)"
    fi
  else
    fail "Parser selection: pypdf"
  fi

  # 4c) Parser selection - gemini-2.5-flash
  gemini_parser_extract="$(curl -sS -X POST "$BACKEND_URL/api/pdf/extract" -F "parser=gemini-2.5-flash" -F "files=@$PDF_FILE" || true)"
  if [[ "$(check_extract_parser_value "$gemini_parser_extract" "gemini-2.5-flash")" == "ok" ]]; then
    if [[ "$(check_extract_summary_nonempty "$gemini_parser_extract")" == "ok" ]]; then
      if [[ "$(check_extract_timestamp_fields_present "$gemini_parser_extract")" == "ok" ]]; then
        pass "Parser selection: gemini-2.5-flash (summary + timestamps present)"
      else
        fail "Parser selection: gemini-2.5-flash (timestamps missing fields)"
      fi
    else
      fail "Parser selection: gemini-2.5-flash (summary missing/empty)"
    fi
  else
    fail "Parser selection: gemini-2.5-flash"
  fi

  # 4d) Parser selection - mistral
  # If MISTRAL_API_KEY is not configured, expect a clear error payload instead of hard failure.
  mistral_extract="$(curl -sS -X POST "$BACKEND_URL/api/pdf/extract" -F "parser=mistral" -F "files=@$PDF_FILE" || true)"
  if [[ "$mistral_extract" == *"MISTRAL_API_KEY is not set"* ]]; then
    pass "Parser selection: mistral (clear missing-key error)"
  elif [[ "$(check_extract_parser_value "$mistral_extract" "mistral")" == "ok" ]]; then
    pass "Parser selection: mistral"
  else
    fail "Parser selection: mistral"
  fi

  # 5) Cache behavior quick check (at least one cached hit)
  if [[ "$(check_extract_any_cached_true "$multi_extract")" == "ok" ]]; then
    pass "Redis cache observed in extraction"
  else
    fail "Redis cache observed in extraction"
  fi

  # 5b) Async processing via Redis Streams (FR-3)
  job_submit_json="$(curl -sS -X POST "$BACKEND_URL/api/jobs/extract" \
    -F "parser=pypdf" \
    -F "files=@$PDF_FILE" || true)"

  job_id="$(python3 - "$job_submit_json" <<'PY'
import json, sys
data=json.loads(sys.argv[1])
jobs=data.get("jobs", [])
print(jobs[0]["job_id"] if isinstance(jobs, list) and jobs and "job_id" in jobs[0] else "")
PY
)"

  if [[ -z "$job_id" ]]; then
    fail "Async job submission (FR-3)"
  else
    # Poll until done (or failed)
    status=""
    job_text_nonempty="bad"
    for _ in $(seq 1 30); do
      job_json="$(curl -sS "$BACKEND_URL/api/jobs/$job_id" || true)"
      status="$(python3 - "$job_json" <<'PY'
import json, sys
data=json.loads(sys.argv[1]) if sys.argv[1] else {}
print(data.get("status",""))
PY
)"
      if [[ "$status" == "done" ]]; then
        if [[ "$(python3 - "$job_json" <<'PY'
import json, sys
data=json.loads(sys.argv[1])
res=data.get("result") or {}
text=res.get("text") if isinstance(res, dict) else None
print("ok" if isinstance(text,str) and text.strip() else "bad")
PY
)" == "ok" ]]; then
          if [[ "$(check_job_result_summary_nonempty "$job_json")" == "ok" ]]; then
          if [[ "$(check_job_result_timestamp_fields_present "$job_json")" == "ok" ]]; then
            job_text_nonempty="ok"
          fi
          fi
        fi
        break
      elif [[ "$status" == "failed" ]]; then
        break
      fi
      sleep 1
    done

    if [[ "$status" == "done" && "$job_text_nonempty" == "ok" ]]; then
      pass "Async processing via Redis Streams (FR-3)"
    else
      fail "Async processing via Redis Streams (FR-3) (status=$status)"
    fi
  fi
done

# 6) Frontend proxy health
proxy_health_json="$(curl -sS "$FRONTEND_URL/api/health" || true)"
if [[ "$(check_contains_status_ok "$proxy_health_json")" == "ok" ]]; then
  pass "Frontend /api proxy health"
else
  fail "Frontend /api proxy health"
fi

# 7) Gemini basic test (optional if API key missing)
gemini_response="$(curl -sS -X POST "$BACKEND_URL/api/gemini/answer" \
  -H "content-type: application/json" \
  -d '{"prompt":"Smoke test in English.","context":"","language":"en"}' || true)"

if [[ "$(check_gemini_payload "$gemini_response")" == "ok" ]]; then
  pass "Gemini response"
else
  # If key is not configured/restricted, we mark as fail but print payload for diagnosis.
  fail "Gemini response (check GOOGLE_API_KEY or provider restrictions)"
  echo "Gemini payload: $gemini_response"
fi

echo
echo "--------------------------------------"
echo "Smoke tests finished: PASS=$pass_count FAIL=$fail_count"
echo "--------------------------------------"

if [[ "$fail_count" -gt 0 ]]; then
  exit 1
fi

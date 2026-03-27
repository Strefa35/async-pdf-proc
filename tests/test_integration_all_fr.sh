#!/usr/bin/env bash
# Integration: FR-1..FR-7 across sync (/api/pdf/extract) and async (/api/jobs/*) paths,
# plus edge cases (invalid job, empty file, no files). One script = full requirement sweep.
#
# Prerequisites: backend + Redis + worker (for async). GOOGLE_API_KEY for FR-5/FR-6 summaries
# (same as per-FR tests). Optional extra PDFs in tests/fixtures/pdf/ for multi-file batch.
#
# Usage:
#   ./tests/test_integration_all_fr.sh
# Env: BACKEND_URL FRONTEND_URL PDF_FILE (see tests/lib/fr_common.sh)
# Optional: PARSER=pypdf|gemini-2.5-flash|mistral for the multi-PDF async batch block only (default pypdf).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/fr_common.sh
source "$SCRIPT_DIR/lib/fr_common.sh"

PARSER="${PARSER:-pypdf}"

fail=0
pass_msg() { echo "PASS [$1]: $2"; }
fail_msg() { echo "FAIL [$1]: $2" >&2; fail=$((fail + 1)); }

echo "========================================"
echo "Integration: FR-1..FR-7 (sync + async + edges)"
echo "BACKEND_URL=$FR_BACKEND_URL FRONTEND_URL=$FRONTEND_URL"
if [[ -n "${PDF_FILE:-}" ]]; then
  echo "PDF_FILE=$PDF_FILE (single file)"
else
  echo "PDF fixtures (${#FR_PDF_FILES[@]} file(s)):"
  for _p in "${FR_PDF_FILES[@]}"; do
    echo "  $_p"
  done
fi
echo "========================================"

# ---------------------------------------------------------------------------
# Edge cases — async API (no PDF required)
# ---------------------------------------------------------------------------
code="$(curl -sS -o /dev/null -w "%{http_code}" \
  "$FR_BACKEND_URL/api/jobs/ffffffffffffffffffffffffffffffff" || true)"
if [[ "$code" == "404" ]]; then
  pass_msg "edge" "GET unknown job → HTTP 404"
else
  fail_msg "edge" "unknown job: expected 404, got $code"
fi

empty_f="$(mktemp)"
truncate -s 0 "$empty_f"
code="$(curl -sS -o /dev/null -w "%{http_code}" -X POST "$FR_BACKEND_URL/api/jobs/extract" \
  -F "parser=pypdf" \
  -F "files=@${empty_f};type=application/pdf" || true)"
rm -f "$empty_f"
if [[ "$code" == "400" ]]; then
  pass_msg "edge" "empty file POST /api/jobs/extract → HTTP 400"
else
  fail_msg "edge" "empty file: expected 400, got $code"
fi

code="$(curl -sS -o /dev/null -w "%{http_code}" -X POST "$FR_BACKEND_URL/api/jobs/extract" \
  -F "parser=pypdf" || true)"
if [[ "$code" == "422" || "$code" == "400" ]]; then
  pass_msg "edge" "POST /api/jobs/extract without files → HTTP $code"
else
  fail_msg "edge" "no files: expected 422 or 400, got $code"
fi

fr_require_pdf

for FR_PDF_FILE in "${FR_PDF_FILES[@]}"; do
  if [[ ${#FR_PDF_FILES[@]} -gt 1 ]]; then
    echo "---------- PDF: $(basename "$FR_PDF_FILE") ----------"
  fi

  # ---------------------------------------------------------------------------
  # FR-1 — multi-file sync + parser in request
  # ---------------------------------------------------------------------------
  resp_fr1="$(curl -sS -X POST "$FR_BACKEND_URL/api/pdf/extract" \
    -F "parser=pypdf" \
    -F "files=@$FR_PDF_FILE" \
    -F "files=@$FR_PDF_FILE" || true)"
  if [[ "$(fr_json_extract_results_len "$resp_fr1" 2)" != "ok" ]] || [[ "$(fr_json_parser_all "$resp_fr1" "pypdf")" != "ok" ]]; then
    fail_msg "FR-1" "multi-file sync: expected 2 results with parser pypdf"
    echo "$resp_fr1" >&2
  else
    pass_msg "FR-1" "multi-file upload + parser in /api/pdf/extract response"
  fi

  # ---------------------------------------------------------------------------
  # FR-4, FR-5, FR-6 — single sync extract (shared response)
  # ---------------------------------------------------------------------------
  resp_sync="$(curl -sS -X POST "$FR_BACKEND_URL/api/pdf/extract" \
    -F "parser=pypdf" \
    -F "language=en" \
    -F "files=@$FR_PDF_FILE" || true)"

  if [[ "$(fr_json_pages_nonempty_first "$resp_sync")" != "ok" ]]; then
    fail_msg "FR-4" "pages[] missing or invalid (pypdf)"
    echo "$resp_sync" >&2
  else
    pass_msg "FR-4" "per-page pages[] in sync extract"
  fi

  if [[ "$(fr_json_summary_nonempty_first "$resp_sync")" != "ok" ]]; then
    fail_msg "FR-5" "summary missing or empty (check GOOGLE_API_KEY)"
    echo "$resp_sync" >&2
  else
    pass_msg "FR-5" "summary per file (Gemini) in sync extract"
  fi

  if [[ "$(fr_json_timestamp_fields_first "$resp_sync")" != "ok" ]]; then
    fail_msg "FR-6" "content_generated_at / summary_generated_at missing"
    echo "$resp_sync" >&2
  else
    pass_msg "FR-6" "timestamps on first sync result"
  fi

  sha="$(echo "$resp_sync" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); r=d.get("results",[{}])[0]; print(r.get("sha256") or "")')"
  parser="$(echo "$resp_sync" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); r=d.get("results",[{}])[0]; print(r.get("parser") or "")')"
  if [[ -z "$sha" || -z "$parser" ]]; then
    fail_msg "FR-6" "sha256 or parser missing on sync result"
  else
    pass_msg "FR-6" "sha256 + parser on sync result"
  fi

  # ---------------------------------------------------------------------------
  # FR-2 — parser selection (pypdf, gemini, mistral)
  # ---------------------------------------------------------------------------
  for parser in pypdf gemini-2.5-flash; do
    r="$(curl -sS -X POST "$FR_BACKEND_URL/api/pdf/extract" \
      -F "parser=$parser" \
      -F "files=@$FR_PDF_FILE" || true)"
    if [[ "$(fr_json_parser_all "$r" "$parser")" != "ok" ]]; then
      fail_msg "FR-2" "parser $parser not reflected in results"
      echo "$r" >&2
    else
      pass_msg "FR-2" "parser=$parser in /api/pdf/extract"
    fi
  done

  mistral_resp="$(curl -sS -X POST "$FR_BACKEND_URL/api/pdf/extract" \
    -F "parser=mistral" \
    -F "files=@$FR_PDF_FILE" || true)"
  if [[ "$mistral_resp" == *"MISTRAL_API_KEY is not set"* ]]; then
    pass_msg "FR-2" "mistral: expected missing-key message (no MISTRAL_API_KEY)"
  elif [[ "$(fr_json_parser_all "$mistral_resp" "mistral")" == "ok" ]]; then
    pass_msg "FR-2" "parser=mistral in /api/pdf/extract"
  else
    fail_msg "FR-2" "mistral unexpected response"
    echo "$mistral_resp" >&2
  fi

  # ---------------------------------------------------------------------------
  # FR-3 + FR-4 + FR-6 + FR-7 — async job: submit, poll, result shape, optional FE proxy
  # ---------------------------------------------------------------------------
  submit_json="$(curl -sS -X POST "$FR_BACKEND_URL/api/jobs/extract" \
    -F "parser=pypdf" \
    -F "language=en" \
    -F "files=@$FR_PDF_FILE" || true)"
  job_id="$(echo "$submit_json" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); j=d.get("jobs",[]); print(j[0]["job_id"] if j else "")')"

  if [[ -z "$job_id" ]]; then
    fail_msg "FR-3" "no job_id from POST /api/jobs/extract"
    echo "$submit_json" >&2
  else
    pass_msg "FR-3" "POST /api/jobs/extract returns job_id (Redis Streams queue)"
    queued_json="$(curl -sS "$FR_BACKEND_URL/api/jobs/$job_id" || true)"
    qstatus="$(echo "$queued_json" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("status",""))')"
    if [[ "$qstatus" == "queued" || "$qstatus" == "processing" || "$qstatus" == "done" ]]; then
      pass_msg "FR-3" "initial GET /api/jobs/{id} status=$qstatus"
    else
      fail_msg "FR-3" "unexpected initial status=$qstatus"
    fi

    final_json="$(fr_poll_job_done "$job_id" 45 1 || true)"
    st=""
    if [[ -n "$final_json" ]]; then
      st="$(echo "$final_json" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("status",""))')"
    fi
    if [[ -z "$final_json" ]]; then
      fail_msg "FR-3" "poll timeout for job $job_id"
    elif [[ "$st" != "done" ]]; then
      fail_msg "FR-3" "job $job_id not done (status=$st)"
      echo "$final_json" >&2
    else
      pass_msg "FR-3" "job reaches status=done"
      if [[ "$(fr_job_result_ok "$final_json")" != "ok" ]]; then
        fail_msg "FR-5/FR-6" "async result: text, summary, timestamps"
        echo "$final_json" >&2
      else
        pass_msg "FR-5/FR-6" "async job result has text, summary, timestamps"
      fi
      if [[ "$(fr_job_result_pages_ok "$final_json")" != "ok" ]]; then
        fail_msg "FR-4" "async job result: pages[]"
        echo "$final_json" >&2
      else
        pass_msg "FR-4" "async job result has pages[]"
      fi
      if [[ "$(fr_job_result_sha_parser_ok "$final_json")" != "ok" ]]; then
        fail_msg "FR-6" "async job result: sha256 + parser"
        echo "$final_json" >&2
      else
        pass_msg "FR-6" "async job result has sha256 + parser"
      fi
    fi

    proxy_json="$(curl -sS "$FRONTEND_URL/api/jobs/$job_id" || true)"
    proxy_st="$(echo "$proxy_json" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("status",""))' 2>/dev/null || echo "")"
    if [[ "$proxy_st" == "done" ]]; then
      pass_msg "FR-7" "frontend proxy GET /api/jobs/{id} → status=done"
    else
      echo "WARN [FR-7]: frontend proxy status='$proxy_st' (backend OK if FR-3 passed)" >&2
    fi
  fi
done

# ---------------------------------------------------------------------------
# Optional: multi-file async batch (same POST → multiple jobs)
# ---------------------------------------------------------------------------
batch_files=("${FR_PDF_FILES[@]}")

if [[ ${#batch_files[@]} -lt 2 ]]; then
  echo "SKIP [batch]: need ≥2 PDFs under tests/fixtures/pdf/ (found: ${#batch_files[@]})"
else
  curl_args=(-sS -X POST "$FR_BACKEND_URL/api/jobs/extract" -F "parser=$PARSER" -F "language=en")
  for p in "${batch_files[@]}"; do
    curl_args+=(-F "files=@$p")
  done
  batch_submit="$(curl "${curl_args[@]}" || true)"
  n_jobs="$(echo "$batch_submit" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(len(d.get("jobs",[])))')"
  if [[ "$n_jobs" != "${#batch_files[@]}" ]]; then
    fail_msg "batch" "expected ${#batch_files[@]} jobs, got $n_jobs"
    echo "$batch_submit" >&2
  else
    batch_ok=1
    while read -r jid; do
      [[ -z "$jid" ]] && continue
      fj="$(fr_poll_job_done "$jid" 120 1 || true)"
      jst="$(echo "$fj" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("status",""))')"
      if [[ "$jst" != "done" ]] || [[ "$(fr_job_result_ok "$fj")" != "ok" ]]; then
        fail_msg "batch" "job $jid incomplete"
        echo "$fj" >&2
        batch_ok=0
        break
      fi
    done < <(echo "$batch_submit" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read());
for j in d.get("jobs",[]): print(j.get("job_id",""))')
    if [[ "$batch_ok" -eq 1 ]]; then
      pass_msg "batch" "multi-PDF async: ${#batch_files[@]} jobs completed"
    fi
  fi
fi

echo "========================================"
if [[ "$fail" -eq 0 ]]; then
  echo "Integration (all FR): PASS"
  exit 0
fi
echo "Integration (all FR): $fail check(s) failed" >&2
exit 1

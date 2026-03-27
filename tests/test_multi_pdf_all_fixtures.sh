#!/usr/bin/env bash
# Multi-PDF: one POST with every fixture PDF (sync /api/pdf/extract + async /api/jobs/extract).
# Uses FR_PDF_FILES from tests/lib/fr_common.sh (all *.pdf under tests/fixtures/pdf/ when PDF_FILE is unset).
#
# Env: BACKEND_URL FRONTEND_URL PDF_FILE (optional single-file override)
# Optional: PARSER=pypdf|gemini-2.5-flash|mistral for async batch (default pypdf).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/fr_common.sh
source "$SCRIPT_DIR/lib/fr_common.sh"

PARSER="${PARSER:-pypdf}"

echo "[multi-PDF all fixtures] sync + async (one request each, N=${#FR_PDF_FILES[@]} file(s))"

if [[ ${#FR_PDF_FILES[@]} -lt 2 ]]; then
  echo "SKIP: need at least 2 PDFs under tests/fixtures/pdf/ (found: ${#FR_PDF_FILES[@]})"
  exit 0
fi

n="${#FR_PDF_FILES[@]}"

# --- Sync: all PDFs in one /api/pdf/extract ---
curl_sync=(-sS -X POST "$FR_BACKEND_URL/api/pdf/extract" -F "parser=pypdf")
for p in "${FR_PDF_FILES[@]}"; do
  curl_sync+=(-F "files=@$p")
done
resp_sync="$(curl "${curl_sync[@]}" || true)"
if [[ "$(fr_json_extract_results_len "$resp_sync" "$n")" != "ok" ]]; then
  echo "FAIL: sync multi-PDF: expected $n results" >&2
  echo "$resp_sync" >&2
  exit 1
fi
if [[ "$(fr_json_parser_all "$resp_sync" "pypdf")" != "ok" ]]; then
  echo "FAIL: sync multi-PDF: parser not pypdf on all results" >&2
  exit 1
fi
echo "PASS: sync /api/pdf/extract — $n PDFs in one request"

# --- Async: all PDFs in one /api/jobs/extract ---
curl_async=(-sS -X POST "$FR_BACKEND_URL/api/jobs/extract" -F "parser=$PARSER" -F "language=en")
for p in "${FR_PDF_FILES[@]}"; do
  curl_async+=(-F "files=@$p")
done
batch_submit="$(curl "${curl_async[@]}" || true)"
n_jobs="$(echo "$batch_submit" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(len(d.get("jobs",[])))')"
if [[ "$n_jobs" != "$n" ]]; then
  echo "FAIL: async multi-PDF: expected $n jobs, got $n_jobs" >&2
  echo "$batch_submit" >&2
  exit 1
fi

batch_ok=1
while read -r jid; do
  [[ -z "$jid" ]] && continue
  fj="$(fr_poll_job_done "$jid" 120 1 || true)"
  jst="$(echo "$fj" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("status",""))')"
  if [[ "$jst" != "done" ]] || [[ "$(fr_job_result_ok "$fj")" != "ok" ]]; then
    echo "FAIL: async multi-PDF: job $jid incomplete" >&2
    echo "$fj" >&2
    batch_ok=0
    break
  fi
done < <(echo "$batch_submit" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read());
for j in d.get("jobs",[]): print(j.get("job_id",""))')

if [[ "$batch_ok" -ne 1 ]]; then
  exit 1
fi
echo "PASS: async /api/jobs/extract — $n jobs from one request (parser=$PARSER)"
exit 0

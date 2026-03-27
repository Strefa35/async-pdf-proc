#!/usr/bin/env bash
# FR-7: Result retrieval after completion — poll GET /api/jobs/{id}; optional frontend proxy.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/fr_common.sh
source "$SCRIPT_DIR/lib/fr_common.sh"

fr_require_pdf
echo "[FR-7] Poll job status + retrieve result (and frontend proxy)"

submit_json="$(curl -sS -X POST "$FR_BACKEND_URL/api/jobs/extract" \
  -F "parser=pypdf" \
  -F "language=en" \
  -F "files=@$FR_PDF_FILE" || true)"

job_id="$(echo "$submit_json" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); j=d.get("jobs",[]); print(j[0]["job_id"] if j else "")')"

if [[ -z "$job_id" ]]; then
  echo "FAIL: no job_id" >&2
  echo "$submit_json" >&2
  exit 1
fi

final_json="$(fr_poll_job_done "$job_id" 45 1 || true)"
if [[ -z "$final_json" ]]; then
  echo "FAIL: poll timeout" >&2
  exit 1
fi

st="$(echo "$final_json" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("status",""))')"
if [[ "$st" != "done" ]]; then
  echo "FAIL: expected done, got $st" >&2
  echo "$final_json" >&2
  exit 1
fi

if [[ "$(fr_job_result_ok "$final_json")" != "ok" ]]; then
  echo "FAIL: job result incomplete" >&2
  exit 1
fi

proxy_json="$(curl -sS "$FRONTEND_URL/api/jobs/$job_id" || true)"
proxy_st="$(echo "$proxy_json" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("status",""))' 2>/dev/null || echo "")"
if [[ "$proxy_st" != "done" ]]; then
  echo "WARN: frontend proxy job status not done (got '$proxy_st'); backend OK" >&2
fi

echo "PASS: FR-7"
exit 0

#!/usr/bin/env bash
# FR-3: Asynchronous processing — Redis Streams; upload returns job id; worker completes.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/fr_common.sh
source "$SCRIPT_DIR/lib/fr_common.sh"

fr_require_pdf
echo "[FR-3] Async job submit + poll until done"

submit_json="$(curl -sS -X POST "$FR_BACKEND_URL/api/jobs/extract" \
  -F "parser=pypdf" \
  -F "files=@$FR_PDF_FILE" || true)"

job_id="$(echo "$submit_json" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); j=d.get("jobs",[]); print(j[0]["job_id"] if j and "job_id" in j[0] else "")')"

if [[ -z "$job_id" ]]; then
  echo "FAIL: no job_id in response" >&2
  echo "$submit_json" >&2
  exit 1
fi

queued_json="$(curl -sS "$FR_BACKEND_URL/api/jobs/$job_id" || true)"
qstatus="$(echo "$queued_json" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("status",""))')"
if [[ "$qstatus" != "queued" && "$qstatus" != "processing" && "$qstatus" != "done" ]]; then
  echo "WARN: initial status=$qstatus (expected queued/processing/done)" >&2
fi

final_json="$(fr_poll_job_done "$job_id" 45 1 || true)"
if [[ -z "$final_json" ]]; then
  echo "FAIL: poll timeout" >&2
  exit 1
fi

st="$(echo "$final_json" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("status",""))')"
if [[ "$st" != "done" ]]; then
  echo "FAIL: job status is $st" >&2
  echo "$final_json" >&2
  exit 1
fi

if [[ "$(fr_job_result_ok "$final_json")" != "ok" ]]; then
  echo "FAIL: job result incomplete" >&2
  echo "$final_json" >&2
  exit 1
fi

echo "PASS: FR-3"
exit 0

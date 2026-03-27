#!/usr/bin/env bash
# FR-6: Persistence in Redis — reflected via API (parser, text/pages, summary, timestamps).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/fr_common.sh
source "$SCRIPT_DIR/lib/fr_common.sh"

fr_require_pdf
echo "[FR-6] Parser + content + summary + timestamp fields (sync extract)"

resp="$(curl -sS -X POST "$FR_BACKEND_URL/api/pdf/extract" \
  -F "parser=pypdf" \
  -F "language=en" \
  -F "files=@$FR_PDF_FILE" || true)"

if [[ "$(fr_json_timestamp_fields_first "$resp")" != "ok" ]]; then
  echo "FAIL: content_generated_at / summary_generated_at missing" >&2
  echo "$resp" >&2
  exit 1
fi

sha="$(echo "$resp" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); r=d.get("results",[{}])[0]; print(r.get("sha256") or "")')"
parser="$(echo "$resp" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); r=d.get("results",[{}])[0]; print(r.get("parser") or "")')"
if [[ -z "$sha" || -z "$parser" ]]; then
  echo "FAIL: sha256 or parser missing" >&2
  exit 1
fi

echo "PASS: FR-6"
exit 0

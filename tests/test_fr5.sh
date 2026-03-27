#!/usr/bin/env bash
# FR-5: One summary per uploaded file (Gemini 2.5 Flash).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/fr_common.sh
source "$SCRIPT_DIR/lib/fr_common.sh"

fr_require_pdf
echo "[FR-5] Summary per file (sync extract)"

resp="$(curl -sS -X POST "$FR_BACKEND_URL/api/pdf/extract" \
  -F "parser=pypdf" \
  -F "language=en" \
  -F "files=@$FR_PDF_FILE" || true)"

if [[ "$(fr_json_summary_nonempty_first "$resp")" != "ok" ]]; then
  echo "FAIL: summary missing or empty (check GOOGLE_API_KEY)" >&2
  echo "$resp" >&2
  exit 1
fi

echo "PASS: FR-5"
exit 0

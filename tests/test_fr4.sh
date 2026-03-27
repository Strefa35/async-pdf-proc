#!/usr/bin/env bash
# FR-4: Parsed output per file — pages[]; pypdf plain text; gemini/mistral markdown-oriented when available.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/fr_common.sh
source "$SCRIPT_DIR/lib/fr_common.sh"

fr_require_pdf
echo "[FR-4] Per-page output (pages[])"

resp="$(curl -sS -X POST "$FR_BACKEND_URL/api/pdf/extract" \
  -F "parser=pypdf" \
  -F "files=@$FR_PDF_FILE" || true)"

if [[ "$(fr_json_pages_nonempty_first "$resp")" != "ok" ]]; then
  echo "FAIL: pages[] missing or invalid for pypdf" >&2
  echo "$resp" >&2
  exit 1
fi

echo "PASS: FR-4"
exit 0

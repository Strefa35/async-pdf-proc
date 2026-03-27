#!/usr/bin/env bash
# FR-1: Document upload — one or more PDFs; request includes parser selection.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/fr_common.sh
source "$SCRIPT_DIR/lib/fr_common.sh"

fr_require_pdf
echo "[FR-1] Multi-file upload + parser in request (pypdf)"

resp="$(curl -sS -X POST "$FR_BACKEND_URL/api/pdf/extract" \
  -F "parser=pypdf" \
  -F "files=@$FR_PDF_FILE" \
  -F "files=@$FR_PDF_FILE" || true)"

if [[ "$(fr_json_extract_results_len "$resp" 2)" != "ok" ]]; then
  echo "FAIL: expected 2 results (FR-1)" >&2
  echo "$resp" >&2
  exit 1
fi

if [[ "$(fr_json_parser_all "$resp" "pypdf")" != "ok" ]]; then
  echo "FAIL: parser field not pypdf on all results" >&2
  exit 1
fi

echo "PASS: FR-1"
exit 0

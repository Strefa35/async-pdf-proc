#!/usr/bin/env bash
# FR-2: Parser selection — pypdf, gemini-2.5-flash, mistral (mock or key).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/fr_common.sh
source "$SCRIPT_DIR/lib/fr_common.sh"

fr_require_pdf
echo "[FR-2] Parser selection (pypdf, gemini, mistral)"

for parser in pypdf gemini-2.5-flash; do
  resp="$(curl -sS -X POST "$FR_BACKEND_URL/api/pdf/extract" \
    -F "parser=$parser" \
    -F "files=@$FR_PDF_FILE" || true)"
  if [[ "$(fr_json_parser_all "$resp" "$parser")" != "ok" ]]; then
    echo "FAIL: parser $parser not reflected in results" >&2
    echo "$resp" >&2
    exit 1
  fi
done

mistral_resp="$(curl -sS -X POST "$FR_BACKEND_URL/api/pdf/extract" \
  -F "parser=mistral" \
  -F "files=@$FR_PDF_FILE" || true)"

if [[ "$mistral_resp" == *"MISTRAL_API_KEY is not set"* ]]; then
  echo "PASS: FR-2 (mistral: expected missing-key message)"
  exit 0
fi

if [[ "$(fr_json_parser_all "$mistral_resp" "mistral")" == "ok" ]]; then
  echo "PASS: FR-2"
  exit 0
fi

echo "FAIL: mistral parser unexpected response" >&2
echo "$mistral_resp" >&2
exit 1

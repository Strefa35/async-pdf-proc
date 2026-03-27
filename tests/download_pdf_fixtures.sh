#!/usr/bin/env bash
# Download a diverse set of PDF fixtures for tests/fixtures/pdf.
# Usage:
#   ./tests/download_pdf_fixtures.sh
#   ./tests/download_pdf_fixtures.sh --force
#   ./tests/download_pdf_fixtures.sh --strict
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_DIR="$PROJECT_ROOT/tests/fixtures/pdf"

FORCE=0
STRICT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)
      FORCE=1
      shift
      ;;
    --strict)
      STRICT=1
      shift
      ;;
    -h|--help)
      cat <<'EOF'
Download PDF fixtures into tests/fixtures/pdf.

Options:
  --force   Re-download files even if they already exist
  --strict  Exit with non-zero code if any file fails
  -h, --help
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

mkdir -p "$TARGET_DIR"

# Format: "filename|url"
# Keep this list intentionally small/lightweight for faster test runs.
PDF_SOURCES=(
  "drylab.pdf|https://princexml.com/samples/newsletter/drylab.pdf"
  "example.pdf|https://princexml.com/samples/usenix/example.pdf"
  "flyer.pdf|https://princexml.com/samples/flyer/flyer.pdf"
  "somatosensory.pdf|https://princexml.com/samples/textbook/somatosensory.pdf"
)

download_one() {
  local filename="$1"
  local url="$2"
  local dest="$TARGET_DIR/$filename"
  local tmp="${dest}.part"

  if [[ -f "$dest" && "$FORCE" -ne 1 ]]; then
    echo "SKIP  $filename (already exists)"
    return 0
  fi

  echo "GET   $filename"
  if curl -fsSL --retry 2 --retry-delay 1 --connect-timeout 10 --max-time 120 "$url" -o "$tmp"; then
    if [[ ! -s "$tmp" ]]; then
      rm -f "$tmp"
      echo "FAIL  $filename (empty response)"
      return 1
    fi
    mv "$tmp" "$dest"
    echo "OK    $filename"
    return 0
  fi

  rm -f "$tmp"
  echo "FAIL  $filename ($url)"
  return 1
}

ok_count=0
fail_count=0

for entry in "${PDF_SOURCES[@]}"; do
  filename="${entry%%|*}"
  url="${entry#*|}"
  if download_one "$filename" "$url"; then
    ok_count=$((ok_count + 1))
  else
    fail_count=$((fail_count + 1))
  fi
done

echo
echo "Done. Success: $ok_count, Failed: $fail_count"
echo "Fixtures dir: $TARGET_DIR"

if [[ "$STRICT" -eq 1 && "$fail_count" -gt 0 ]]; then
  exit 1
fi

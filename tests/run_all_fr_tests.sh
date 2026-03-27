#!/usr/bin/env bash
# Run FR-1..FR-7 tests individually. Does not modify tests/run_smoke_tests.sh.
#
# Usage:
#   ./tests/run_all_fr_tests.sh
#   ./tests/run_all_fr_tests.sh --reverse
#   ./tests/run_all_fr_tests.sh --shuffle
#   ./tests/run_all_fr_tests.sh --order 7,6,5,4,3,2,1
#   ./tests/run_all_fr_tests.sh --only fr3,fr5
# Tags: fr1..fr7 (per fixture PDF), multi (once: all PDFs in one sync + async request; needs ≥2 fixtures)
#
# Env (optional):
#   BACKEND_URL FRONTEND_URL PDF_FILE
# If PDF_FILE is unset, every *.pdf under tests/fixtures/pdf/ is used; the suite runs once per file.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
# shellcheck source=lib/fr_common.sh
source "$SCRIPT_DIR/lib/fr_common.sh"

DEFAULT_ORDER=(fr1 fr2 fr3 fr4 fr5 fr6 fr7 multi)
ORDER=("${DEFAULT_ORDER[@]}")
ONLY=()

usage() {
  sed -n '1,20p' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reverse)
      ORDER=(fr7 fr6 fr5 fr4 fr3 fr2 fr1 multi)
      shift
      ;;
    --shuffle)
      if command -v shuf >/dev/null 2>&1; then
        ORDER=($(shuf -e "${DEFAULT_ORDER[@]}"))
      else
        ORDER=($(python3 -c 'import random; x="fr1 fr2 fr3 fr4 fr5 fr6 fr7 multi".split(); random.shuffle(x); print(" ".join(x))'))
      fi
      shift
      ;;
    --order)
      IFS=',' read -r -a ORDER <<<"${2:-}"
      shift 2
      ;;
    --only)
      IFS=',' read -r -a ONLY <<<"${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ ${#ONLY[@]} -gt 0 ]]; then
  ORDER=("${ONLY[@]}")
fi

ORDER_PER_PDF=()
RUN_MULTI=0
for tag in "${ORDER[@]}"; do
  tag="$(echo "$tag" | tr -d '[:space:]')"
  [[ -z "$tag" ]] && continue
  if [[ "$tag" == "multi" ]]; then
    RUN_MULTI=1
  else
    ORDER_PER_PDF+=("$tag")
  fi
done

map_script() {
  case "$1" in
    fr1) echo "$SCRIPT_DIR/test_fr1.sh" ;;
    fr2) echo "$SCRIPT_DIR/test_fr2.sh" ;;
    fr3) echo "$SCRIPT_DIR/test_fr3.sh" ;;
    fr4) echo "$SCRIPT_DIR/test_fr4.sh" ;;
    fr5) echo "$SCRIPT_DIR/test_fr5.sh" ;;
    fr6) echo "$SCRIPT_DIR/test_fr6.sh" ;;
    fr7) echo "$SCRIPT_DIR/test_fr7.sh" ;;
    multi) echo "$SCRIPT_DIR/test_multi_pdf_all_fixtures.sh" ;;
    *) echo "" ;;
  esac
}

pass=0
fail=0
failed_list=()

echo "FR test order: ${ORDER_PER_PDF[*]}$([[ "$RUN_MULTI" -eq 1 ]] && echo ' multi')"
echo "BACKEND_URL=${BACKEND_URL:-http://localhost:8000}"
echo "FRONTEND_URL=${FRONTEND_URL:-http://localhost:5173}"
if [[ -n "${PDF_FILE:-}" ]]; then
  echo "PDF_FILE=$PDF_FILE (single file)"
else
  echo "PDF fixtures (${#FR_PDF_FILES[@]} file(s)):"
  for _p in "${FR_PDF_FILES[@]}"; do
    echo "  $_p"
  done
fi
echo "----------------------------------------"

if [[ ${#ORDER_PER_PDF[@]} -gt 0 ]]; then
  for pdf in "${FR_PDF_FILES[@]}"; do
    if [[ ${#FR_PDF_FILES[@]} -gt 1 ]]; then
      echo ""
      echo "========== PDF: $(basename "$pdf") =========="
    fi
    export PDF_FILE="$pdf"
    for tag in "${ORDER_PER_PDF[@]}"; do
      tag="$(echo "$tag" | tr -d '[:space:]')"
      [[ -z "$tag" ]] && continue
      scr="$(map_script "$tag")"
      if [[ -z "$scr" || ! -f "$scr" ]]; then
        echo "[SKIP] unknown tag: $tag"
        continue
      fi
      echo ""
      echo ">>> Running $tag ($(basename "$scr"))"
      if bash "$scr"; then
        pass=$((pass + 1))
      else
        fail=$((fail + 1))
        failed_list+=("${tag}@$(basename "$pdf")")
      fi
    done
  done
fi

if [[ "$RUN_MULTI" -eq 1 ]]; then
  echo ""
  echo ">>> Running multi ($(basename "$SCRIPT_DIR/test_multi_pdf_all_fixtures.sh"))"
  # Child must discover all fixtures; do not inherit PDF_FILE from the last per-PDF iteration.
  if env -u PDF_FILE bash "$SCRIPT_DIR/test_multi_pdf_all_fixtures.sh"; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    failed_list+=(multi)
  fi
fi

echo ""
echo "========================================"
echo "FR suite finished: PASS=$pass FAIL=$fail"
if [[ ${#failed_list[@]} -gt 0 ]]; then
  echo "Failed: ${failed_list[*]}"
  exit 1
fi
exit 0

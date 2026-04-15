#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "ERROR: neither 'docker compose' nor 'docker-compose' is available." >&2
  exit 1
fi

cleanup() {
  "${COMPOSE_CMD[@]}" down -v --remove-orphans || true
}
trap cleanup EXIT

cd "$PROJECT_ROOT"

echo "[CI] Starting clean build"
"${COMPOSE_CMD[@]}" down -v --remove-orphans || true
"${COMPOSE_CMD[@]}" up -d --build

echo "[CI] Downloading PDF fixtures"
python3 tests/download_pdf_fixtures.py --force --strict

echo "[CI] Running pytest integration suite (JUnit + HTML under tests/report/)"
python3 tests/run_pytest.py

echo "[CI] All checks passed"

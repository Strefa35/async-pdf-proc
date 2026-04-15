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

wait_for_http() {
  local url=$1
  local label=$2
  local timeout_sec=${CI_STACK_READY_TIMEOUT_SECONDS:-120}
  local interval_sec=${CI_STACK_READY_POLL_INTERVAL_SECONDS:-2}
  local deadline=$(( $(date +%s) + timeout_sec ))
  local last_log=0

  echo "[CI] Readiness: polling $label ($url, timeout ${timeout_sec}s)"
  while true; do
    if curl -sf --max-time 3 "$url" >/dev/null; then
      echo "[CI] Readiness: $label OK"
      return 0
    fi
    local now
    now=$(date +%s)
    if (( now >= deadline )); then
      echo "ERROR: Timed out after ${timeout_sec}s waiting for $label (${url})" >&2
      exit 1
    fi
    if (( last_log == 0 || now - last_log >= 10 )); then
      echo "[CI] Readiness: still waiting for $label ($(( deadline - now ))s left)"
      last_log=$now
    fi
    sleep "$interval_sec"
  done
}

compose_supports_wait=false
if "${COMPOSE_CMD[@]}" up --help 2>&1 | grep -qE '(^|[[:space:]])--wait([[:space:]]|$)'; then
  compose_supports_wait=true
fi

echo "[CI] Starting clean build"
"${COMPOSE_CMD[@]}" down -v --remove-orphans || true

if [[ "$compose_supports_wait" == true ]]; then
  echo "[CI] Starting stack (up -d --build --wait --wait-timeout 120)"
  "${COMPOSE_CMD[@]}" up -d --build --wait --wait-timeout 120
else
  echo "[CI] Starting stack (up -d --build; no --wait in this compose version)"
  "${COMPOSE_CMD[@]}" up -d --build
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "ERROR: curl is required for stack readiness checks" >&2
  exit 1
fi
wait_for_http "http://127.0.0.1:8000/api/health" "backend"
wait_for_http "http://127.0.0.1:5173/api/health" "frontend API proxy"

echo "[CI] Downloading PDF fixtures"
python3 tests/download_pdf_fixtures.py --force --strict

echo "[CI] Running pytest integration suite (JUnit + HTML under tests/report/)"
python3 tests/run_pytest.py

echo "[CI] All checks passed"

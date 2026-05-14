#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

HOST_ADDRESS="${HOST_ADDRESS:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

cleanup() {
  jobs -p | xargs -r kill
}
trap cleanup EXIT INT TERM

uv run uvicorn app.backend.main:app --host "$HOST_ADDRESS" --port "$BACKEND_PORT" &
BACKEND_PID=$!

(
  cd app/frontend
  VITE_API_BASE_URL="http://${HOST_ADDRESS}:${BACKEND_PORT}" npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT"
) &
FRONTEND_PID=$!

echo "Backend PID: $BACKEND_PID"
echo "Frontend PID: $FRONTEND_PID"
echo "Frontend: http://127.0.0.1:${FRONTEND_PORT}"
wait


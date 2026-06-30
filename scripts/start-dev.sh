#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

AGENTCORE_RUNTIME="${AGENTCORE_RUNTIME:-rams_supervisor_runtime}"
AGENTCORE_PORT="${AGENTCORE_PORT:-8080}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

echo "3D-RAMS dev startup"
echo "Repository: $ROOT_DIR"

if ! command -v agentcore >/dev/null 2>&1; then
  echo "agentcore CLI was not found on PATH. Install or activate the AgentCore CLI before running this script."
  exit 1
fi

echo "Installing frontend dependencies"
(
  cd frontend
  if [ -f package-lock.json ]; then
    npm ci
  else
    npm install
  fi
)

if [ "${1:-}" = "--install-only" ]; then
  echo "Install complete. Start the app with: bash scripts/start-dev.sh"
  exit 0
fi

kill_tree() {
  local pid="$1"
  local child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

kill_repo_orphans() {
  local pid
  pgrep -f "$ROOT_DIR/app/rams_supervisor_runtime/.venv/bin/uvicorn main:app" 2>/dev/null | while read -r pid; do
    kill_tree "$pid"
  done
  pgrep -f "$ROOT_DIR/frontend/node_modules/.bin/vite" 2>/dev/null | while read -r pid; do
    kill_tree "$pid"
  done
}

cleanup() {
  trap - INT TERM EXIT
  if [ -n "${AGENTCORE_PID:-}" ]; then
    kill_tree "$AGENTCORE_PID"
  fi
  if [ -n "${FRONTEND_PID:-}" ]; then
    kill_tree "$FRONTEND_PID"
  fi
  kill_repo_orphans
}
trap cleanup INT TERM EXIT

echo "Starting AgentCore runtime on http://127.0.0.1:$AGENTCORE_PORT"
(
  exec agentcore dev \
    --runtime "$AGENTCORE_RUNTIME" \
    --skip-deploy \
    --no-browser \
    --no-traces \
    --logs \
    --port "$AGENTCORE_PORT"
) &
AGENTCORE_PID=$!

echo "Starting frontend on http://0.0.0.0:$FRONTEND_PORT"
(
  cd frontend
  VITE_AGENTCORE_URL=/agentcore/invocations \
    VITE_AGENTCORE_PROXY_TARGET="http://127.0.0.1:$AGENTCORE_PORT" \
    VITE_USE_LOCAL_ASIONE=true \
    npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT"
) &
FRONTEND_PID=$!

echo "AgentCore PID: $AGENTCORE_PID"
echo "Frontend PID: $FRONTEND_PID"
echo "Open http://localhost:$FRONTEND_PORT after AgentCore reports it is listening."
echo "Codespaces should forward ports $AGENTCORE_PORT and $FRONTEND_PORT. Press Ctrl+C to stop both."

while true; do
  if ! kill -0 "$AGENTCORE_PID" 2>/dev/null; then
    echo "AgentCore process exited; stopping frontend."
    exit 1
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo "Frontend process exited; stopping AgentCore."
    exit 1
  fi
  sleep 1
done

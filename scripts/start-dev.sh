#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"

echo "3D-RAMS dev startup"
echo "Repository: $ROOT_DIR"

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating Python virtual environment at $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "Installing backend dependencies"
python -m pip install --disable-pip-version-check -r backend/requirements.txt

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

cleanup() {
  trap - INT TERM EXIT
  if [ -n "${BACKEND_PID:-}" ]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [ -n "${FRONTEND_PID:-}" ]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

echo "Starting backend on http://0.0.0.0:8000"
(
  cd backend
  uvicorn app.main:app --host 0.0.0.0 --port 8000
) &
BACKEND_PID=$!

echo "Starting frontend on http://0.0.0.0:5173"
(
  cd frontend
  npm run dev -- --host 0.0.0.0 --port 5173
) &
FRONTEND_PID=$!

echo "Backend PID: $BACKEND_PID"
echo "Frontend PID: $FRONTEND_PID"
echo "Codespaces will forward ports 8000 and 5173. Press Ctrl+C to stop both."

wait -n "$BACKEND_PID" "$FRONTEND_PID"

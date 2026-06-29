#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

INSTALL=false

for arg in "$@"; do
  case "$arg" in
    --install)
      INSTALL=true
      ;;
    -h|--help)
      cat <<'USAGE'
Usage: bash scripts/check-demo.sh [--install]

Runs the local no-AWS verification stack:
  - backend/script compile check
  - backend unit and API contract tests
  - deterministic demo evaluation
  - frontend production build
  - backend/frontend HTTP runtime smoke test

Options:
  --install  Install backend and frontend dependencies before checking.
USAGE
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Run: bash scripts/check-demo.sh --help" >&2
      exit 2
      ;;
  esac
done

if [ "$INSTALL" = true ]; then
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
fi

echo "Compiling backend, tests, and scripts"
python -m compileall backend/app backend/tests scripts

echo "Running backend unit and API contract tests"
python -m unittest discover -s backend/tests -q

echo "Running deterministic no-AWS demo evaluation"
ENABLE_BEDROCK=false python scripts/evaluate-demo.py

echo "Building frontend"
(
  cd frontend
  if [ ! -d node_modules ]; then
    echo "frontend/node_modules is missing. Run: bash scripts/check-demo.sh --install" >&2
    exit 3
  fi
  npm run build
)

echo "Running backend/frontend HTTP runtime smoke test"
python scripts/smoke-runtime.py

echo "3D-RAMS local verification passed."

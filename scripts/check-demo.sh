#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

INSTALL=false
PYTHON_BIN="${PYTHON_BIN:-python3}"
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-${TMPDIR:-/tmp}/3d-rams-pycache}"

for arg in "$@"; do
  case "$arg" in
    --install)
      INSTALL=true
      ;;
    -h|--help)
      cat <<'USAGE'
Usage: bash scripts/check-demo.sh [--install]

Runs the local no-AWS verification stack:
  - AgentCore package/script compile check
  - AgentCore workflow and invocation tests
  - deterministic demo evaluation
  - frontend production build
  - AgentCore/frontend HTTP runtime smoke test

Options:
  --install  Install AgentCore Python package and frontend dependencies before checking.
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
  echo "Installing AgentCore Python package"
  "$PYTHON_BIN" -m pip install --disable-pip-version-check -e app/rams_agentcore

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

echo "Compiling AgentCore package, tests, and scripts"
"$PYTHON_BIN" -m compileall \
  app/MyAgent \
  app/rams_agentcore/main.py \
  app/rams_agentcore/mcp_client \
  app/rams_agentcore/model \
  app/rams_agentcore/skills \
  app/rams_agentcore/tests \
  app/rams_agentcore/three_d_rams \
  agentverse \
  scripts

echo "Running AgentCore workflow and invocation tests"
"$PYTHON_BIN" -m unittest discover -s app/rams_agentcore/tests -q

echo "Running deterministic no-AWS demo evaluation"
ENABLE_BEDROCK=false "$PYTHON_BIN" scripts/evaluate-demo.py

echo "Building frontend"
(
  cd frontend
  if [ ! -d node_modules ]; then
    echo "frontend/node_modules is missing. Run: bash scripts/check-demo.sh --install" >&2
    exit 3
  fi
  npm run build
)

echo "Running AgentCore/frontend HTTP runtime smoke test"
"$PYTHON_BIN" scripts/smoke-runtime.py

echo "3D-RAMS local verification passed."

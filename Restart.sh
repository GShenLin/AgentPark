#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"
WORKSPACE_ROOT="$(pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"

if [ -z "$PYTHON_BIN" ]; then
  for candidate in "$WORKSPACE_ROOT/AgnetPark_Linux_env/bin/python" "$WORKSPACE_ROOT/.venv/bin/python" python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -m pip --version >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "[ERROR] Could not find a Python interpreter with pip available." >&2
  exit 1
fi

echo "[INFO] Restarting AgentPark..."
"$PYTHON_BIN" scripts/restart_aitools.py --workspace-root "$WORKSPACE_ROOT" --stop-only

if git status --porcelain | grep . >/dev/null 2>&1; then
  echo "[WARN] Working tree has local changes; skipping git pull --rebase."
else
  echo "[INFO] Updating repository with git pull --rebase..."
  git pull --rebase || echo "[WARN] git pull --rebase failed; continuing startup with current workspace."
fi

echo "[INFO] Starting AgentPark through build_and_run.sh..."
AITOOLS_NO_PAUSE=1 exec "$WORKSPACE_ROOT/build_and_run.sh" "$@"

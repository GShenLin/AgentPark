#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

LAUNCH_MODE="cli_web"
CLI_ARGS="chat"
RESTART_EXIT_CODE="43"
PYTHON_BIN="${PYTHON_BIN:-}"
SERVER_PID=""
EXPLICIT_MODE="0"

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

case "${1:-}" in
  server|web)
    EXPLICIT_MODE="1"
    LAUNCH_MODE="server"
    CLI_ARGS=""
    ;;
  cli-only)
    EXPLICIT_MODE="1"
    LAUNCH_MODE="cli_only"
    shift || true
    case "${1:-}" in
      "" )
        CLI_ARGS="chat"
        ;;
      chat|doctor|capabilities|config)
        CLI_ARGS="$*"
        ;;
      *)
        CLI_ARGS="chat $*"
        ;;
    esac
    ;;
  cli)
    EXPLICIT_MODE="1"
    LAUNCH_MODE="cli_web"
    shift || true
    case "${1:-}" in
      "" )
        CLI_ARGS="chat"
        ;;
      chat|doctor|capabilities|config)
        CLI_ARGS="$*"
        ;;
      *)
        CLI_ARGS="chat $*"
        ;;
    esac
    ;;
  chat)
    EXPLICIT_MODE="1"
    LAUNCH_MODE="cli_web"
    shift || true
    CLI_ARGS="chat ${*:-}"
    ;;
esac

if [ "$EXPLICIT_MODE" = "0" ] && { [ ! -t 0 ] || [ ! -t 1 ]; }; then
  echo "[INFO] Non-interactive terminal detected; starting server only. Use './build_and_run.sh cli' from an interactive terminal for companion chat."
  LAUNCH_MODE="server"
  CLI_ARGS=""
fi

select_python() {
  if [ -n "$PYTHON_BIN" ]; then
    return 0
  fi
  for candidate in "./AgnetPark_Linux_env/bin/python" "./.venv/bin/python" "python3" "python"; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -m pip --version >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      return 0
    fi
  done
  return 1
}

stop_background_server() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" >/dev/null 2>&1 || true
  fi
}

select_python || {
  echo "[ERROR] Could not find a Python interpreter with pip available." >&2
  exit 1
}

echo "[INFO] Using Python: $PYTHON_BIN"
if ! command -v rg >/dev/null 2>&1; then
  echo "[WARN] ripgrep (rg) not found in PATH. Shell rg commands will be unavailable."
fi

echo "[INFO] Installing/updating WebUI dependencies..."
cd webui
npm install

echo "[INFO] Compiling WebUI..."
npm run build
cd ..

echo "[INFO] Installing/updating Python dependencies..."
"$PYTHON_BIN" -m pip install -e .

if [ "$LAUNCH_MODE" = "cli_web" ]; then
  echo "[INFO] Stopping existing AgentPark processes for this workspace..."
  "$PYTHON_BIN" scripts/restart_aitools.py --workspace-root "$(pwd)" --stop-only

  mkdir -p .runtime
  echo "[INFO] Starting AgentPark web server in background."
  "$PYTHON_BIN" -m src.fast_api --workspace-root "$(pwd)" > .runtime/aitools-server.log 2> .runtime/aitools-server.err.log &
  SERVER_PID="$!"
  trap stop_background_server EXIT INT TERM
fi

if [ "$LAUNCH_MODE" = "cli_web" ] || [ "$LAUNCH_MODE" = "cli_only" ]; then
  echo "[INFO] Starting AgentPark CLI: python -m src.cli $CLI_ARGS"
  set +e
  "$PYTHON_BIN" -m src.cli $CLI_ARGS
  code="$?"
  set -e
  if [ "$code" = "$RESTART_EXIT_CODE" ]; then
    exit 0
  fi
  exit "$code"
fi

echo "[INFO] Starting AgentPark server..."
exec "$PYTHON_BIN" -m src.fast_api --workspace-root "$(pwd)"

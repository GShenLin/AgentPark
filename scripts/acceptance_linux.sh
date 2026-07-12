#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"
MODE="full"
SKIP_FRONTEND_BUILD="${AGENTPARK_ACCEPTANCE_SKIP_FRONTEND_BUILD:-0}"
SKIP_PROVIDER_FACTORY="${AGENTPARK_ACCEPTANCE_SKIP_PROVIDER_FACTORY:-0}"

usage() {
  cat <<'USAGE'
Usage: scripts/acceptance_linux.sh [--quick|--full] [--skip-frontend-build] [--skip-provider-factory]

Runs local Linux merge acceptance checks without calling real model/provider APIs.

Modes:
  --quick  config/provider contracts + focused core tests
  --full   quick checks + frontend build + wider skills/MCP/plugin/tool/runtime tests

Environment:
  PYTHON_BIN                               Python interpreter override
  AGENTPARK_ACCEPTANCE_SKIP_FRONTEND_BUILD Set to 1 to skip npm run build
  AGENTPARK_ACCEPTANCE_SKIP_PROVIDER_FACTORY Set to 1 to skip create_agent checks
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --quick)
      MODE="quick"
      ;;
    --full)
      MODE="full"
      ;;
    --skip-frontend-build)
      SKIP_FRONTEND_BUILD="1"
      ;;
    --skip-provider-factory)
      SKIP_PROVIDER_FACTORY="1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

select_python() {
  if [ -n "$PYTHON_BIN" ]; then
    return 0
  fi
  for candidate in "$ROOT_DIR/AgentPark_Linux_env/bin/python" "$ROOT_DIR/.venv/bin/python" python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -m pip --version >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      return 0
    fi
  done
  return 1
}

run_step() {
  name="$1"
  shift
  echo
  echo "==> $name"
  "$@"
}

run_pytest() {
  "$PYTHON_BIN" -m pytest "$@"
}

cd "$ROOT_DIR"

select_python || {
  echo "[ERROR] Could not find a Python interpreter with pip available." >&2
  exit 1
}

echo "[INFO] AgentPark Linux acceptance mode: $MODE"
echo "[INFO] Python: $PYTHON_BIN"

if git diff --name-only --diff-filter=U | grep . >/dev/null 2>&1; then
  echo "[ERROR] Unresolved git conflicts are present:" >&2
  git diff --name-only --diff-filter=U >&2
  exit 1
fi

if git grep -n -E '^(<<<<<<<|=======|>>>>>>>)' -- ':!webui/dist/**' ':!*.lock' >/tmp/agentpark_acceptance_conflicts.$$ 2>/dev/null; then
  echo "[ERROR] Conflict markers found:" >&2
  cat /tmp/agentpark_acceptance_conflicts.$$ >&2
  rm -f /tmp/agentpark_acceptance_conflicts.$$
  exit 1
fi
rm -f /tmp/agentpark_acceptance_conflicts.$$

PROVIDER_FACTORY_ARG=""
if [ "$SKIP_PROVIDER_FACTORY" = "1" ]; then
  PROVIDER_FACTORY_ARG="--skip-provider-factory"
fi

run_step "local config and provider contract checks" "$PYTHON_BIN" scripts/acceptance_linux.py $PROVIDER_FACTORY_ARG
run_step "backend import smoke" "$PYTHON_BIN" -c "import src.fast_api; import src.config_loader; import src.providers; print('backend imports OK')"

if [ "$SKIP_FRONTEND_BUILD" != "1" ] && [ "$MODE" = "full" ]; then
  run_step "WebUI build" npm --prefix webui run build
else
  echo
  echo "==> WebUI build"
  echo "[SKIP] skipped by mode or AGENTPARK_ACCEPTANCE_SKIP_FRONTEND_BUILD"
fi

run_step "core contract tests" run_pytest \
  tests/test_config_loader.py \
  tests/test_provider_factory.py \
  tests/test_agent_node_config.py \
  tests/test_agent_node_stream.py \
  tests/test_openai_responses_runtime.py \
  tests/test_responses_websocket_transport.py

if [ "$MODE" = "full" ]; then
  run_step "extension contract tests" run_pytest \
    tests/test_agent_mcp_loader.py \
    tests/test_agent_plugin_loader.py \
    tests/test_agent_tool_loader.py \
    tests/test_agent_skill_loader.py \
    tests/test_skill_resource_tools.py \
    tests/test_skill_script_tools.py \
    tests/test_companion_mcp.py \
    tests/test_prompt_library.py \
    tests/test_node_memory_store.py \
    tests/test_mobile_api.py \
    tests/test_tool_stats_store.py \
    tests/test_provider_tool_call_protocol.py
fi

echo
echo "[OK] AgentPark Linux acceptance passed"

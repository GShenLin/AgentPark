from __future__ import annotations

import json
import uuid

from src.file_transaction import atomic_write_text
from src.harness.contracts import HarnessContext, HarnessResult
from src.harness.install_manager import command_argv
from src.harness.process import run_process
from src.harness.reasoning_config import reasoning_options
from .cli_session import cli_session, string_field, write_json
from .openclaw_progress import OpenClawProgress, install_progress_plugin


def parse_result(output: str) -> str:
    result = json.loads(output)
    if not isinstance(result, dict) or not isinstance(result.get("payloads"), list):
        raise ValueError("OpenClaw local JSON result requires a payloads array.")
    if result.get("ok") is False:
        raise RuntimeError(f"OpenClaw turn failed: {result.get('error')}")
    payloads = result["payloads"]
    if not payloads:
        raise RuntimeError("OpenClaw returned no response payloads.")
    return "\n".join(string_field(payload, "text") for payload in payloads)


class Adapter:
    def run(self, text: str, context: HarnessContext) -> HarnessResult:
        with cli_session("openclaw", context) as (request, lease, env, events):
            env["OPENCLAW_STATE_DIR"] = str(request.state_dir)
            config_path = request.state_dir / "openclaw.json"
            env["OPENCLAW_CONFIG_PATH"] = str(config_path)
            efforts = reasoning_options(request.binding.request_config())
            model = {"id": request.binding.model_id, "name": request.binding.model_id,
                     "reasoning": bool(efforts), "compat": {"supportedReasoningEfforts": efforts}}
            write_json(config_path, {
                "plugins": install_progress_plugin(request.state_dir),
                "models": {"mode": "replace", "providers": {"agentpark": {
                    "baseUrl": lease.base_url, "apiKey": "${AGENTPARK_HARNESS_TOKEN}",
                    "api": "openai-responses", "models": [model],
                }}},
                "agents": {"defaults": {"workspace": request.cwd,
                                        "model": {"primary": f"agentpark/{request.binding.model_id}"}}},
            })
            # The local CLI persists its own conversation under the isolated state directory.
            session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(request.state_dir)))
            prompt_path = request.state_dir / "prompt.txt"
            prompt = f"{request.instruction}\n\n{text}" if request.instruction else text
            atomic_write_text(str(prompt_path), prompt, encoding="utf-8")
            progress = OpenClawProgress(events)
            thinking_level = "off" if request.reasoning_effort == "none" else request.reasoning_effort
            thinking_args = ["--thinking", thinking_level] if thinking_level else []
            try:
                output = run_process(
                    [*command_argv("openclaw"), "agent", "--local", "--json", "--session-id", session_id,
                     "--message-file", str(prompt_path), "--timeout", str(int(request.timeout)), *thinking_args],
                    cwd=request.cwd, env=env, timeout=request.timeout, cancel_source=request.cancel_source,
                    on_stderr_line=progress.handle_stderr)
            finally:
                prompt_path.unlink()
            progress.finish()
            return events.done(parse_result(output))

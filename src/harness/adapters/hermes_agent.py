from __future__ import annotations

import json
from pathlib import Path

from src.harness.contracts import HarnessContext, HarnessResult
from src.harness.install_manager import command_argv
from src.harness.process import run_process
from .cli_session import cli_session, read_event, string_field, write_json


class HermesEvents:
    def __init__(self, events):
        self.events = events
        self.result: str | None = None

    def handle(self, line: str) -> None:
        event = read_event(line)
        if self.result is not None:
            raise ValueError("Hermes emitted an event after its result.")
        kind = event["type"]
        if kind == "text":
            self.events.text_delta(string_field(event, "text"))
        elif kind == "thinking":
            self.events.thinking_delta(string_field(event, "text"))
        elif kind in {"tool_start", "tool_end"}:
            self.events.tool(call_id=string_field(event, "id"), name=string_field(event, "name"),
                             phase="running" if kind == "tool_start" else "completed",
                             value=event["arguments"] if kind == "tool_start" else event["output"],
                             error=event.get("error") is True)
        elif kind == "result":
            if self.events.started:
                raise ValueError("Hermes returned with unfinished tool calls.")
            self.result = string_field(event, "text")
        elif kind == "error":
            raise RuntimeError(string_field(event, "message"))
        else:
            raise ValueError(f"Unknown Hermes runner event: {kind}")


class Adapter:
    def run(self, text: str, context: HarnessContext) -> HarnessResult:
        with cli_session("hermes_agent", context) as (request, lease, env, events):
            home = request.state_dir / "home"
            home.mkdir(exist_ok=True)
            # Explicit home/config prevent personal profiles and credentials from selecting a different route.
            for name in ("HERMES_PROFILE", "HERMES_CONFIG", "HERMES_ENV", "PYTHONPATH", "PYTHONHOME"):
                env.pop(name, None)
            env.update(HERMES_HOME=str(home), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            write_json(home / "config.yaml", {
                "model": {"provider": "custom:agentpark", "default": request.binding.model_id},
                "providers": {"agentpark": {"name": "agentpark", "base_url": lease.base_url,
                    "api_mode": "codex_responses", "key_env": "AGENTPARK_HARNESS_TOKEN",
                    "default_model": request.binding.model_id, "models": [request.binding.model_id],
                    "discover_models": False}},
                "terminal": {"backend": "local", "cwd": request.cwd},
                # AgentPark owns node names. Attaching native storage must not start
                # Hermes's separate background model request for a CLI session title.
                "auxiliary": {"title_generation": {"enabled": False}},
            })
            parser = HermesEvents(events)
            runner = Path(__file__).with_name("hermes_runner.py")
            payload = {"text": text, "model": request.binding.model_id, "base_url": lease.base_url,
                       "instruction": request.instruction, "state_dir": str(request.state_dir),
                       "timeout": request.timeout, "reasoning_effort": request.reasoning_effort}
            run_process([*command_argv("hermes_agent"), str(runner)], cwd=request.cwd, env=env,
                        stdin=json.dumps(payload, ensure_ascii=False), timeout=request.timeout,
                        cancel_source=request.cancel_source, on_line=parser.handle)
            if parser.result is None:
                raise RuntimeError("Hermes exited without a result.")
            return events.done(parser.result)

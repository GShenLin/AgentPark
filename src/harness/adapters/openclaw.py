from __future__ import annotations

from src.harness.config import load_cli_request
from src.harness.contracts import HarnessContext, HarnessResult
from src.harness.execution import execution_session
from src.harness.install_manager import command_argv
from src.harness.openclaw_session import OpenClawSessions
from .cli_session import string_field
from .openclaw_progress import OpenClawProgress


def parse_result(result: dict) -> str:
    if not isinstance(result, dict) or not isinstance(result.get("payloads"), list):
        raise ValueError("OpenClaw result requires a payloads array.")
    if result.get("ok") is False:
        raise RuntimeError(f"OpenClaw turn failed: {result.get('error')}")
    payloads = result["payloads"]
    if not payloads:
        raise RuntimeError("OpenClaw returned no response payloads.")
    return "\n".join(string_field(payload, "text") for payload in payloads)


class Adapter:
    def __init__(self):
        self.state_dir = None

    def prepare(self, context):
        request = load_cli_request("openclaw", context)
        request.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = request.state_dir
        OpenClawSessions.instance().run(request, command_argv("openclaw"), None, None)

    def is_alive(self):
        return self.state_dir is not None and OpenClawSessions.instance().is_alive(self.state_dir)

    def close(self):
        if self.state_dir is not None:
            OpenClawSessions.instance().close_under(self.state_dir)
            self.state_dir = None

    def run(self, text: str, context: HarnessContext) -> HarnessResult:
        request = load_cli_request("openclaw", context)
        self.state_dir = request.state_dir
        with execution_session("openclaw", request.binding.provider_id, request, context) as events:
            progress = OpenClawProgress(events)
            prompt = f"{request.instruction}\n\n{text}" if request.instruction else text
            result = OpenClawSessions.instance().run(request, command_argv("openclaw"), prompt, progress.handle)
            progress.finish()
            return events.done(parse_result(result))

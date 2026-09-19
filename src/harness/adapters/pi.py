from __future__ import annotations

from src.harness.contracts import HarnessContext, HarnessResult
from src.harness.install_manager import command_argv
from src.harness.process import run_process
from .cli_session import cli_session, read_event, string_field, write_json


class PiEvents:
    def __init__(self, events):
        self.events = events
        self.final_text: str | None = None

    def handle(self, line: str) -> None:
        event = read_event(line)
        kind = event["type"]
        if kind == "message_update":
            update = event.get("assistantMessageEvent")
            if not isinstance(update, dict):
                raise ValueError("Pi message_update requires assistantMessageEvent.")
            if update.get("type") == "text_delta":
                self.events.text_delta(string_field(update, "delta"))
            elif update.get("type") == "thinking_delta":
                self.events.thinking_delta(string_field(update, "delta"))
        elif kind == "message_end":
            message = event.get("message")
            if not isinstance(message, dict):
                raise ValueError("Pi message_end requires a message object.")
            if message.get("role") == "assistant":
                if message.get("stopReason") in {"error", "aborted"}:
                    raise RuntimeError(f"Pi failed: {message.get('errorMessage', message['stopReason'])}")
                content = message.get("content")
                if not isinstance(content, list):
                    raise ValueError("Pi assistant content must be an array.")
                self.final_text = "".join(string_field(block, "text") for block in content
                                          if isinstance(block, dict) and block.get("type") == "text")
        elif kind in {"tool_execution_start", "tool_execution_end"}:
            self.events.tool(call_id=string_field(event, "toolCallId"), name=string_field(event, "toolName"),
                             phase="running" if kind.endswith("start") else "completed",
                             value=event.get("args") if kind.endswith("start") else event.get("result"),
                             error=event.get("isError") is True)
        elif kind == "extension_error":
            raise RuntimeError(f"Pi extension failed: {event}")


class Adapter:
    def run(self, text: str, context: HarnessContext) -> HarnessResult:
        with cli_session("pi", context) as (request, lease, env, events):
            home = request.state_dir / "agent"
            home.mkdir(exist_ok=True)
            env["PI_CODING_AGENT_DIR"] = str(home)
            write_json(home / "models.json", {"providers": {"agentpark": {
                "baseUrl": lease.base_url, "api": "openai-responses", "apiKey": "AGENTPARK_HARNESS_TOKEN",
                "models": [{"id": request.binding.model_id, "name": request.binding.model_id}],
            }}})
            argv = [*command_argv("pi"), "--print", "--mode", "json", "--provider", "agentpark",
                    "--model", request.binding.model_id, "--session", str(request.state_dir / "session.jsonl"),
                    "--no-extensions"]
            if request.instruction:
                argv += ["--append-system-prompt", request.instruction]
            parser = PiEvents(events)
            run_process(argv, cwd=request.cwd, env=env, stdin=text, timeout=request.timeout,
                        cancel_source=request.cancel_source, on_line=parser.handle)
            if parser.final_text is None:
                raise RuntimeError("Pi exited without an assistant message.")
            return events.done(parser.final_text)

from __future__ import annotations

import json
import uuid
from src.harness.jsonl_process import JsonlProcess
from .resident import ResidentCliAdapter
from .cli_session import read_event, string_field, write_json


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



class Adapter(ResidentCliAdapter):
    harness_id = "pi"

    def open(self, request, argv, env, options, events):
        home = request.state_dir / "agent"
        home.mkdir(exist_ok=True)
        env["PI_CODING_AGENT_DIR"] = str(home)
        write_json(home / "models.json", {"providers": {"agentpark": {
            "baseUrl": self.lease.base_url, "api": "openai-responses", "apiKey": "AGENTPARK_HARNESS_TOKEN",
            "models": [{"id": request.binding.model_id, "name": request.binding.model_id}],
        }}})
        argv = [*argv, "--mode", "rpc", "--provider", "agentpark",
                "--model", request.binding.model_id, "--session", str(request.state_dir / "session.jsonl"),
                "--no-extensions"]
        if request.instruction:
            argv += ["--append-system-prompt", request.instruction]
        self.client = JsonlProcess(argv, cwd=request.cwd, env=env,
            timeout=request.timeout, cancel_source=request.cancel_source)
        self.client.send({"id": "initialize", "type": "get_state"})
        self._response(self.client.receive(), "initialize", "get_state")

    @staticmethod
    def _response(frame, request_id, command):
        if (frame.get("type") != "response" or frame.get("id") != request_id
                or frame.get("command") != command or frame.get("success") is not True):
            raise RuntimeError(f"Pi {command} failed: {frame}")

    def turn(self, text, request, events):
        parser = PiEvents(events)
        request_id = uuid.uuid4().hex
        self.client.send({"id": request_id, "type": "prompt", "message": text})
        accepted = settled = False
        while not (accepted and settled):
            frame = self.client.receive()
            if frame.get("type") == "response":
                self._response(frame, request_id, "prompt")
                if frame.get("data", {}).get("disposition") != "started":
                    raise RuntimeError(f"Pi did not start this turn: {frame}")
                accepted = True
            elif frame.get("type") == "agent_settled":
                if frame.get("aborted") is not False:
                    raise RuntimeError("Pi turn was aborted.")
                settled = True
            else:
                parser.handle(json.dumps(frame, ensure_ascii=False))
        if parser.final_text is None or events.started:
            raise RuntimeError("Pi settled without a completed assistant result.")
        return events.done(parser.final_text)

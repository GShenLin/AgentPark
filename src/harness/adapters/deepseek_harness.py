from __future__ import annotations

import json

from src.harness.acp_client import AcpClient
from .cli_session import string_field, write_json
from .deepseek_config import configure_runtime


class DeepSeekEvents:
    def __init__(self, events):
        self.events = events
        self.session_id = ""
        self.pending: list[dict] = []

    def bind(self, session_id: str) -> None:
        self.session_id = session_id
        for params in self.pending:
            self.handle(params)
        self.pending.clear()

    def handle(self, params: dict) -> None:
        if not self.session_id:
            if len(self.pending) >= 100:
                raise ValueError("Too many ACP updates before session creation completed.")
            self.pending.append(params)
            return
        if params.get("sessionId") != self.session_id:
            raise ValueError("ACP update belongs to a different session.")
        event = params.get("update")
        if not isinstance(event, dict) or not isinstance(event.get("sessionUpdate"), str):
            raise ValueError("ACP session/update requires a typed update object.")
        kind = event["sessionUpdate"]
        if kind in {"agent_message_chunk", "agent_thought_chunk"}:
            content = event.get("content")
            if not isinstance(content, dict) or content.get("type") != "text":
                raise ValueError("DeepSeek Harness currently supports text response blocks only.")
            if kind == "agent_message_chunk":
                self.events.text_delta(string_field(content, "text"))
            else:
                self.events.thinking_delta(string_field(content, "text"))
        elif kind == "tool_call":
            self.events.tool(call_id=string_field(event, "toolCallId"), name=string_field(event, "title"),
                             phase="running", value=event.get("rawInput"))
        elif kind == "tool_call_update" and event.get("status") in {"completed", "failed"}:
            self.events.tool(call_id=string_field(event, "toolCallId"), name="", phase="completed",
                             value=event.get("content"), error=event["status"] == "failed")


from .resident import ResidentCliAdapter


class Adapter(ResidentCliAdapter):
    harness_id = "deepseek_harness"

    def open(self, request, argv, env, options, events):
        home = request.state_dir / "home"
        home.mkdir(exist_ok=True)
        env["DSH_HOME"] = str(home)
        overlay = configure_runtime(home, request.binding.model_id, self.lease.base_url)
        parser = DeepSeekEvents(events)
        self.client = client = AcpClient([*argv, "--profile", "acp", "--patch", str(overlay)],
                           cwd=request.cwd, env=env, timeout=request.timeout,
                           cancel_source=request.cancel_source, on_update=parser.handle)
        state_path = request.state_dir / "session.json"
        capabilities = client.request("initialize", {"protocolVersion": 1, "clientCapabilities": {},
                                                     "clientInfo": {"name": "agentpark", "version": "1"}})
        if capabilities.get("protocolVersion") != 1:
            raise ValueError("DeepSeek Harness requires ACP protocol version 1.")
        params = {"cwd": request.cwd, "mcpServers": []}
        if state_path.exists():
            parser.session_id = string_field(json.loads(state_path.read_text(encoding="utf-8")), "session_id")
            client.request("session/resume", {**params, "sessionId": parser.session_id})
        else:
            session = client.request("session/new", params)
            parser.bind(string_field(session, "sessionId"))
        if not parser.session_id:
            raise ValueError("DeepSeek Harness returned an empty session id.")
        write_json(state_path, {"session_id": parser.session_id})
        client.request("session/set_config_option", {"sessionId": parser.session_id, "configId": "model",
                       "value": json.dumps(["agentpark", request.binding.model_id], separators=(",", ":"))})
        self.session_id = parser.session_id

    def turn(self, text, request, events):
        parser = DeepSeekEvents(events)
        parser.bind(self.session_id)
        client = self.client
        client.on_update = parser.handle
        prompt = f"{request.instruction}\n\n{text}" if request.instruction else text
        result = client.request("session/prompt", {"sessionId": self.session_id,
                                                  "prompt": [{"type": "text", "text": prompt}]})
        if result.get("stopReason") != "end_turn":
            raise RuntimeError(f"DeepSeek Harness turn ended: {result.get('stopReason')}")
        return events.done(events.text)

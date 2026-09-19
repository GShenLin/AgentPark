from __future__ import annotations

import json
from pathlib import Path

from src.harness.acp_client import AcpClient
from src.harness.contracts import HarnessContext, HarnessResult
from src.harness.install_manager import command_argv
from .cli_session import cli_session, string_field, write_json


def resume_models(settings_path: Path, model: str) -> list[dict[str, str]]:
    """ACP replays historical model selections before set_config_option runs.

    Keep their descriptors resolvable; every descriptor still uses the current
    gateway lease, whose binding pins all inference to the selected Provider/Model.
    settings.yaml is an adapter-owned JSON document (also valid YAML).
    """
    ids = []
    if settings_path.exists():
        value = json.loads(settings_path.read_text(encoding="utf-8"))
        for key in ("llm-pi-ai", "providers", "agentpark", "models"):
            if not isinstance(value, dict) or key not in value:
                raise ValueError("Invalid DeepSeek Harness model configuration for session resume.")
            value = value[key]
        if not isinstance(value, list) or not value:
            raise ValueError("DeepSeek Harness models must be a nonempty array.")
        for item in value:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                raise ValueError("DeepSeek Harness model requires a nonempty id.")
            if item["id"] not in ids:
                ids.append(item["id"])
    if model not in ids:
        ids.append(model)
    return [{"id": item} for item in ids]


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


class Adapter:
    def run(self, text: str, context: HarnessContext) -> HarnessResult:
        with cli_session("deepseek_harness", context) as (request, lease, env, events):
            home = request.state_dir / "home"
            home.mkdir(exist_ok=True)
            env["DSH_HOME"] = str(home)
            settings_path = home / "settings.yaml"
            models = resume_models(settings_path, request.binding.model_id)
            write_json(settings_path, {
                "llm-pi-ai": {"providers": {"agentpark": {
                    "apiKeyEnv": "AGENTPARK_HARNESS_TOKEN", "api": "openai-responses",
                    "baseURL": lease.base_url, "models": models,
                }}},
                "agent-default-model": {"provider": "agentpark", "model": request.binding.model_id},
            })
            parser = DeepSeekEvents(events)
            client = AcpClient([*command_argv("deepseek_harness"), "--profile", "acp"],
                               cwd=request.cwd, env=env, timeout=request.timeout,
                               cancel_source=request.cancel_source, on_update=parser.handle)
            state_path = request.state_dir / "session.json"
            try:
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
                prompt = f"{request.instruction}\n\n{text}" if request.instruction else text
                result = client.request("session/prompt", {"sessionId": parser.session_id,
                                                          "prompt": [{"type": "text", "text": prompt}]})
                if result.get("stopReason") != "end_turn":
                    raise RuntimeError(f"DeepSeek Harness turn ended: {result.get('stopReason')}")
                client.request("session/close", {"sessionId": parser.session_id})
                return events.done(events.text)
            finally:
                client.close()

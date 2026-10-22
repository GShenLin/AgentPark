"""Own an official OpenCode ACP child and resume node-scoped native sessions."""
from __future__ import annotations

import json

from src.harness.acp_client import AcpClient
from src.harness.acp_events import AcpEvents
from .cli_session import string_field, write_json
from .opencode_config import agent_mode, runtime_config, RUNTIME_MODEL, select_option


from .resident import ResidentCliAdapter


class Adapter(ResidentCliAdapter):
    harness_id = "opencode"

    def options(self, context):
        return agent_mode(context)

    def open(self, request, argv, env, options, events):
        parser = AcpEvents(events)
        state_path = request.state_dir / "session.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or state.get("cwd") != request.cwd:
                raise ValueError("OpenCode session working directory changed. Restore it or clear this node's memory before starting in a different directory.")
            parser.bind(string_field(state, "session_id"))
        env.update(OPENCODE_DB=str(request.state_dir / "sessions.db"),
                   OPENCODE_CONFIG_CONTENT=json.dumps(runtime_config(self.lease.base_url)))
        self.client = client = AcpClient([*argv, "acp"], cwd=request.cwd, env=env,
            timeout=request.timeout, cancel_source=request.cancel_source, on_update=parser.handle)
        initialized = client.request("initialize", {"protocolVersion": 1, "clientCapabilities": {},
            "clientInfo": {"name": "agentpark", "version": "1"}})
        agent = initialized.get("agentCapabilities")
        sessions = agent.get("sessionCapabilities") if isinstance(agent, dict) else None
        if initialized.get("protocolVersion") != 1 or not isinstance(sessions, dict) or any(
                key not in sessions for key in ("resume", "close")):
            raise ValueError("OpenCode requires ACP v1 with session resume and close. Update it in Settings → Harness.")
        params = {"cwd": request.cwd, "mcpServers": []}
        if parser.session_id:
            control = client.request("session/resume", {**params, "sessionId": parser.session_id})
        else:
            control = client.request("session/new", params)
            parser.bind(string_field(control, "sessionId"))
            write_json(state_path, {"session_id": parser.session_id, "cwd": request.cwd})
        # Select the agent first: model controls/variants can depend on it.
        for key, value in (("mode", options), ("model", RUNTIME_MODEL)):
            control = client.request("session/set_config_option", {"sessionId": parser.session_id,
                "configId": key, "value": select_option(control, key, value)})
        self.session_id = parser.session_id

    def turn(self, text, request, events):
        parser = AcpEvents(events)
        parser.bind(self.session_id)
        client = self.client
        client.on_update = parser.handle
        prompt = f"{request.instruction}\n\n{text}" if request.instruction else text
        result = client.request("session/prompt", {"sessionId": self.session_id,
            "prompt": [{"type": "text", "text": prompt}]})
        return parser.finish(result)

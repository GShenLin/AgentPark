"""Own an official OpenCode ACP child and resume node-scoped native sessions."""
from __future__ import annotations

import json
import os

from src.harness.acp_client import AcpClient
from src.harness.acp_events import AcpEvents
from src.harness.contracts import HarnessContext, HarnessResult
from src.harness.execution import execution_session
from src.harness.install_manager import command_argv
from .cli_session import string_field, write_json
from .opencode_config import load_request, select_option


class Adapter:
    def run(self, text: str, context: HarnessContext) -> HarnessResult:
        request = load_request(context)
        with execution_session("opencode", request.model.split("/", 1)[0], request, context) as events:
            parser = AcpEvents(events)
            state_path = request.state_dir / "session.json"
            if state_path.exists():
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if not isinstance(state, dict) or state.get("cwd") != request.cwd:
                    raise ValueError("OpenCode session working directory changed. Restore it or clear this node's memory before starting in a different directory.")
                parser.bind(string_field(state, "session_id"))
            # Keep native credentials/config in their documented user locations;
            # isolate conversation data so node memory reset owns its entire DB.
            env = {**os.environ, "OPENCODE_DB": str(request.state_dir / "sessions.db")}
            client = AcpClient([*command_argv("opencode"), "acp"], cwd=request.cwd, env=env,
                timeout=request.timeout, cancel_source=request.cancel_source, on_update=parser.handle)
            try:
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
                for key, value in (("mode", request.mode), ("model", request.model)):
                    control = client.request("session/set_config_option", {"sessionId": parser.session_id,
                        "configId": key, "value": select_option(control, key, value)})
                if request.effort:
                    client.request("session/set_config_option", {"sessionId": parser.session_id,
                        "configId": "effort", "value": select_option(control, "effort", request.effort)})
                prompt = f"{request.instruction}\n\n{text}" if request.instruction else text
                result = client.request("session/prompt", {"sessionId": parser.session_id,
                    "prompt": [{"type": "text", "text": prompt}]})
                client.request("session/close", {"sessionId": parser.session_id})
                return parser.finish(result)
            finally:
                client.close()

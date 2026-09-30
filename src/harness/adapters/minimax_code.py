"""MiniMax Code ACP lifecycle; Provider credentials remain in AgentPark's gateway."""
from __future__ import annotations

import json

from src.harness.acp_client import AcpClient
from src.harness.contracts import HarnessContext, HarnessResult
from src.harness.install_manager import command_argv
from .cli_session import cli_session, string_field, write_json
from .minimax_config import configure_home, model_selection, permission_selection
from .minimax_events import MiniMaxEvents


class Adapter:
    def run(self, text: str, context: HarnessContext) -> HarnessResult:
        with cli_session("minimax_code", context) as (request, lease, env, events):
            configure_home(request, lease, env)
            parser = MiniMaxEvents(events)
            state_path = request.state_dir / "session.json"
            if state_path.exists():
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if not isinstance(state, dict):
                    raise ValueError("MiniMax Code session state must be an object.")
                parser.bind(string_field(state, "session_id"))
            client = AcpClient([*command_argv("minimax_code"), "acp"], cwd=request.cwd, env=env,
                               timeout=request.timeout, cancel_source=request.cancel_source, on_update=parser.handle)
            try:
                capabilities = client.request("initialize", {"protocolVersion": 1, "clientCapabilities": {},
                                                             "clientInfo": {"name": "agentpark", "version": "1"}})
                if capabilities.get("protocolVersion") != 1:
                    raise ValueError("MiniMax Code requires ACP protocol version 1.")
                agent = capabilities.get("agentCapabilities", {})
                sessions = agent.get("sessionCapabilities", {}) if isinstance(agent, dict) else {}
                if not isinstance(sessions, dict) or any(key not in sessions for key in ("resume", "close")):
                    raise ValueError("MiniMax Code requires ACP session resume and close capabilities.")
                params = {"cwd": request.cwd, "mcpServers": []}
                if parser.session_id:
                    control = client.request("session/resume", {**params, "sessionId": parser.session_id})
                else:
                    control = client.request("session/new", params)
                    parser.bind(string_field(control, "sessionId"))
                    write_json(state_path, {"session_id": parser.session_id})
                client.request("session/set_config_option", {"sessionId": parser.session_id,
                               "configId": "permissionMode", "value": permission_selection(control, request.permission_mode)})
                client.request("session/set_config_option", {"sessionId": parser.session_id, "configId": "model",
                               "value": model_selection(control, request.binding.model_id)})
                if request.reasoning_effort:
                    client.request("session/set_config_option", {"sessionId": parser.session_id,
                                   "configId": "thinkingEffort", "value": request.reasoning_effort})
                prompt = f"{request.instruction}\n\n{text}" if request.instruction else text
                result = client.request("session/prompt", {"sessionId": parser.session_id,
                                                          "prompt": [{"type": "text", "text": prompt}]})
                client.request("session/close", {"sessionId": parser.session_id})
                return parser.finish(result)
            finally:
                client.close()

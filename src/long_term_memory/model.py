from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path

from src.agent_profile_inference import resolve_agent_profile_inference
from src.providers.agent_invocation import send_agent
from src.providers.agent_runtime_context import AgentRuntimeContext, bind_agent_runtime_context
from .contracts import encode
from .privacy import redact


class ProfileMemoryModel:
    """Use AgentProfile inference settings, without node tools or recursive memory."""

    def __init__(self, extract_profile_id: str, consolidation_profile_id: str, *, graph_id: str = "", node_id: str = ""):
        self.profiles = {"extract": extract_profile_id, "consolidate": consolidation_profile_id,
                         "answer": consolidation_profile_id}
        self.graph_id, self.node_id = graph_id, node_id

    def complete(self, phase: str, instructions: str, payload: dict) -> str:
        profile = resolve_agent_profile_inference(self.profiles[phase])
        # BaseAgent creates a memory handle even when persistence is disabled.
        # Isolating that handle prevents background output from entering source history.
        with TemporaryDirectory(prefix="agentpark-memory-") as folder:
            agent = profile.create_agent(str(Path(folder) / "scratch.md"), instructions)
            secrets = tuple(str(agent.config.get(key) or "") for key in ("apiKey", "api_key", "token"))
            bind_agent_runtime_context(agent, AgentRuntimeContext(
                responses_instruction=profile.instructions(instructions), graph_id=self.graph_id, node_id=self.node_id,
                task_id=f"memory:{phase}", node_type_id="node_memory",
            ))
            agent.Message("user", redact(encode(payload), secrets), persist=False)
            response = send_agent(agent)
            if not isinstance(response, str):
                raise TypeError("memory provider must return a text response")
            return redact(response, secrets)

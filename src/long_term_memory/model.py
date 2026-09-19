from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path

from src.providers import create_agent
from src.providers.agent_runtime_context import AgentRuntimeContext, bind_agent_runtime_context
from .contracts import encode
from .privacy import redact


class ProviderMemoryModel:
    """Use AgentPark's configured provider transport, without node tools or recursive memory."""

    def __init__(self, extract_provider: str, consolidation_provider: str, *, graph_id: str = "", node_id: str = ""):
        if not extract_provider or not consolidation_provider:
            raise ValueError("both memory model providers must be configured")
        self.providers = {"extract": extract_provider, "consolidate": consolidation_provider, "answer": consolidation_provider}
        self.graph_id, self.node_id = graph_id, node_id

    def complete(self, phase: str, instructions: str, payload: dict) -> str:
        # BaseAgent creates a memory handle even when persistence is disabled.
        # Isolating that handle prevents background output from entering source history.
        with TemporaryDirectory(prefix="agentpark-memory-") as folder:
            agent = create_agent(self.providers[phase], memory_file_path=str(Path(folder) / "scratch.md"),
                                 system_prompt=instructions, internal_memory_enabled=False)
            secrets = tuple(str(agent.config.get(key) or "") for key in ("apiKey", "api_key", "token"))
            bind_agent_runtime_context(agent, AgentRuntimeContext(
                responses_instruction=instructions, graph_id=self.graph_id, node_id=self.node_id,
                task_id=f"memory:{phase}", node_type_id="node_memory",
            ))
            agent.Message("user", redact(encode(payload), secrets), persist=False)
            response = agent.Send(run_tools=False, web_search="disabled", thinking="enabled", reasoning_effort="low", stream=False)
            if not isinstance(response, str):
                raise TypeError("memory provider must return a text response")
            return redact(response, secrets)

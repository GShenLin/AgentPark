from __future__ import annotations

from importlib import import_module

from .contracts import HarnessAdapter, HarnessDescriptor


DESCRIPTORS = (
    HarnessDescriptor("codex", "Codex", "codex_node", "@openai/codex", "codex", "app-server",
                      "https://github.com/openai/codex", "persistent"),
    HarnessDescriptor("claude", "Claude Code", "claude_node", "@anthropic-ai/claude-code", "claude", "sdk",
                      "https://code.claude.com/docs/en/overview", "persistent"),
    HarnessDescriptor("openclaw", "OpenClaw", "openclaw_node", "openclaw", "openclaw", "local-json",
                      "https://docs.openclaw.ai/cli/agent", "persistent"),
    HarnessDescriptor("deepseek_harness", "DeepSeek Harness", "deepseek_harness_node", "@deepseek-ai/dsh", "dsh", "acp",
                      "https://github.com/deepseek-ai/deepseek-harness", "persistent"),
    HarnessDescriptor("pi", "Pi", "pi_node", "@earendil-works/pi-coding-agent", "pi", "json-stream",
                      "https://github.com/earendil-works/pi", "persistent"),
    HarnessDescriptor("hermes_agent", "Hermes Agent", "hermes_agent_node", "hermes-agent", "hermes", "python-sdk",
                      "https://github.com/NousResearch/hermes-agent", "persistent", "hermes-python"),
)
HARNESS_NODE_TYPES = frozenset(item.node_type for item in DESCRIPTORS)
_DESCRIPTORS = {item.id: item for item in DESCRIPTORS}


def descriptor(harness_id: str) -> HarnessDescriptor:
    try:
        return _DESCRIPTORS[harness_id]
    except KeyError as exc:
        raise ValueError(f"Unknown Harness: {harness_id}") from exc


def create_adapter(harness_id: str) -> HarnessAdapter:
    descriptor(harness_id)
    module = import_module(f"src.harness.adapters.{harness_id}")
    return module.Adapter()

from __future__ import annotations

import json
from pathlib import Path

from nodes.agent_skill_loader import load_node_skills
from nodes.agent_support.capability_setup import resolve_agent_capabilities


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARK_MCP_URL = "https://sd6j8o9hu8aldae0o6es0.apigateway-cn-beijing.volceapi.com/mcp"


def test_ark_doc_skill_declares_the_ark_docs_mcp_dependency():
    skill = load_node_skills(["ark-doc-cli"], node_id="GPT1")[0]

    assert skill.name == "ark-doc-cli"
    assert skill.version == "0.1.0"
    assert skill.mcp_servers == ("ark-docs-mcp",)
    assert skill.mcp_server_configs == {
        "ark-docs-mcp": {
            "label": "Ark Docs MCP",
            "transport": "streamable-http",
            "url": ARK_MCP_URL,
        }
    }
    assert "ark_search_docs" in skill.content
    assert "ark_get_skill" in skill.content


def test_current_node_defers_ark_doc_mcp_service_to_skill_activation():
    profile = json.loads((PROJECT_ROOT / "agent" / "GPT1.json").read_text(encoding="utf-8"))

    assert profile["source_graph_id"] == "default"
    assert profile["source_node_id"] == "GPT1"
    assert profile["fields"]["skills"] == ["ark-doc-cli"]
    assert profile["fields"]["mcp_servers"] == []

    plan = resolve_agent_capabilities(
        lambda key, default: profile["fields"].get(key, default),
        node_id="GPT1",
    )

    assert plan.tool_names == ("system_tools", "skill_activation_tools")
    assert plan.mcp_server_names == ()
    assert plan.mcp_settings["mcpServers"]["ark-docs-mcp"] == {
        "label": "Ark Docs MCP",
        "transport": "streamable-http",
        "url": ARK_MCP_URL,
    }

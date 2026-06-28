import json
import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("AITOOLS_RUN_OPENAI_MCP_LIVE") != "1",
    reason="live OpenAI Docs MCP smoke test is opt-in",
)


def test_openai_docs_skill_registers_and_calls_live_mcp_search():
    from nodes.agent_mcp_loader import register_mcp_server_tools
    from nodes.agent_skill_loader import collect_loaded_skill_dependencies, load_node_skills
    from src.tool.base_tool import BaseTool

    skill_root = Path.home() / ".codex" / "skills" / ".system"
    if not (skill_root / "openai-docs" / "SKILL.md").exists():
        pytest.skip("openai-docs skill is not installed in the local Codex skill root")

    skills = load_node_skills(["openai-docs"], node_id="openai_mcp_live_probe", skill_root=str(skill_root))
    dependencies = collect_loaded_skill_dependencies(skills)

    assert dependencies.mcp_servers == ("openaiDeveloperDocs",)
    assert dependencies.mcp_server_configs["openaiDeveloperDocs"]["url"] == "https://developers.openai.com/mcp"

    class DummyAgent:
        config = {}

        def __init__(self):
            self.tools = BaseTool(self)

    agent = DummyAgent()
    register_mcp_server_tools(
        agent,
        list(dependencies.mcp_servers),
        settings={"mcpServers": dependencies.mcp_server_configs},
    )

    declaration_names = [
        item.get("function", {}).get("name")
        for item in agent.tools.tool_declarations
        if isinstance(item, dict)
    ]
    search_tool = "mcp__openaiDeveloperDocs__search_openai_docs"
    assert search_tool in declaration_names

    result = agent.tools.execute_tool_result(search_tool, {"query": "Responses API tools", "limit": 2})

    assert result.ok
    payload = json.loads(result.result)
    text = payload["content"][0]["text"]
    assert "developers.openai.com" in text

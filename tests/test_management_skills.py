import json

from nodes.agent_skill_activation import bind_deferred_skills
from nodes.agent_skill_loader import load_skill_directory
from nodes.agent_support.capability_setup import resolve_agent_capabilities
from src.long_term_memory.retrieval import MemoryReader
from src.long_term_memory.store import MemoryStore
from src.tool.base_tool import BaseTool


MEMORY_TOOLS = {"search_node_memory", "read_node_memory", "add_node_memory_note", "forget_node_memory"}
SKILL_TOOLS = {"activate_skill", "deactivate_skill", "list_skill_resources", "read_skill_resource"}


def make_agent(directory, *, extra=()):
    directory.mkdir(exist_ok=True)
    agent = type("Agent", (), {})()
    agent.config = {}
    agent.messages = []
    agent._agentpark_node_directory = str(directory)
    agent._agentpark_memory_reader = MemoryReader(MemoryStore(directory, "graph", directory.name))
    agent.tools = BaseTool(agent)
    agent.addTool = agent.tools.addTool
    agent.Message = lambda role, content, **kw: agent.messages.append({"role": role, "content": content})
    plan = resolve_agent_capabilities(lambda key, default: {"tools": ["system_tools"]}.get(key, default),
                                      node_id=directory.name)
    for module in plan.tool_names:
        agent.addTool(module)
    bind_deferred_skills(agent, [*plan.selected_skill_definitions, *extra], role="system")
    return agent


def activate(agent, name):
    result = json.loads(agent.tools.execute_tool("activate_skill", {"skill": name}))
    assert result["status"] == "success", result
    assert result["active"] is True
    return result


def test_skill_tools_are_direct_and_memory_is_deferred(tmp_path):
    agent = make_agent(tmp_path / "node")
    assert len(agent.tools.function_map) == 18
    assert SKILL_TOOLS <= agent.tools.function_map.keys()
    assert MEMORY_TOOLS.isdisjoint(agent.tools.function_map)
    assert "skill-management" not in agent._agentpark_available_skills
    activate(agent, "node-memory")
    assert len(agent.tools.function_map) == 22
    assert MEMORY_TOOLS <= agent.tools.function_map.keys()
    result = json.loads(agent.tools.execute_tool("search_node_memory", {"query": "fixture"}))
    assert result["matches"] == []
    closed = json.loads(agent.tools.execute_tool("deactivate_skill", {"skill": "node-memory"}))
    assert closed["status"] == "success"
    assert SKILL_TOOLS <= agent.tools.function_map.keys()
    assert MEMORY_TOOLS.isdisjoint(agent.tools.function_map)
    activate(agent, "node-memory")
    next_turn = make_agent(tmp_path / "node")
    assert len(next_turn.tools.function_map) == 18
    assert MEMORY_TOOLS.isdisjoint(next_turn.tools.function_map)


def test_reading_skill_file_returns_content_without_activation(tmp_path):
    agent = make_agent(tmp_path / "node")
    path = agent._agentpark_available_skills["node-memory"].path
    result = json.loads(agent.tools.execute_tool("read_file", {"file_path": path}))
    assert result["status"] == "success"
    assert "name: node-memory" in result["content"]
    assert "skill_activation" not in result
    assert agent._agentpark_skill_runtime.active == set()
    assert MEMORY_TOOLS.isdisjoint(agent.tools.function_map)


def test_resource_tools_remain_available_after_skill_deactivation(tmp_path):
    directory = tmp_path / "demo"
    (directory / "references").mkdir(parents=True)
    (directory / "SKILL.md").write_text("---\nname: demo\ndescription: Demo\n---\nUse demo.", encoding="utf-8")
    (directory / "references" / "guide.md").write_text("Resource evidence", encoding="utf-8")
    agent = make_agent(tmp_path / "node", extra=[load_skill_directory(str(directory))])
    activate(agent, "demo")
    listing = json.loads(agent.tools.execute_tool("list_skill_resources", {"skill": "demo"}))
    assert listing["resources"][0]["path"] == "references/guide.md"
    resource = json.loads(agent.tools.execute_tool("read_skill_resource", {"skill": "demo", "path": "references/guide.md"}))
    assert resource["content"] == "Resource evidence"
    agent.tools.execute_tool("deactivate_skill", {"skill": "demo"})
    assert SKILL_TOOLS <= agent.tools.function_map.keys()
    assert agent._agentpark_skill_runtime.active == set()


def test_memory_tools_remain_bound_to_host_node_after_lazy_activation(tmp_path):
    first, second = make_agent(tmp_path / "first"), make_agent(tmp_path / "second")
    activate(first, "node-memory")
    activate(second, "node-memory")
    result = json.loads(first.tools.execute_tool("add_node_memory_note", {"content": "fixture note"}))
    assert result["status"] == "pending_consolidation"
    assert len(first._agentpark_memory_reader.store.notes()) == 1
    assert second._agentpark_memory_reader.store.notes() == []
    result = json.loads(second.tools.execute_tool("read_node_memory", {"source_id": "f" * 64}))
    assert result["status"] == "exception"
    for name in MEMORY_TOOLS:
        declaration = next(d for d in second.tools.tool_declarations if d["function"]["name"] == name)
        assert "agent" not in declaration["function"]["parameters"]["properties"]
        assert "node_id" not in declaration["function"]["parameters"]["properties"]

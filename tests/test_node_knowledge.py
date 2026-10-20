import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nodes.agent_skill_activation import bind_deferred_skills, refresh_skill_messages
from nodes.agent_support.capability_setup import resolve_agent_capabilities
from src.knowledge.catalog import Catalog
from src.knowledge.contracts import LibraryConfig, LibraryUpdate
from src.knowledge.node_access import knowledge_ids, library_options, render_node_knowledge
from src.knowledge.skill import execute
from src.providers.agent_runtime_context import AgentRuntimeContext, bind_agent_runtime_context
from src.tool.base_tool import BaseTool


@pytest.fixture
def libraries(tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    catalog = Catalog(tmp_path)
    config = LibraryConfig(name="课件", folder=str(folder), embedding_url="http://localhost:1234/v1",
                           embedding_model="test", dimensions=8)
    first = catalog.create(config)["id"]
    second = catalog.create(config.model_copy(update={"name": "论文"}))["id"]
    hidden = catalog.create(config.model_copy(update={"name": "private", "allow_mcp": False}))["id"]
    return catalog, first, second, hidden


def plan_for(monkeypatch, workspace, fields):
    monkeypatch.setattr("nodes.agent_support.capability_setup.get_workspace_root", lambda: str(workspace))
    return resolve_agent_capabilities(lambda key, default: fields.get(key, default), node_id="test")


def test_selection_controls_skill_and_catalog(monkeypatch, libraries):
    catalog, first, second, hidden = libraries
    plan = plan_for(monkeypatch, catalog.workspace, {"knowledge_ids": [second, first, second]})
    assert [lib["id"] for lib in plan.knowledge_libraries] == [second, first]
    assert [s.name for s in plan.selected_skill_definitions].count("knowledge") == 1
    assert {item["value"] for item in library_options(catalog.workspace)} == {first, second, hidden}
    empty = plan_for(monkeypatch, catalog.workspace, {"skills": ["knowledge"], "knowledge_ids": []})
    assert "knowledge" not in [s.name for s in empty.selected_skill_definitions]
    assert execute(catalog.workspace, {"action": "list"}, library_ids=()) == {"libraries": []}
    assert [lib["id"] for lib in execute(catalog.workspace, {"action": "list"},
                                         library_ids=(second,))["libraries"]] == [second]
    private_plan = plan_for(monkeypatch, catalog.workspace, {"knowledge_ids": [hidden]})
    assert private_plan.knowledge_libraries[0]["id"] == hidden
    with pytest.raises(ValueError, match="不存在"):
        plan_for(monkeypatch, catalog.workspace, {"knowledge_ids": ["deleted"]})


@pytest.mark.parametrize("arguments", [
    {"action": "list"}, {"action": "search", "query": "test"},
    {"action": "read", "chunk_id": 1},
    {"action": "table", "document_id": 1, "sheet": "Sheet1", "metrics": [{"op": "count_rows", "name": "count"}]},
])
def test_unselected_library_cannot_be_accessed(libraries, arguments):
    catalog, first, second, _ = libraries
    with pytest.raises(PermissionError, match="未被当前节点勾选"):
        execute(catalog.workspace, {**arguments, "library_id": second}, library_ids=(first,))


def test_real_script_uses_bound_workspace_and_selection(monkeypatch, libraries, tmp_path):
    catalog, first, second, _ = libraries
    plan = plan_for(monkeypatch, catalog.workspace, {"knowledge_ids": [first, second]})
    agent = SimpleNamespace(config={}, messages=[])
    agent.tools = BaseTool(agent)
    bind_agent_runtime_context(agent, AgentRuntimeContext(
        node_directory=str(tmp_path / "node"), workspace_root=str(catalog.workspace),
        knowledge_ids=(first, second)))
    agent._agentpark_knowledge_context = render_node_knowledge(list(plan.knowledge_libraries))
    bind_deferred_skills(agent, plan.selected_skill_definitions, role="system")
    agent._agentpark_skill_runtime.change("knowledge", active=True)
    result = json.loads(agent.tools.execute_tool("skill__knowledge__list", {}))
    assert result["status"] == "success", result
    assert [lib["id"] for lib in json.loads(result["stdout"])["libraries"]] == [first, second]
    for messages in [agent.messages, refresh_skill_messages(agent, agent.messages)]:
        context = messages[0]["content"]
        assert first in context and second in context and "课件" in context
        assert "<state>active</state>" in context
        assert context.count("<node_knowledge>") == 1
    # MCP visibility does not revoke a node's explicit selection.
    config = catalog.get(first)
    catalog.update(first, LibraryUpdate(**{**config.model_dump(), "allow_mcp": False}))
    result = json.loads(agent.tools.execute_tool("skill__knowledge__list", {}))
    assert result["status"] == "success"
    assert [lib["id"] for lib in json.loads(result["stdout"])["libraries"]] == [first, second]


@pytest.mark.parametrize("value", [None, "id", [1], [""], [" id "]])
def test_selection_contract_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="knowledge_ids"):
        knowledge_ids(value)


def test_node_config_persists_selection_and_rejects_wrong_types(tmp_path):
    from src.web_backend.node_config_service import node_config_service
    from src.web_backend.node_config_errors import NodeConfigFormatError
    path = str(tmp_path / "node" / "config.json")
    node_config_service.write(path, {"node_id": "test", "knowledge_ids": ["a", "b"]})
    assert node_config_service.read_strict(path)["knowledge_ids"] == ["a", "b"]
    with pytest.raises(NodeConfigFormatError, match="knowledge_ids"):
        node_config_service.create_or_replace(path, {"node_id": "test", "knowledge_ids": "a"})


@pytest.mark.parametrize("selected", [False, True])
def test_node_run_automatically_activates_selected_knowledge(monkeypatch, libraries, tmp_path, selected):
    import nodes.agent_node as module
    from tests.agent_invocation_helpers import configured_fake

    catalog, first, second, _ = libraries
    monkeypatch.setattr("nodes.agent_support.capability_setup.get_workspace_root", lambda: str(catalog.workspace))
    monkeypatch.setattr(module, "get_workspace_root", lambda: str(catalog.workspace))
    monkeypatch.setattr(module.ConfigLoader, "get_provider_config", lambda *args: {"supportmode": ["chat"]})
    agent = SimpleNamespace(config={}, messages=[])
    agent.tools = BaseTool(agent)
    agent.addTool = agent.tools.addTool
    agent.Message = lambda role, content, **kwargs: agent.messages.append({"role": role, "content": content})
    agent.Send = lambda **kwargs: "ok"
    monkeypatch.setattr(module, "create_agent", lambda *args, **kwargs: configured_fake(agent, kwargs.get("agent_config")))
    node = module.Node()
    monkeypatch.setattr(node, "_resolve_memory_path", lambda ctx: str(tmp_path / "node" / "memory.md"))
    monkeypatch.setattr(node, "_resolve_messages_path", lambda ctx: str(tmp_path / "node" / "messages.jsonl"))
    result = node.on_input("hello", {"node_instance_id": "test", "provider_id": "test-chat",
                                    "skills": ["knowledge"], "knowledge_ids": [first, second] if selected else []})
    assert result["display"] == "ok"
    assert ("skill__knowledge__search" in agent.tools.function_map) is selected
    if selected:
        assert "knowledge" in agent._agentpark_skill_runtime.active
        context = "\n".join(str(m.get("content")) for m in agent.messages)
        assert first in context and second in context and "课件" in context

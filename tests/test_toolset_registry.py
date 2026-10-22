import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.tool.base_tool import BaseTool
from src.tool.tool_task_tools import TASK_CONTROL_TOOLS
from src.tool import toolset_registry as registry
from src.web_backend.settings_api import SettingsApiDomain


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(registry, "toolsets_path", lambda: str(tmp_path / "toolsets.json"))
    return tmp_path / "toolsets.json"


def save(path, sets):
    path.write_text(json.dumps({"toolsets": sets}), encoding="utf-8")


def test_defaults_preserve_every_schema_order_and_callable(isolated):
    defaults = registry.settings_document()
    before = {}
    for name in defaults["toolsets"]:
        tool = BaseTool(SimpleNamespace())
        tool.addTool(name)
        before[name] = (list(tool.tool_declarations), dict(tool.function_map))
    SettingsApiDomain(SimpleNamespace()).update_settings_section("toolsets", {"content": json.dumps(defaults)})
    for name, (declarations, functions) in before.items():
        tool = BaseTool(SimpleNamespace())
        tool.addTool(name)
        assert tool.tool_declarations == declarations, name
        assert tool.function_map == functions, name
    assert len(before["system_tools"][0]) == 14 + len(TASK_CONTROL_TOOLS)


def test_membership_empty_sets_dedup_and_next_load(isolated):
    sets = {"system_tools": {"description": "只读", "tools": ["file_read_tools:read_file"]},
            "custom": {"description": "", "tools": ["file_read_tools:read_file", "file_write_tools:write_file"]}}
    save(isolated, sets)
    tool = BaseTool(SimpleNamespace())
    tool.addTool("system_tools")
    tool.addTool("custom")
    assert list(tool.function_map) == [*TASK_CONTROL_TOOLS, "read_file", "write_file"]
    assert len(tool.tool_declarations) == 2 + len(TASK_CONTROL_TOOLS)
    sets["system_tools"]["tools"] = []
    save(isolated, sets)
    next_tool = BaseTool(SimpleNamespace())
    next_tool.addTool("system_tools")
    assert next_tool.function_map == TASK_CONTROL_TOOLS
    assert len(tool.function_map) == 2 + len(TASK_CONTROL_TOOLS)  # Running agents retain their snapshot.


@pytest.mark.parametrize("references", [
    ["missing_module:read_file"], ["file_read_tools:missing"],
    ["../file_read_tools:read_file"], ["system_tools"],
    ["file_read_tools:read_file", "system_tools:read_file"], [False],
])
def test_invalid_save_is_rejected_without_changing_disk(isolated, references):
    save(isolated, {})
    before = isolated.read_bytes()
    payload = {"toolsets": {"custom": {"description": "", "tools": references}}}
    with pytest.raises(HTTPException) as error:
        SettingsApiDomain(SimpleNamespace()).update_settings_section("toolsets", {"content": json.dumps(payload)})
    assert error.value.status_code == 400
    assert isolated.read_bytes() == before


def test_failed_resolution_does_not_partially_register(isolated):
    save(isolated, {"custom": {"description": "", "tools": ["file_read_tools:read_file", "file_read_tools:missing"]}})
    tool = BaseTool(SimpleNamespace())
    with pytest.raises(Exception, match="Unknown tool reference"):
        tool.addTool("custom")
    assert tool.function_map == TASK_CONTROL_TOOLS and len(tool.tool_declarations) == len(TASK_CONTROL_TOOLS)


def test_api_catalog_and_node_options_reflect_saved_custom_sets(isolated):
    from nodes.agent_tool_loader import list_available_tool_options
    from src.web_backend.node_catalog import NodeCatalog

    domain = SettingsApiDomain(SimpleNamespace())
    result = domain.get_settings_section("toolsets")
    assert "system_tools" in result["builtin_toolsets"]
    assert any(item["name"] == "read_file" for item in result["tool_catalog"])
    data = result["data"]
    data["toolsets"]["my_custom_tools"] = {"description": "自定义", "tools": []}
    domain.update_settings_section("toolsets", {"content": json.dumps(data)})
    assert "my_custom_tools" in NodeCatalog(SimpleNamespace()).list_tools()["tools"]
    assert "my_custom_tools" in {item["value"] for item in list_available_tool_options()}
    assert domain.get_settings_section("toolsets")["data"] == data


def test_access_filter_blocks_custom_set_alias(isolated):
    from src.tool.access_filter import filter_registered_agent_tools

    save(isolated, {"custom": {"description": "", "tools": ["console_tools:execute_console_command", "file_read_tools:read_file"]}})
    agent = SimpleNamespace()
    agent.tools = BaseTool(agent)
    agent.tools.addTool("custom")
    assert filter_registered_agent_tools(agent, ["console_tools"]) == ("execute_console_command",)
    assert list(agent.tools.function_map) == [*TASK_CONTROL_TOOLS, "read_file"]


def test_default_policy_keeps_explicit_read_tools_available(isolated):
    from src.access_policy import DEFAULT_NONDEVELOPER_FILTERED_TOOLS
    from src.tool.access_filter import filter_registered_agent_tools

    agent = SimpleNamespace()
    agent.tools = BaseTool(agent)
    agent.tools.addTool("file_read_tools")
    filter_registered_agent_tools(agent, DEFAULT_NONDEVELOPER_FILTERED_TOOLS)
    assert list(agent.tools.function_map) == [*TASK_CONTROL_TOOLS, "read_file"]


def test_capability_summary_uses_actual_members(isolated):
    from src.web_backend.companion_capabilities import infer_node_can

    save(isolated, {"system_tools": {"description": "", "tools": ["file_read_tools:read_file"]}})
    can = infer_node_can({"tools": ["system_tools"]})
    assert can["read_local_files"] is True
    assert can["write_local_files"] is False
    assert can["execute_shell"] is False


@pytest.mark.parametrize("name", ["system_tools", "my_custom_tools"])
def test_deleted_sets_stay_deleted_and_can_be_recreated(isolated, name):
    from nodes.agent_tool_loader import list_available_tool_options
    from src.tool.tool_load_errors import ToolLoadError
    from src.web_backend.node_catalog import NodeCatalog

    domain = SettingsApiDomain(SimpleNamespace())
    data = domain.get_settings_section("toolsets")["data"]
    data["toolsets"]["my_custom_tools"] = {"description": "custom", "tools": ["file_read_tools:read_file"]}
    domain.update_settings_section("toolsets", {"content": json.dumps(data)})
    del data["toolsets"][name]
    data["deleted_toolsets"] = [name]
    domain.update_settings_section("toolsets", {"content": json.dumps(data)})
    reloaded = domain.get_settings_section("toolsets")["data"]
    assert name not in reloaded["toolsets"]
    assert name not in NodeCatalog(SimpleNamespace()).list_tools()["tools"]
    assert name not in {item["value"] for item in list_available_tool_options()}
    with pytest.raises(ToolLoadError, match="has been deleted"):
        BaseTool(SimpleNamespace()).addTool(name)
    # Removing a set never deletes underlying implementations used by other sets.
    assert registry.resolve_reference("system_tools:read_file")[1] is not None
    reloaded["deleted_toolsets"] = []
    reloaded["toolsets"][name] = {"description": "recreated", "tools": []}
    domain.update_settings_section("toolsets", {"content": json.dumps(reloaded)})
    assert registry.resolve_toolset(name) == []


@pytest.mark.parametrize("deleted", ["system_tools", [False], ["../system_tools"], ["system_tools", "system_tools"]])
def test_deleted_set_contract_rejects_invalid_data(isolated, deleted):
    with pytest.raises(ValueError):
        registry.validate_structure({"toolsets": {}, "deleted_toolsets": deleted})


def test_active_and_deleted_names_cannot_overlap(isolated):
    with pytest.raises(ValueError, match="cannot also appear"):
        registry.validate_structure({"toolsets": {"system_tools": {"description": "", "tools": []}},
                                     "deleted_toolsets": ["system_tools"]})

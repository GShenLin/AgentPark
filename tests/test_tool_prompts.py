import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.tool import toolset_registry as registry
from src.tool.base_tool import BaseTool
from src.web_backend.settings_api import SettingsApiDomain


@pytest.fixture
def settings(tmp_path, monkeypatch):
    path = tmp_path / "toolsets.json"
    monkeypatch.setattr(registry, "toolsets_path", lambda: str(path))
    return SettingsApiDomain(SimpleNamespace()), path


def save(domain, overrides):
    document = domain.get_settings_section("toolsets")["data"]
    document["tool_prompts"] = overrides
    domain.update_settings_section("toolsets", {"content": json.dumps(document, ensure_ascii=False)})


def description(tools, name):
    return next(item["function"]["description"] for item in tools.tool_declarations if item["function"]["name"] == name)


def test_save_reload_register_restore_and_existing_run_snapshot(settings):
    from functions.file_read_tools import read_file_declaration
    domain, path = settings
    original = deepcopy(read_file_declaration)
    custom = "先确认路径。\n读取后总结发现，不要重复读取。"
    save(domain, {"read_file": custom})
    assert json.loads(path.read_text(encoding="utf-8"))["tool_prompts"] == {"read_file": custom}
    assert domain.get_settings_section("toolsets")["data"]["tool_prompts"]["read_file"] == custom
    running = BaseTool(SimpleNamespace())
    running.addTool("file_read_tools")
    assert description(running, "read_file") == custom
    assert read_file_declaration == original
    effective = next(item for item in running.tool_declarations if item["function"]["name"] == "read_file")
    assert effective["function"]["parameters"] == original["function"]["parameters"]
    save(domain, {})
    fresh = BaseTool(SimpleNamespace())
    fresh.addTool("file_read_tools")
    assert description(fresh, "read_file") == original["function"]["description"]
    assert description(running, "read_file") == custom


@pytest.mark.parametrize("name", ["mcp__server__read", "skill__my_skill__query", "plugin_query", "read_tool_task"])
def test_external_and_control_tools_use_override_without_changing_execution(settings, name):
    domain, _ = settings
    save(domain, {name: "Custom instructions"})
    tools = BaseTool(SimpleNamespace())
    if name != "read_tool_task":
        declaration = {"type": "function", "function": {"name": name, "description": "From external tool",
            "parameters": {"type": "object", "properties": {}}}}
        def callback():
            return "same execution"
        tools.register_external_tool(declaration, callback)
        assert tools.function_map[name] is callback
        assert declaration["function"]["description"] == "From external tool"
    assert description(tools, name) == "Custom instructions"


def test_skill_registration_keeps_the_original_run_snapshot(settings):
    from nodes.agent_skill_runtime import _RegistrationAgent
    domain, _ = settings
    save(domain, {"read_file": "Run one"})
    agent = SimpleNamespace()
    agent.tools = BaseTool(agent)
    save(domain, {"read_file": "Run two"})
    target = _RegistrationAgent(agent)
    target.addTool("file_read_tools")
    assert description(target.tools, "read_file") == "Run one"


def test_provider_adapter_receives_overridden_description(settings):
    from src.providers.claude_chat_runtime import ClaudeChatRuntime
    domain, _ = settings
    save(domain, {"read_file": "Instructions actually sent to the model"})
    tools = BaseTool(SimpleNamespace())
    tools.addTool("file_read_tools")
    tool = next(item for item in tools.tool_declarations if item["function"]["name"] == "read_file")
    runtime = SimpleNamespace(_is_claude_tool_declaration=ClaudeChatRuntime._is_claude_tool_declaration,
                              _oauth_tool_name=lambda name: name)
    wire = ClaudeChatRuntime.to_claude_tool_declaration(runtime, tool)
    assert wire["description"] == "Instructions actually sent to the model"
    assert wire["input_schema"] == tool["function"]["parameters"]


@pytest.mark.parametrize("overrides", [None, [], {"bad name": "text"}, {"read_file": 3}, {"read_file": "x" * 32001}])
def test_invalid_prompt_save_preserves_disk(settings, overrides):
    domain, path = settings
    save(domain, {"read_file": "existing"})
    before = path.read_bytes()
    with pytest.raises(HTTPException) as error:
        save(domain, overrides)
    assert error.value.status_code == 400 and path.read_bytes() == before


def test_empty_override_is_distinct_from_restoring_default(settings):
    domain, _ = settings
    save(domain, {"read_file": ""})
    tools = BaseTool(SimpleNamespace())
    tools.addTool("file_read_tools")
    assert description(tools, "read_file") == ""


def test_catalog_contains_controls_and_keeps_original_defaults(settings):
    domain, _ = settings
    save(domain, {"read_file": "custom"})
    catalog = domain.get_settings_section("toolsets")["tool_prompt_catalog"]
    assert {"read_tool_task", "wait_tool_task", "stop_tool_task"} <= {item["name"] for item in catalog}
    defaults = next(item["defaults"] for item in catalog if item["name"] == "read_file")
    assert defaults and all(item["description"] != "custom" for item in defaults)

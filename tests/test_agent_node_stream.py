import time
import json
import os

import pytest


def _write_agent_node_test_skill(root, name="ue5-cpp-gameplay"):
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        f"---\nname: {name}\ndescription: Test skill\n---\n\nUse the test skill.\n",
        encoding="utf-8",
    )
    return skill_path


def test_agent_node_tools_schema_is_multiselect_with_available_tools():
    from nodes.agent_node import Node

    schema = Node().get_config_schema(None)

    tools_schema = schema.get("tools")
    assert isinstance(tools_schema, dict)
    assert tools_schema.get("type") == "multiselect"
    options = tools_schema.get("options")
    assert isinstance(options, list)
    assert any(item.get("value") == "file_read_tools" for item in options if isinstance(item, dict))

    assert schema["plugins"]["type"] == "multiselect"
    assert isinstance(schema["plugins"]["options"], list)
    assert schema["mcp_servers"]["type"] == "multiselect"
    assert isinstance(schema["mcp_servers"]["options"], list)
    assert schema["collaboration_mode"]["type"] == "select"
    assert [item["value"] for item in schema["collaboration_mode"]["options"]] == ["default", "plan"]
    assert "agentToolStagePolicyEnabled" not in schema
    assert "agentToolStageGatheringAllowedTools" not in schema
    assert "agentToolStageAnalyzingAllowedTools" not in schema
    assert "agentToolStageFinalizingAllowedTools" not in schema
    assert list(schema.keys())[-4:] == ["tools", "mcp_servers", "skills", "plugins"]


def test_agent_node_capability_schema_uses_registry_descriptors(monkeypatch):
    import nodes.agent_node as agent_node_module

    class DummyRegistry:
        def discover_payload(self, config):
            assert config == {"tools": ["demo_tool"]}
            return {
                "tool": {
                    "available": [
                        {
                            "value": "demo_tool",
                            "label": "Demo Tool",
                            "kind": "tool",
                            "source": "workspace",
                            "status": "selected",
                            "enabled": True,
                            "diagnostics": ["ready"],
                            "dependencies": [{"kind": "mcp", "id": "docs"}],
                            "effective": "next_agent_run",
                        }
                    ],
                },
                "mcp": {"available": []},
                "skill": {"available": []},
                "plugin": {"available": []},
            }

    monkeypatch.setattr(agent_node_module, "CapabilityRegistry", lambda: DummyRegistry())

    schema = agent_node_module.Node().get_config_schema({"tools": ["demo_tool"]})

    option = schema["tools"]["options"][0]
    assert option["value"] == "demo_tool"
    assert option["source"] == "workspace"
    assert option["status"] == "selected"
    assert option["diagnostics"] == ["ready"]
    assert option["dependencies"] == [{"kind": "mcp", "id": "docs"}]
    assert option["effective"] == "next_agent_run"


def test_agent_node_schema_includes_selected_provider_features(monkeypatch):
    import nodes.agent_node as agent_node_module

    class DummyRegistry:
        def discover_payload(self, _config):
            return {
                "tool": {"available": []},
                "mcp": {"available": []},
                "skill": {"available": []},
                "plugin": {"available": []},
            }

    class DummyConfigLoader:
        def get_all_providers(self):
            return {
                "zhipu": {
                    "features": {
                        "web_search": {"supported": False, "values": []},
                        "tools": {"supported": False, "values": []},
                        "thinking": {"supported": True, "values": ["enabled", "disabled"]},
                        "reasoning_effort": {
                            "supported": True,
                            "values": ["minimal", "low", "medium", "high", "xhigh"],
                        },
                    }
                }
            }

    monkeypatch.setattr(agent_node_module, "CapabilityRegistry", lambda: DummyRegistry())
    monkeypatch.setattr(agent_node_module, "ConfigLoader", lambda: DummyConfigLoader())

    schema = agent_node_module.Node().get_config_schema({"provider_id": "zhipu"})

    assert schema["web_search"]["provider_feature"]["supported"] is False
    assert "not supported" in schema["web_search"]["description"]
    assert schema["tools"]["provider_feature"]["supported"] is False
    assert "not supported" in schema["tools"]["description"]
    assert schema["thinking"]["provider_feature"]["values"] == ["enabled", "disabled"]
    assert "Supported values: enabled, disabled" in schema["thinking"]["description"]
    assert schema["reasoning_effort"]["provider_feature"]["supported"] is True


def test_agent_node_registers_selected_mcp_servers_before_send(monkeypatch):
    import nodes.agent_node as agent_node_module

    captured = {"registered": [], "send_tool_count": None}

    class ToolRegistry:
        def __init__(self):
            self.tool_declarations = []

        def register_external_tool(self, declaration, func):
            self.tool_declarations.append(declaration)

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.tools = ToolRegistry()
            self.tool_declarations = self.tools.tool_declarations

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            captured["send_tool_count"] = len(self.tools.tool_declarations)
            return "ok"

    def fake_register(agent, values, *, settings=None):
        captured["registered"] = list(values)
        captured["settings"] = settings
        agent.tools.register_external_tool(
            {
                "type": "function",
                "function": {
                    "name": "mcp__docs__search",
                    "description": "Docs search.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            lambda agent=None: "ok",
        )
        return []

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())
    monkeypatch.setattr(agent_node_module, "register_mcp_server_tools", fake_register)
    monkeypatch.setattr(agent_node_module, "inject_mcp_server_context", lambda *_args, **_kwargs: [])

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_mcp_unit",
            "node_instance_id": "n_mcp_unit",
            "provider_id": "provider-stream",
            "mcp_servers": ["docs"],
        },
    )

    assert str(result.get("display") or "") == "ok"
    assert captured["registered"] == ["docs"]
    assert captured["send_tool_count"] == 1
    assert isinstance(captured["settings"], dict)


def test_agent_node_expands_plugin_tools_skills_and_mcp(monkeypatch):
    import nodes.agent_node as agent_node_module
    from nodes.agent_plugin_loader import PluginCapabilitySet
    from nodes.agent_plugin_tool_loader import PluginToolDefinition
    from nodes.agent_skill_loader import SkillDefinition

    captured = {"tools": [], "plugin_tools": [], "skills": None, "mcp": [], "mcp_settings": None}

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.tools = self

        def addTool(self, name):
            captured["tools"].append(name)

        def register_external_tool(self, declaration, func):
            captured["plugin_tools"].append(declaration["function"]["name"])

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    extra_skill = SkillDefinition(
        name="plugin-skill",
        description="Plugin skill",
        path="plugin/SKILL.md",
        content="Use plugin skill.",
    )
    plugin_tool = PluginToolDefinition(
        name="plugin__core-dev__local_echo",
        source_name="local_echo",
        path="plugin/tools.py",
        declaration={
            "type": "function",
            "function": {
                "name": "plugin__core-dev__local_echo",
                "description": "Echo.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        callable=lambda agent=None: "ok",
    )
    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())
    monkeypatch.setattr(
        agent_node_module,
        "resolve_plugin_capabilities",
        lambda *_args, **_kwargs: PluginCapabilitySet(
            tools=("file_read_tools",),
            tool_definitions=(plugin_tool,),
            skills=("control-in-app-browser",),
            skill_definitions=(extra_skill,),
            mcp_servers=("docs",),
            mcp_server_configs={"docs": {"transport": "stdio", "command": "docs-mcp"}},
        ),
    )
    def fake_register_mcp(_agent, values, *, settings=None):
        captured["mcp"].extend(values)
        captured["mcp_settings"] = settings
        return []

    monkeypatch.setattr(agent_node_module, "register_mcp_server_tools", fake_register_mcp)
    monkeypatch.setattr(agent_node_module, "inject_mcp_server_context", lambda *_args, **_kwargs: [])

    def fake_inject_skills(self, agent, values, *, node_id="", extra_skills=None, role="system"):
        captured["skills"] = {
            "values": list(values.get("skills") or []),
            "extra": list(extra_skills or []),
            "node_id": node_id,
            "role": role,
        }
        return []

    monkeypatch.setattr(agent_node_module.Node, "_inject_configured_skills", fake_inject_skills)

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_plugin_unit",
            "node_instance_id": "n_plugin_unit",
            "provider_id": "provider-stream",
            "plugins": ["core-dev"],
            "tools": ["rg_tools"],
            "skills": [],
            "mcp_servers": [],
        },
    )

    assert str(result.get("display") or "") == "ok"
    assert captured["tools"] == ["rg_tools", "file_read_tools"]
    assert captured["plugin_tools"] == ["plugin__core-dev__local_echo"]
    assert captured["mcp"] == ["docs"]
    assert captured["mcp_settings"]["mcpServers"]["docs"]["command"] == "docs-mcp"
    assert captured["skills"]["values"] == ["control-in-app-browser"]
    assert captured["skills"]["extra"] == [extra_skill]
    assert captured["skills"]["node_id"] == "n_plugin_unit"


def test_agent_node_registers_selected_skill_mcp_dependencies_before_send(monkeypatch):
    import nodes.agent_node as agent_node_module
    from nodes.agent_plugin_loader import PluginCapabilitySet
    from nodes.agent_skill_loader import SkillDefinition

    captured = {"mcp": [], "settings": None, "skills": None}
    selected_skill = SkillDefinition(
        name="openai-docs",
        description="OpenAI docs",
        path="skills/openai-docs/SKILL.md",
        content="Use OpenAI docs.",
        mcp_servers=("openaiDeveloperDocs",),
        mcp_server_configs={
            "openaiDeveloperDocs": {
                "transport": "streamable-http",
                "url": "https://developers.openai.com/mcp",
            }
        },
    )

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.tools = self

        def addTool(self, _name):
            return None

        def register_external_tool(self, _declaration, _func):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())
    monkeypatch.setattr(agent_node_module, "resolve_plugin_capabilities", lambda *_args, **_kwargs: PluginCapabilitySet())
    monkeypatch.setattr(agent_node_module, "load_node_skills", lambda *_args, **_kwargs: [selected_skill])

    def fake_register_mcp(_agent, values, *, settings=None):
        captured["mcp"].extend(values)
        captured["settings"] = settings
        return []

    def fake_inject_skills(self, _agent, values, *, node_id="", extra_skills=None, role="system"):
        captured["skills"] = {
            "values": list(values.get("skills") or []),
            "extra": list(extra_skills or []),
            "node_id": node_id,
            "role": role,
        }
        return []

    monkeypatch.setattr(agent_node_module, "register_mcp_server_tools", fake_register_mcp)
    monkeypatch.setattr(agent_node_module, "inject_mcp_server_context", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(agent_node_module.Node, "_inject_configured_skills", fake_inject_skills)

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_skill_mcp",
            "node_instance_id": "n_skill_mcp",
            "provider_id": "provider-stream",
            "skills": ["openai-docs"],
        },
    )

    assert str(result.get("display") or "") == "ok"
    assert captured["mcp"] == ["openaiDeveloperDocs"]
    assert captured["settings"]["mcpServers"]["openaiDeveloperDocs"]["url"] == "https://developers.openai.com/mcp"
    assert captured["skills"]["values"] == []
    assert captured["skills"]["extra"] == [selected_skill]
    assert captured["skills"]["node_id"] == "n_skill_mcp"


def test_agent_node_auto_loads_skill_resource_tool_for_resource_skills(monkeypatch, tmp_path):
    import nodes.agent_node as agent_node_module
    from nodes.agent_plugin_loader import PluginCapabilitySet
    from nodes.agent_skill_loader import SkillDefinition
    from src.skills.resource_index import SkillResource

    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text("---\nname: demo\ndescription: Demo\n---\n\nUse it.\n", encoding="utf-8")
    captured = {"tools": [], "agent": None}
    selected_skill = SkillDefinition(
        name="demo",
        description="Demo",
        path=str(skill_path),
        content="Use it.",
        resource_root=str(skill_dir),
        resources=(SkillResource(type="reference", path="references/guide.md", title="Guide", size_bytes=10),),
    )

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.tools = self
            captured["agent"] = self

        def addTool(self, name):
            captured["tools"].append(name)

        def register_external_tool(self, _declaration, _func):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())
    monkeypatch.setattr(agent_node_module, "load_node_skills", lambda *_args, **_kwargs: [selected_skill])
    monkeypatch.setattr(agent_node_module, "resolve_plugin_capabilities", lambda *_args, **_kwargs: PluginCapabilitySet())
    monkeypatch.setattr(agent_node_module, "register_mcp_server_tools", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(agent_node_module, "inject_mcp_server_context", lambda *_args, **_kwargs: [])

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_skill_resource_unit",
            "node_instance_id": "n_skill_resource_unit",
            "provider_id": "provider-stream",
            "skills": ["demo"],
            "tools": ["file_read_tools"],
        },
    )

    assert str(result.get("display") or "") == "ok"
    assert captured["tools"] == ["file_read_tools", "skill_resource_tools"]
    assert captured["agent"]._agentpark_skill_resource_roots["demo"] == str(skill_dir)


def test_agent_node_registers_selected_skill_script_tools(monkeypatch, tmp_path):
    import nodes.agent_node as agent_node_module
    from nodes.agent_plugin_loader import PluginCapabilitySet
    from nodes.agent_skill_loader import SkillDefinition
    from src.skills.script_manifest import SkillScriptDefinition

    skill_dir = tmp_path / "skills" / "demo"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    script_path = scripts_dir / "echo.py"
    script_path.write_text("print('ok')\n", encoding="utf-8")
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text("---\nname: demo\ndescription: Demo\n---\n\nUse it.\n", encoding="utf-8")
    captured = {"registered": [], "agent": None}
    selected_skill = SkillDefinition(
        name="demo",
        description="Demo",
        path=str(skill_path),
        content="Use it.",
        resource_root=str(skill_dir),
        script_tools=(
            SkillScriptDefinition(
                id="echo",
                name="Echo",
                description="Run echo.",
                skill_name="demo",
                skill_dir=str(skill_dir),
                entry=str(script_path),
                args_schema={"type": "object", "properties": {}, "additionalProperties": False},
                cwd=str(skill_dir),
                timeout_seconds=5,
                allow_write=False,
                enabled=True,
            ),
        ),
    )

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.tools = self
            captured["agent"] = self

        def addTool(self, _name):
            return None

        def register_external_tool(self, declaration, func):
            captured["registered"].append((declaration["function"]["name"], func))

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())
    monkeypatch.setattr(agent_node_module, "load_node_skills", lambda *_args, **_kwargs: [selected_skill])
    monkeypatch.setattr(agent_node_module, "resolve_plugin_capabilities", lambda *_args, **_kwargs: PluginCapabilitySet())
    monkeypatch.setattr(agent_node_module, "register_mcp_server_tools", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(agent_node_module, "inject_mcp_server_context", lambda *_args, **_kwargs: [])

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_skill_script_unit",
            "node_instance_id": "n_skill_script_unit",
            "provider_id": "provider-stream",
            "skills": ["demo"],
        },
    )

    assert str(result.get("display") or "") == "ok"
    assert [name for name, _func in captured["registered"]] == ["skill__demo__echo"]


def test_agent_node_stream_callback_and_done(monkeypatch):
    import nodes.agent_node as agent_node_module

    class DummyAgent:
        def __init__(self):
            self.messages = []

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **kwargs):
            handler = kwargs.get("stream_handler")
            if callable(handler):
                handler("A", "A")
                handler("B", "AB")
            return "AB"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    node = agent_node_module.Node()
    streamed_events: list[dict] = []

    result = node.on_input(
        "hello",
        {
            "graph_id": "g_stream_unit",
            "node_instance_id": "n_stream_unit",
            "provider_id": "provider-stream",
            "stream_callback": lambda payload: streamed_events.append(dict(payload)),
        },
    )

    assert isinstance(result, dict)
    assert str(result.get("display") or "") == "AB"

    assert streamed_events, "stream callback should receive message delta and done events"
    assert any(str(item.get("type") or "") == "node_message_delta" for item in streamed_events)
    assert any(str(item.get("type") or "") == "node_message_done" for item in streamed_events)
    done_event = next((item for item in streamed_events if str(item.get("type") or "") == "node_message_done"), None)
    assert isinstance(done_event, dict)
    assert str(done_event.get("text") or "") == "AB"


def test_agent_node_sse_response_mode_separates_instruction_and_system_prompt(monkeypatch):
    import nodes.agent_node as agent_node_module

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.config = {"type": "openai", "responsesApi": True}
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **kwargs):
            handler = kwargs.get("stream_handler")
            if callable(handler):
                handler("O", "O")
                handler("K", "OK")
            return "OK"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())
    monkeypatch.setattr(agent_node_module, "resolve_agent_default_instructions", lambda *_args, **_kwargs: "")

    events: list[dict] = []
    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_response_instruction_sse",
            "node_instance_id": "n_response_instruction_sse",
            "provider_id": "openai",
            "instruction": "Use the Responses instructions parameter.",
            "system_prompt": "Use the system prompt parameter.",
            "stream_callback": lambda payload: events.append(dict(payload)),
        },
    )

    assert str(result.get("display") or "") == "OK"
    assert any(str(item.get("type") or "") == "node_message_delta" for item in events)
    assert created_agents[0]._agentpark_responses_instruction == "Use the Responses instructions parameter."
    assert [item for item in created_agents[0].messages if item.get("role") == "system"][0]["content"] == "Use the system prompt parameter."
    assert not any("Responses instructions parameter" in str(item.get("content") or "") for item in created_agents[0].messages)


def test_agent_node_sse_chat_mode_keeps_instruction_and_system_prompt_as_messages(monkeypatch):
    import nodes.agent_node as agent_node_module

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.config = {"type": "doubao", "responsesApi": False}
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **kwargs):
            handler = kwargs.get("stream_handler")
            if callable(handler):
                handler("O", "O")
                handler("K", "OK")
            return "OK"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    events: list[dict] = []
    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_chat_instruction_sse",
            "node_instance_id": "n_chat_instruction_sse",
            "provider_id": "doubao-chat",
            "instruction": "Use the chat instruction context.",
            "system_prompt": "Use the chat system prompt.",
            "stream_callback": lambda payload: events.append(dict(payload)),
        },
    )

    assert str(result.get("display") or "") == "OK"
    assert any(str(item.get("type") or "") == "node_message_delta" for item in events)
    system_messages = [item for item in created_agents[0].messages if item.get("role") == "system"]
    assert [item["content"] for item in system_messages[:2]] == [
        "Use the chat system prompt.",
        "Use the chat instruction context.",
    ]
    assert not str(getattr(created_agents[0], "_agentpark_responses_instruction", "") or "").strip()


def test_agent_node_forwards_reasoning_effort(monkeypatch):
    import nodes.agent_node as agent_node_module

    captured = {}

    class DummyAgent:
        def __init__(self):
            self.messages = []

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **kwargs):
            captured.update(kwargs)
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_reasoning_unit",
            "node_instance_id": "n_reasoning_unit",
            "provider_id": "openai",
            "reasoning_effort": "high",
        },
    )

    assert str(result.get("display") or "") == "ok"
    assert captured["reasoning_effort"] == "high"


def test_agent_node_forwards_stream_enabled_false_from_provider_config(monkeypatch):
    import nodes.agent_node as agent_node_module

    captured = {}

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.config = {"type": "claude", "streamEnabled": False}

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **kwargs):
            captured.update(kwargs)
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_stream_disabled",
            "node_instance_id": "n_stream_disabled",
            "provider_id": "claude",
        },
    )

    assert str(result.get("display") or "") == "ok"
    assert captured["stream"] is False


def test_agent_node_defaults_stream_enabled_true_when_absent(monkeypatch):
    import nodes.agent_node as agent_node_module

    captured = {}

    class DummyAgent:
        def __init__(self):
            self.messages = []

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **kwargs):
            captured.update(kwargs)
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_stream_default",
            "node_instance_id": "n_stream_default",
            "provider_id": "openai",
        },
    )

    assert str(result.get("display") or "") == "ok"
    assert captured["stream"] is True


def test_agent_node_sets_collaboration_mode_runtime_attribute(monkeypatch):
    import nodes.agent_node as agent_node_module

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_collaboration_unit",
            "node_instance_id": "n_collaboration_unit",
            "provider_id": "openai",
            "collaboration_mode": "plan",
        },
    )

    assert str(result.get("display") or "") == "ok"
    assert created_agents[0]._agentpark_collaboration_mode == "plan"


def test_agent_node_uses_developer_context_role_for_openai_responses(monkeypatch):
    import nodes.agent_node as agent_node_module

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.config = {"type": "openai", "responsesApi": True}
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())
    monkeypatch.setattr(
        agent_node_module,
        "build_operational_memory_summary",
        lambda *_args, **_kwargs: "Operational memory for this node:\n- keep context developer-scoped",
    )

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_instruction_role_unit",
            "node_instance_id": "n_instruction_role_unit",
            "provider_id": "openai",
        },
    )

    assert str(result.get("display") or "") == "ok"
    memory_message = next(
        item for item in created_agents[0].messages if "Operational memory" in str(item.get("content") or "")
    )
    assert memory_message["role"] == "developer"


def test_agent_node_uses_developer_context_role_for_doubao_responses(monkeypatch):
    import nodes.agent_node as agent_node_module

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.config = {"type": "doubao", "responsesApi": True}
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())
    monkeypatch.setattr(
        agent_node_module,
        "build_operational_memory_summary",
        lambda *_args, **_kwargs: "Operational memory for this node:\n- keep context developer-scoped",
    )

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_doubao_context_role_unit",
            "node_instance_id": "n_doubao_context_role_unit",
            "provider_id": "doubao-seed-evolving",
        },
    )

    assert str(result.get("display") or "") == "ok"
    memory_message = next(
        item for item in created_agents[0].messages if "Operational memory" in str(item.get("content") or "")
    )
    assert memory_message["role"] == "developer"


def test_agent_node_injects_default_instructions_for_openai_responses(monkeypatch):
    import nodes.agent_node as agent_node_module

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.config = {"type": "openai", "responsesApi": True}
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())
    monkeypatch.setattr(
        agent_node_module,
        "resolve_agent_default_instructions",
        lambda *_args, **_kwargs: "Default instructions",
    )

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_default_instructions_unit",
            "node_instance_id": "n_default_instructions_unit",
            "provider_id": "openai",
        },
    )

    assert str(result.get("display") or "") == "ok"
    assert created_agents[0]._agentpark_responses_instruction == "Default instructions"
    assert not [item for item in created_agents[0].messages if item.get("role") == "system"]


def test_agent_node_injects_default_instructions_for_doubao_responses(monkeypatch):
    import nodes.agent_node as agent_node_module

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.config = {"type": "doubao", "responsesApi": True}
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())
    monkeypatch.setattr(
        agent_node_module,
        "resolve_agent_default_instructions",
        lambda *_args, **_kwargs: "Default instructions",
    )

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_doubao_default_instructions_unit",
            "node_instance_id": "n_doubao_default_instructions_unit",
            "provider_id": "doubao-seed-evolving",
        },
    )

    assert str(result.get("display") or "") == "ok"
    assert created_agents[0]._agentpark_responses_instruction == "Default instructions"
    assert not [item for item in created_agents[0].messages if item.get("role") == "system"]


def test_agent_node_forwards_tool_lifecycle_events(monkeypatch, tmp_path):
    import nodes.agent_node as agent_node_module
    from src.tool import tool_stats_store

    class DummyAgent:
        def __init__(self):
            self.messages = []
            self.tool_event_callback = None

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            assert callable(self.tool_event_callback)
            self.tool_event_callback(
                {
                    "type": "tool_call_start",
                    "name": "read_file",
                    "call_id": "call-1",
                    "provider": "unit",
                    "arguments": {"filePath": "README.md"},
                    "arguments_json": '{"filePath":"README.md"}',
                    "raw_call": {"id": "call-1", "function": {"name": "read_file"}},
                }
            )
            self.tool_event_callback(
                {
                    "type": "tool_call_end",
                    "name": "read_file",
                    "call_id": "call-1",
                    "provider": "unit",
                    "status": "completed",
                    "duration_ms": 3,
                    "result": {"status": "completed", "text": "ok"},
                    "result_preview": "ok",
                }
            )
            return "done"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())
    monkeypatch.setattr(tool_stats_store, "get_workspace_cache_dir", lambda: str(tmp_path / ".cache"))

    events: list[dict] = []
    node = agent_node_module.Node()

    result = node.on_input(
        "hello",
        {
            "graph_id": "g_tool_event_unit",
            "node_instance_id": "n_tool_event_unit",
            "provider_id": "provider-stream",
            "stream_callback": lambda payload: events.append(dict(payload)),
        },
    )

    assert str(result.get("display") or "") == "done"
    event_types = [str(item.get("type") or "") for item in events]
    assert "tool_call_start" in event_types
    assert "tool_call_end" in event_types
    assert events[event_types.index("tool_call_start")]["name"] == "read_file"
    assert events[event_types.index("tool_call_end")]["status"] == "completed"
    stats_path = tmp_path / ".cache" / "tool_stats" / "tool_calls.jsonl"
    stats_records = [json.loads(line) for line in stats_path.read_text(encoding="utf-8").splitlines()]
    assert stats_records[-1]["provider_id"] == "provider-stream"
    assert stats_records[-1]["success"] is True
    assert stats_records[-1]["tool_call_raw"] == {"id": "call-1", "function": {"name": "read_file"}}
    assert stats_records[-1]["result"] == {"status": "completed", "text": "ok"}
    summary = json.loads((tmp_path / ".cache" / "tool_stats" / "summary.json").read_text(encoding="utf-8"))
    assert summary["providers"]["provider-stream"]["success"] == 1
    assert summary["providers"]["provider-stream"]["tools"]["read_file"]["success"] == 1


def test_agent_node_keeps_working_path_runtime_only(monkeypatch):
    import nodes.agent_node as agent_node_module

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    node = agent_node_module.Node()
    result = node.on_input(
        "hello",
        {
            "graph_id": "g_working_path_unit",
            "node_instance_id": "n_working_path_unit",
            "provider_id": "provider-stream",
            "working_path": r"C:\Project\AgentPark\XYJ",
        },
    )

    assert str(result.get("display") or "") == "ok"
    system_messages = [item for item in created_agents[0].messages if item.get("role") == "system"]
    assert not any("C:\\Project\\AgentPark\\XYJ" in str(item.get("content") or "") for item in system_messages)
    assert created_agents[0]._agentpark_working_path == r"C:\Project\AgentPark\XYJ"
    sent_user = next(item for item in created_agents[0].messages if item.get("role") == "user")
    assert sent_user.get("content") == "hello"


def test_agent_node_surfaces_configured_tool_load_failure(monkeypatch):
    import nodes.agent_node as agent_node_module
    from src.tool.tool_load_errors import ToolLoadError

    class DummyAgent:
        def __init__(self):
            self.messages = []

        def addTool(self, name):
            raise ToolLoadError(f"bad tool: {name}")

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            raise AssertionError("Send should not run when configured tools fail to load")

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    node = agent_node_module.Node()
    with pytest.raises(RuntimeError) as exc:
        node.on_input(
            "hello",
            {
                "graph_id": "g_bad_tool_unit",
                "node_instance_id": "n_bad_tool_unit",
                "provider_id": "provider-stream",
                "tools": ["missing_tool"],
            },
        )

    assert "Configured tools failed to load" in str(exc.value)
    assert "bad tool: missing_tool" in str(exc.value)


def test_agent_node_injects_configured_skill_without_affecting_unconfigured_nodes(monkeypatch, tmp_path):
    import nodes.agent_node as agent_node_module
    import nodes.agent_skill_loader as skill_loader

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())
    _write_agent_node_test_skill(tmp_path)
    monkeypatch.setattr(
        agent_node_module,
        "load_node_skills",
        lambda values, *args, **kwargs: skill_loader.load_node_skills(
            values,
            *args,
            skill_root=str(tmp_path),
            **kwargs,
        ),
    )

    node = agent_node_module.Node()
    first = node.on_input(
        "hello",
        {
            "graph_id": "g_skill_unit",
            "node_instance_id": "n_with_skill",
            "provider_id": "provider-stream",
            "skills": ["ue5-cpp-gameplay"],
        },
    )
    second = node.on_input(
        "hello",
        {
            "graph_id": "g_skill_unit",
            "node_instance_id": "n_without_skill",
            "provider_id": "provider-stream",
        },
    )

    assert str(first.get("display") or "") == "ok"
    assert str(second.get("display") or "") == "ok"
    skill_system = next(
        item for item in created_agents[0].messages if "<skills_instructions>" in str(item.get("content") or "")
    )
    assert skill_system["role"] == "system"
    assert skill_system["persist"] is False
    assert "<name>ue5-cpp-gameplay</name>" in skill_system["content"]
    assert not any("<skills_instructions>" in str(item.get("content") or "") for item in created_agents[1].messages)


def test_agent_node_preserves_system_prompt_when_injecting_skill(monkeypatch, tmp_path):
    import nodes.agent_node as agent_node_module
    import nodes.agent_skill_loader as skill_loader

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())
    _write_agent_node_test_skill(tmp_path)
    monkeypatch.setattr(
        agent_node_module,
        "load_node_skills",
        lambda values, *args, **kwargs: skill_loader.load_node_skills(
            values,
            *args,
            skill_root=str(tmp_path),
            **kwargs,
        ),
    )

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_skill_system_unit",
            "node_instance_id": "n_skill_system_unit",
            "provider_id": "provider-stream",
            "system_prompt": "You are the node system prompt.",
            "skills": ["ue5-cpp-gameplay"],
        },
    )

    assert str(result.get("display") or "") == "ok"
    system_messages = [msg for msg in created_agents[0].messages if msg.get("role") == "system"]
    assert "You are the node system prompt." in str(system_messages[0].get("content") or "")
    assert "<skills_instructions>" in str(system_messages[1].get("content") or "")


def test_agent_node_disables_provider_internal_memory(monkeypatch):
    import nodes.agent_node as agent_node_module

    captured = {}

    class DummyAgent:
        def __init__(self):
            self.messages = []

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    def fake_create_agent(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return DummyAgent()

    monkeypatch.setattr(agent_node_module, "create_agent", fake_create_agent)

    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_no_provider_memory_unit",
            "node_instance_id": "n_no_provider_memory_unit",
            "provider_id": "provider-stream",
        },
    )

    assert str(result.get("display") or "") == "ok"
    assert captured["kwargs"]["internal_memory_enabled"] is False


def test_agent_node_loads_structured_node_history(monkeypatch):
    import nodes.agent_node as agent_node_module

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    graph_id = "g_history_unit"
    node_id = "n_history_unit"
    node = agent_node_module.Node()
    context = {
        "graph_id": graph_id,
        "node_instance_id": node_id,
        "provider_id": "openai",
    }
    messages_path = node._resolve_messages_path(context)
    os.makedirs(os.path.dirname(messages_path), exist_ok=True)
    with open(messages_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"id": "u1", "role": "user", "parts": [{"type": "text", "text": "old question"}]}) + "\n")
        handle.write(json.dumps({"id": "a1", "role": "assistant", "parts": [{"type": "text", "text": "old answer"}]}) + "\n")
        handle.write(json.dumps({"id": "t1", "role": "tool", "parts": [{"type": "tool_call", "call_id": "call-1"}]}) + "\n")
        handle.write(json.dumps({"id": "current", "role": "user", "parts": [{"type": "text", "text": "current question"}]}) + "\n")

    result = node.on_input(
        {"id": "current", "role": "user", "parts": [{"type": "text", "text": "current question"}]},
        context,
    )

    assert str(result.get("display") or "") == "ok"
    user_assistant_messages = [
        item for item in created_agents[0].messages if item.get("role") in {"user", "assistant"}
    ]
    assert [item["content"] for item in user_assistant_messages] == [
        "old question",
        "old answer",
        "current question",
    ]


def test_agent_node_uses_configured_history_message_limit(monkeypatch):
    import nodes.agent_node as agent_node_module

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    class DummyLoader:
        def get_config(self):
            return {"agentNode": {"historyMessageLimit": 1, "minSendDelayMs": 0}}

        def get_provider_config(self, _provider_id):
            return {}

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())
    monkeypatch.setattr(agent_node_module, "ConfigLoader", lambda: DummyLoader())

    graph_id = "g_history_limit_unit"
    node_id = "n_history_limit_unit"
    node = agent_node_module.Node()
    context = {
        "graph_id": graph_id,
        "node_instance_id": node_id,
        "provider_id": "openai",
    }
    messages_path = node._resolve_messages_path(context)
    os.makedirs(os.path.dirname(messages_path), exist_ok=True)
    with open(messages_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"id": "u1", "role": "user", "parts": [{"type": "text", "text": "old question"}]}) + "\n")
        handle.write(json.dumps({"id": "a1", "role": "assistant", "parts": [{"type": "text", "text": "old answer"}]}) + "\n")
        handle.write(json.dumps({"id": "current", "role": "user", "parts": [{"type": "text", "text": "current question"}]}) + "\n")

    node.on_input(
        {"id": "current", "role": "user", "parts": [{"type": "text", "text": "current question"}]},
        context,
    )

    user_assistant_messages = [
        item for item in created_agents[0].messages if item.get("role") in {"user", "assistant"}
    ]
    assert [item["content"] for item in user_assistant_messages] == [
        "old answer",
        "current question",
    ]


def test_agent_node_persists_assistant_content_returned_with_tool_calls(monkeypatch, tmp_path):
    import nodes.agent_node as agent_node_module

    class DummyAgent:
        def __init__(self):
            self.messages = []

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            note_message = {
                "role": "assistant",
                "content": "I will inspect README before answering.",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
                    }
                ],
            }
            self.Message(
                "assistant",
                note_message["content"],
                tool_calls=note_message["tool_calls"],
            )
            self._agentpark_persist_assistant_tool_call_note(note_message)
            assert messages_path.exists()
            self.Message("tool", "README contents", tool_call_id="call-1", name="read_file")
            self.Message("assistant", "Final answer.")
            return "Final answer."

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    result = agent_node_module.Node().on_input(
        "hello",
        {
            "graph_id": "g_notes_unit",
            "node_instance_id": "n_notes_unit",
            "provider_id": "openai",
            "memory_path": str(memory_path),
            "messages_path": str(messages_path),
        },
    )

    assert str(result.get("display") or "") == "Final answer."
    records = [
        json.loads(line)
        for line in messages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["role"] == "assistant"
    assert records[0]["parts"] == [
        {"type": "text", "text": "I will inspect README before answering."}
    ]
    assert "I will inspect README before answering." in memory_path.read_text(encoding="utf-8")
    assert "Final answer." not in memory_path.read_text(encoding="utf-8")


def test_agent_node_injects_active_goal_context(monkeypatch):
    import nodes.agent_node as agent_node_module

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    node = agent_node_module.Node()
    node.on_input(
        "continue",
        {
            "graph_id": "g_goal_context_unit",
            "node_instance_id": "n_goal_context_unit",
            "provider_id": "openai",
            "goal": "finish the node goal",
            "goal_state": {"status": "active", "reason": "started"},
        },
    )

    goal_messages = [
        item
        for item in created_agents[0].messages
        if item["role"] == "user" and str(item.get("content") or "").startswith('<agentpark_internal_context source="goal">')
    ]
    assert len(goal_messages) == 1
    assert "<objective>\nfinish the node goal\n</objective>" in goal_messages[0]["content"]
    assert "Goal completion audit:" in goal_messages[0]["content"]


def test_agent_node_omits_history_image_payloads(monkeypatch, tmp_path):
    import nodes.agent_node as agent_node_module

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    graph_id = "g_history_image_unit"
    node_id = "n_history_image_unit"
    node = agent_node_module.Node()
    context = {
        "graph_id": graph_id,
        "node_instance_id": node_id,
        "provider_id": "openai",
    }
    image_path = tmp_path / "old.png"
    image_path.write_bytes(b"fake-png")
    messages_path = node._resolve_messages_path(context)
    os.makedirs(os.path.dirname(messages_path), exist_ok=True)
    with open(messages_path, "w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "id": "old-image",
                    "role": "user",
                    "parts": [
                        {"type": "text", "text": "old image question"},
                        {
                            "type": "resource",
                            "resource": {
                                "uri": str(image_path),
                                "kind": "image",
                                "mime": "image/png",
                            },
                        },
                    ],
                }
            )
            + "\n"
        )

    result = node.on_input("current question", context)

    assert str(result.get("display") or "") == "ok"
    history_user = created_agents[0].messages[0]
    assert history_user["role"] == "user"
    assert isinstance(history_user["content"], str)
    assert "old image question" in history_user["content"]
    assert str(image_path) in history_user["content"]
    assert "data:image" not in history_user["content"]


def test_agent_node_surfaces_missing_configured_skill(monkeypatch):
    import nodes.agent_node as agent_node_module

    class DummyAgent:
        def __init__(self):
            self.messages = []

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            raise AssertionError("Send should not run when skill loading fails")

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())

    node = agent_node_module.Node()
    with pytest.raises(RuntimeError) as exc:
        node.on_input(
            "hello",
            {
                "graph_id": "g_missing_skill_unit",
                "node_instance_id": "n_missing_skill",
                "provider_id": "provider-stream",
                "skills": ["missing-skill"],
            },
        )

    message = str(exc.value)
    assert "node n_missing_skill" in message
    assert "skill missing-skill" in message
    assert "SKILL.md does not exist" in message


def test_agent_node_loads_skills_from_persisted_node_config(monkeypatch, tmp_path):
    import nodes.agent_node as agent_node_module
    import nodes.agent_skill_loader as skill_loader

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.messages = []
            created_agents.append(self)

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **_kwargs):
            return "ok"

    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: DummyAgent())
    _write_agent_node_test_skill(tmp_path)
    monkeypatch.setattr(
        agent_node_module,
        "load_node_skills",
        lambda values, *args, **kwargs: skill_loader.load_node_skills(
            values,
            *args,
            skill_root=str(tmp_path),
            **kwargs,
        ),
    )

    graph_id = "g_skill_config_unit"
    node_id = "n_skill_config_unit"
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(agent_node_module.__file__)))
    agent_dir = os.path.join(base_dir, "memories", graph_id, node_id)
    os.makedirs(agent_dir, exist_ok=True)
    with open(os.path.join(agent_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"skills": ["ue5-cpp-gameplay"]}, f)

    try:
        result = agent_node_module.Node().on_input(
            "hello",
            {
                "graph_id": graph_id,
                "node_instance_id": node_id,
                "provider_id": "provider-stream",
            },
        )
    finally:
        try:
            os.remove(os.path.join(agent_dir, "config.json"))
        except OSError:
            pass

    assert str(result.get("display") or "") == "ok"
    assert any("<skills_instructions>" in str(item.get("content") or "") for item in created_agents[0].messages)


def test_graph_runner_updates_last_message_during_stream(monkeypatch, tmp_path):
    import src.web_backend as backend
    import nodes.agent_node as agent_node_module
    import src.providers as providers_module
    import src.web_backend.runtime_paths as runtime_paths_module
    import src.web_backend.node_runtime as node_runtime_module

    runtime_root = str(tmp_path)
    original_get_runtime_root = backend._get_runtime_root
    original_get_resource_root = backend._get_resource_root
    original_runtime_paths_get_runtime_root = runtime_paths_module._get_runtime_root
    original_runtime_paths_get_resource_root = runtime_paths_module._get_resource_root
    original_node_runtime_get_runtime_root = node_runtime_module._get_runtime_root
    original_node_runtime_get_resource_root = node_runtime_module._get_resource_root
    resource_root = original_get_runtime_root()

    class SlowStreamingAgent:
        def __init__(self):
            self.messages = []

        def addTool(self, _name):
            return None

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

        def Send(self, **kwargs):
            handler = kwargs.get("stream_handler")
            if callable(handler):
                handler("H", "H")
                time.sleep(0.5)
            if callable(getattr(self, "tool_event_callback", None)):
                self.tool_event_callback(
                    {
                        "type": "tool_call_start",
                        "name": "read_file",
                        "call_id": "call-1",
                        "provider": "unit",
                        "arguments": {"filePath": "README.md"},
                    }
                )
                time.sleep(0.05)
                self.tool_event_callback(
                    {
                        "type": "tool_call_end",
                        "name": "read_file",
                        "call_id": "call-1",
                        "provider": "unit",
                        "status": "completed",
                        "duration_ms": 2,
                        "result_preview": "ok",
                    }
                )
                time.sleep(0.05)
            if callable(handler):
                handler("i", "Hi")
            time.sleep(0.1)
            return "Hi"

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root
    runtime_paths_module._get_runtime_root = lambda: runtime_root
    runtime_paths_module._get_resource_root = lambda: resource_root
    node_runtime_module._get_runtime_root = lambda: runtime_root
    node_runtime_module._get_resource_root = lambda: resource_root
    monkeypatch.setattr(providers_module, "create_agent", lambda *_args, **_kwargs: SlowStreamingAgent())
    monkeypatch.setattr(agent_node_module, "create_agent", lambda *_args, **_kwargs: SlowStreamingAgent())

    try:
        app = backend.create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)

        graph = {"id": "default", "name": "default", "output_routes": {}}
        assert client.post("/api/graphs/default", json={"graph": graph}).status_code == 200
        assert (
            client.post(
                "/api/nodes/instances",
                json={"node_id": "agent1", "type_id": "agent_node", "graph_id": "default"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/nodes/instances/agent1/config?graph_id=default",
                json={"fields": {"provider_id": "doubao-2.0-pro"}},
            ).status_code
            == 200
        )
        assert client.post("/api/graphs/default/runner/start").status_code == 200
        assert client.post("/api/graphs/default/emit", json={"from_id": "agent1", "payload": "hello"}).status_code == 200

        saw_partial_live_output = False
        saw_tool_event = False
        saw_tool_event_without_message_override = False
        saw_runtime_history = False
        saw_runtime_tool_call = False
        saw_runtime_event_cleared = False
        saw_final = False
        for _ in range(80):
            cfgs = client.get("/api/nodes/instances/configs?graph_id=default")
            assert cfgs.status_code == 200
            nodes = cfgs.json().get("nodes") or []
            cfg = next((item for item in nodes if str(item.get("node_id") or "") == "agent1"), None)
            if not isinstance(cfg, dict):
                time.sleep(0.05)
                continue
            state = str(cfg.get("state") or "idle")
            last_message = str(cfg.get("last_message") or "")
            live = client.get("/api/nodes/instances/agent1/live?graph_id=default")
            assert live.status_code == 200
            live_message = str((live.json() or {}).get("live_message") or "")
            if state == "working" and live_message == "H":
                saw_partial_live_output = True
            last_runtime_event = cfg.get("last_runtime_event")
            if isinstance(last_runtime_event, dict) and last_runtime_event.get("name") == "read_file":
                saw_tool_event = True
                if state == "working" and last_message != str(last_runtime_event.get("message") or ""):
                    saw_tool_event_without_message_override = True
            runtime_events = cfg.get("runtime_events")
            if isinstance(runtime_events, list) and len(runtime_events) >= 2:
                names = [item.get("name") for item in runtime_events if isinstance(item, dict)]
                types = [item.get("type") for item in runtime_events if isinstance(item, dict)]
                if "read_file" in names and "tool_call_start" in types and "tool_call_end" in types:
                    saw_runtime_history = True
            runtime_tool_calls = cfg.get("runtime_tool_calls")
            if isinstance(runtime_tool_calls, list):
                call = next((item for item in runtime_tool_calls if isinstance(item, dict) and item.get("call_id") == "call-1"), None)
                if isinstance(call, dict) and call.get("name") == "read_file" and call.get("status") == "completed":
                    saw_runtime_tool_call = True
            if str(cfg.get("last_run_at") or "").strip() and last_message == "Hi":
                saw_runtime_event_cleared = cfg.get("last_runtime_event") is None
                runtime_events = cfg.get("runtime_events")
                if isinstance(runtime_events, list) and len(runtime_events) >= 2:
                    saw_runtime_history = True
                runtime_tool_calls = cfg.get("runtime_tool_calls")
                if isinstance(runtime_tool_calls, list):
                    call = next((item for item in runtime_tool_calls if isinstance(item, dict) and item.get("call_id") == "call-1"), None)
                    if isinstance(call, dict) and call.get("name") == "read_file" and call.get("status") == "completed":
                        saw_runtime_tool_call = True
                saw_final = True
                break
            time.sleep(0.05)

        assert saw_partial_live_output, "expected partial stream text in live output while node is working"
        assert saw_tool_event, "expected structured tool lifecycle event in node config"
        assert saw_tool_event_without_message_override, "expected tool lifecycle event to preserve streamed assistant text"
        assert saw_runtime_history, "expected bounded tool lifecycle history in node config"
        assert saw_runtime_tool_call, "expected grouped runtime tool call item in node config"
        assert saw_runtime_event_cleared, "expected tool lifecycle event to clear after final output"
        assert saw_final, "expected final message and last_run_at after completion"

        mem = client.get("/api/nodes/instances/agent1/memory?graph_id=default&max_chars=20000")
        assert mem.status_code == 200
        body = mem.json() or {}
        messages = body.get("messages") or []
        assert any(str(item.get("role") or "") == "assistant" for item in messages if isinstance(item, dict))
        tool_messages = [item for item in messages if isinstance(item, dict) and str(item.get("role") or "") == "tool"]
        assert tool_messages, "expected tool lifecycle item persisted in node message history"
        tool_parts = [part for item in tool_messages for part in (item.get("parts") or []) if isinstance(part, dict)]
        tool_part = next((part for part in tool_parts if part.get("type") == "tool_call" and part.get("call_id") == "call-1"), None)
        assert isinstance(tool_part, dict)
        assert tool_part.get("name") == "read_file"
        assert tool_part.get("status") == "completed"
        assert tool_part.get("result_preview") == "ok"
    finally:
        backend._get_runtime_root = original_get_runtime_root
        backend._get_resource_root = original_get_resource_root
        runtime_paths_module._get_runtime_root = original_runtime_paths_get_runtime_root
        runtime_paths_module._get_resource_root = original_runtime_paths_get_resource_root
        node_runtime_module._get_runtime_root = original_node_runtime_get_runtime_root
        node_runtime_module._get_resource_root = original_node_runtime_get_resource_root

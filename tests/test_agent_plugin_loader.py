import pytest

from src.capabilities.discovery_cache import invalidate_discovery_cache


def _write_plugin_manifest(plugin_dir, filename="agentpark.plugin.json", payload=None):
    import json

    plugin_dir.mkdir(parents=True, exist_ok=True)
    path = plugin_dir / filename
    path.write_text(json.dumps(payload or {}, ensure_ascii=False), encoding="utf-8")
    return path


def _write_skill(root, name="demo"):
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo skill\n---\n\nUse demo.\n",
        encoding="utf-8",
    )
    return skill_dir


def _write_plugin_tool(tool_dir, filename="local_tools.py"):
    tool_dir.mkdir(parents=True, exist_ok=True)
    path = tool_dir / filename
    path.write_text(
        "\n".join(
            [
                "def local_echo(text, agent=None):",
                "    return {'echo': text}",
                "",
                "local_echo_declaration = {",
                "    'type': 'function',",
                "    'function': {",
                "        'name': 'local_echo',",
                "        'description': 'Echo text from a plugin-local tool.',",
                "        'parameters': {",
                "            'type': 'object',",
                "            'properties': {'text': {'type': 'string'}},",
                "            'required': ['text'],",
                "        },",
                "    },",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_plugin_options_list_manifest_directories(tmp_path):
    from nodes.agent_plugin_loader import list_available_plugin_options

    _write_plugin_manifest(
        tmp_path / "core-dev",
        payload={"id": "core-dev", "name": "Core Dev", "description": "Project tools", "version": "1.0.0"},
    )

    assert list_available_plugin_options(str(tmp_path)) == [
        {"value": "core-dev", "label": "Core Dev - Project tools", "version": "1.0.0"}
    ]


def test_plugin_option_discovery_cache_refreshes_on_explicit_invalidation(tmp_path):
    from nodes.agent_plugin_loader import list_available_plugin_options

    manifest_path = _write_plugin_manifest(
        tmp_path / "core-dev",
        payload={"id": "core-dev", "name": "Core Dev", "description": "First"},
    )
    invalidate_discovery_cache("plugins", str(tmp_path))

    first = list_available_plugin_options(str(tmp_path))
    manifest_path.write_text(
        '{"id":"core-dev","name":"Core Dev","description":"Second"}',
        encoding="utf-8",
    )
    cached = list_available_plugin_options(str(tmp_path))
    invalidate_discovery_cache("plugins", str(tmp_path))
    refreshed = list_available_plugin_options(str(tmp_path))

    assert first == [{"value": "core-dev", "label": "Core Dev - First"}]
    assert cached == first
    assert refreshed == [{"value": "core-dev", "label": "Core Dev - Second"}]


def test_resolve_plugin_capabilities_reads_agentpark_manifest(tmp_path):
    from nodes.agent_plugin_loader import resolve_plugin_capabilities

    _write_plugin_manifest(
        tmp_path / "core-dev",
        payload={
            "id": "core-dev",
            "name": "Core Dev",
            "version": "1.2.3",
            "tools": ["file_read_tools", "rg_tools", "file_read_tools"],
            "skills": ["control-in-app-browser"],
            "mcpServers": ["docs", "docs"],
            "configSchema": {"enabled": {"type": "boolean"}},
        },
    )

    capabilities = resolve_plugin_capabilities(["core-dev"], plugin_root=str(tmp_path))

    assert len(capabilities.plugins) == 1
    assert capabilities.plugins[0].version == "1.2.3"
    assert capabilities.plugins[0].source_format == "agentpark"
    assert capabilities.plugins[0].config_schema == {"enabled": {"type": "boolean"}}
    assert capabilities.tools == ("file_read_tools", "rg_tools")
    assert capabilities.skills == ("control-in-app-browser",)
    assert capabilities.mcp_servers == ("docs",)
    assert capabilities.mcp_server_configs == {}


def test_resolve_plugin_capabilities_reads_openclaw_style_manifest_and_local_skills(tmp_path):
    from nodes.agent_plugin_loader import resolve_plugin_capabilities

    plugin_dir = tmp_path / "browser"
    _write_skill(plugin_dir / "skills", "inspect")
    _write_plugin_manifest(
        plugin_dir,
        filename="openclaw.plugin.json",
        payload={
            "id": "browser",
            "name": "Browser",
            "contracts": {"tools": ["browser_tools"]},
            "skills": ["./skills"],
            "mcp": {"servers": ["browser-mcp"]},
        },
    )

    capabilities = resolve_plugin_capabilities(["browser"], plugin_root=str(tmp_path))

    assert capabilities.tools == ("browser_tools",)
    assert capabilities.skills == ()
    assert capabilities.mcp_servers == ("browser-mcp",)
    assert capabilities.plugins[0].source_format == "openclaw"
    assert len(capabilities.skill_definitions) == 1
    assert capabilities.skill_definitions[0].name == "demo"
    assert "Use demo." in capabilities.skill_definitions[0].content


def test_resolve_plugin_capabilities_reads_local_tool_definitions(tmp_path):
    from nodes.agent_plugin_loader import resolve_plugin_capabilities

    plugin_dir = tmp_path / "local-tools"
    tool_path = _write_plugin_tool(plugin_dir / "tools")
    _write_plugin_manifest(
        plugin_dir,
        payload={
            "id": "local-tools",
            "tools": ["./tools"],
        },
    )

    capabilities = resolve_plugin_capabilities(["local-tools"], plugin_root=str(tmp_path))

    assert capabilities.tools == ()
    assert len(capabilities.tool_definitions) == 1
    assert capabilities.tool_definitions[0].name == "plugin__local-tools__local_echo"
    assert capabilities.tool_definitions[0].source_name == "local_echo"
    assert capabilities.tool_definitions[0].path == str(tool_path)
    assert capabilities.tool_definitions[0].callable(text="ok") == {"echo": "ok"}
    assert capabilities.tool_definitions[0].declaration["function"]["name"] == "plugin__local-tools__local_echo"


def test_plugin_local_tool_path_cannot_escape_plugin_root(tmp_path):
    from nodes.agent_plugin_loader import PluginLoadError, resolve_plugin_capabilities

    _write_plugin_manifest(
        tmp_path / "bad-tool",
        payload={"id": "bad-tool", "tools": ["./../tools"]},
    )

    with pytest.raises(PluginLoadError) as exc:
        resolve_plugin_capabilities(["bad-tool"], plugin_root=str(tmp_path))

    assert "plugin tool path escapes plugin root" in str(exc.value)


def test_resolve_plugin_capabilities_reads_inline_mcp_server_configs(tmp_path):
    from nodes.agent_plugin_loader import resolve_plugin_capabilities

    plugin_dir = tmp_path / "inline-mcp"
    _write_plugin_manifest(
        plugin_dir,
        payload={
            "id": "inline-mcp",
            "mcpServers": {
                "probe": {
                    "transport": "stdio",
                    "command": "./bin/probe.py",
                    "args": ["./server.py"],
                },
                "disabled": {
                    "enabled": False,
                    "command": "./disabled.py",
                },
            },
        },
    )

    capabilities = resolve_plugin_capabilities(["inline-mcp"], plugin_root=str(tmp_path))

    assert capabilities.mcp_servers == ("probe",)
    assert "disabled" not in capabilities.mcp_server_configs
    assert capabilities.mcp_server_configs["probe"]["command"] == str(plugin_dir / "bin" / "probe.py")
    assert capabilities.mcp_server_configs["probe"]["args"] == [str(plugin_dir / "server.py")]
    assert capabilities.mcp_server_configs["probe"]["cwd"] == str(plugin_dir)


def test_plugin_mcp_relative_path_cannot_escape_plugin_root(tmp_path):
    from nodes.agent_plugin_loader import PluginLoadError, resolve_plugin_capabilities

    _write_plugin_manifest(
        tmp_path / "bad-mcp",
        payload={
            "id": "bad-mcp",
            "mcpServers": {
                "probe": {
                    "transport": "stdio",
                    "command": "./../probe.py",
                }
            },
        },
    )

    with pytest.raises(PluginLoadError) as exc:
        resolve_plugin_capabilities(["bad-mcp"], plugin_root=str(tmp_path))

    assert "plugin MCP path escapes plugin root" in str(exc.value)


def test_resolve_plugin_capabilities_reads_file_backed_mcp_server_configs(tmp_path):
    from nodes.agent_plugin_loader import resolve_plugin_capabilities

    plugin_dir = tmp_path / "file-mcp"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / ".mcp.json").write_text(
        '{"mcpServers":{"probe":{"transport":"stdio","command":"python","args":["./probe.py"]}}}',
        encoding="utf-8",
    )
    _write_plugin_manifest(
        plugin_dir,
        payload={
            "id": "file-mcp",
            "mcpServers": "./.mcp.json",
        },
    )

    capabilities = resolve_plugin_capabilities(["file-mcp"], plugin_root=str(tmp_path))

    assert capabilities.mcp_servers == ("probe",)
    assert capabilities.mcp_server_configs["probe"]["command"] == "python"
    assert capabilities.mcp_server_configs["probe"]["args"] == [str(plugin_dir / "probe.py")]


def test_resolve_plugin_capabilities_rejects_conflicting_mcp_server_configs(tmp_path):
    from nodes.agent_plugin_loader import PluginLoadError, resolve_plugin_capabilities

    _write_plugin_manifest(
        tmp_path / "left",
        payload={"id": "left", "mcpServers": {"probe": {"command": "left"}}},
    )
    _write_plugin_manifest(
        tmp_path / "right",
        payload={"id": "right", "mcpServers": {"probe": {"command": "right"}}},
    )

    with pytest.raises(PluginLoadError) as exc:
        resolve_plugin_capabilities(["left", "right"], plugin_root=str(tmp_path))

    assert "conflicting MCP server config for probe" in str(exc.value)


def test_resolve_plugin_capabilities_rejects_invalid_config_schema(tmp_path):
    from nodes.agent_plugin_loader import PluginLoadError, resolve_plugin_capabilities

    _write_plugin_manifest(
        tmp_path / "bad-schema",
        payload={"id": "bad-schema", "configSchema": []},
    )

    with pytest.raises(PluginLoadError) as exc:
        resolve_plugin_capabilities(["bad-schema"], plugin_root=str(tmp_path))

    assert "configSchema must be an object" in str(exc.value)


def test_plugin_skill_path_cannot_escape_plugin_root(tmp_path):
    from nodes.agent_plugin_loader import PluginLoadError, resolve_plugin_capabilities

    _write_plugin_manifest(
        tmp_path / "bad",
        payload={"id": "bad", "skills": ["./../outside"]},
    )

    with pytest.raises(PluginLoadError) as exc:
        resolve_plugin_capabilities(["bad"], plugin_root=str(tmp_path))

    assert "plugin skill path escapes plugin root" in str(exc.value)

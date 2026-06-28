from nodes.agent_plugin_loader import PluginDefinition
from nodes.agent_skill_loader import SkillDefinition
from src.capabilities.registry import CapabilityRegistry


def test_capability_registry_reports_skill_mcp_dependencies(monkeypatch):
    import src.capabilities.registry as registry_module

    monkeypatch.setattr(
        registry_module,
        "list_available_skill_options",
        lambda: [{"value": "docs", "label": "Docs", "version": "1.2.3"}],
    )
    monkeypatch.setattr(
        registry_module,
        "load_node_skills",
        lambda _names: [
            SkillDefinition(
                name="docs",
                description="Docs skill",
                path="skills/docs/SKILL.md",
                content="body",
                version="1.2.3",
                mcp_servers=("docs-mcp",),
            )
        ],
    )

    payload = CapabilityRegistry().discover_payload({"skills": ["docs"]})

    assert payload["skill"]["schema_version"] == 1
    descriptor = payload["skill"]["descriptors"][0]
    assert descriptor["id"] == "docs"
    assert descriptor["version"] == "1.2.3"
    assert descriptor["enabled"] is True
    assert descriptor["status"] == "selected"
    assert descriptor["dependencies"] == [{"kind": "mcp", "id": "docs-mcp"}]


def test_capability_registry_reports_plugin_contributions(monkeypatch):
    import src.capabilities.registry as registry_module

    monkeypatch.setattr(
        registry_module,
        "list_available_plugin_options",
        lambda: [{"value": "demo", "label": "Demo Plugin", "version": "2.0.0"}],
    )
    monkeypatch.setattr(
        registry_module,
        "load_node_plugins",
        lambda _names: [
            PluginDefinition(
                id="demo",
                name="Demo Plugin",
                description="Demo",
                path="plugins/demo/aitools.plugin.json",
                version="2.0.0",
                tools=("file_read_tools",),
                skills=("docs",),
                mcp_servers=("docs-mcp",),
                config_schema={"enabled": {"type": "boolean"}},
            )
        ],
    )

    payload = CapabilityRegistry().discover_payload({"plugins": ["demo"]})

    descriptor = payload["plugin"]["descriptors"][0]
    assert descriptor["source"] == "plugin"
    assert descriptor["version"] == "2.0.0"
    assert descriptor["status"] == "selected"
    assert descriptor["config_schema"] == {"enabled": {"type": "boolean"}}
    assert {"kind": "tool", "id": "file_read_tools"} in descriptor["dependencies"]
    assert {"kind": "skill", "id": "docs"} in descriptor["dependencies"]
    assert {"kind": "mcp", "id": "docs-mcp"} in descriptor["dependencies"]
    option = payload["plugin"]["available"][0]
    assert option["kind"] == "plugin"
    assert option["version"] == "2.0.0"
    assert option["source"] == "plugin"
    assert option["status"] == "selected"
    assert option["effective"] == "next_agent_run"
    assert option["config_schema"] == {"enabled": {"type": "boolean"}}
    assert {"kind": "mcp", "id": "docs-mcp"} in option["dependencies"]


def test_capability_registry_reports_mcp_lifecycle_failure(monkeypatch):
    import src.capabilities.registry as registry_module
    from src.mcp.lifecycle import mark_mcp_failed, reset_mcp_lifecycle

    monkeypatch.setattr(
        registry_module,
        "list_available_mcp_server_options",
        lambda: [{"value": "docs", "label": "Docs (stdio)"}],
    )
    reset_mcp_lifecycle()
    mark_mcp_failed("docs", "startup boom", transport="stdio")

    payload = CapabilityRegistry().discover_payload({"mcp_servers": ["docs"]})

    descriptor = payload["mcp"]["descriptors"][0]
    assert descriptor["id"] == "docs"
    assert descriptor["status"] == "error"
    assert "mcp lifecycle: failed" in descriptor["diagnostics"]
    assert "startup boom" in descriptor["diagnostics"]

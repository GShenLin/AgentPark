import json
from types import SimpleNamespace

import pytest

from nodes import agent_plugin_loader as loader
from src.capabilities import registry as registry_module
from src.capabilities.discovery_cache import invalidate_discovery_cache
from src.capabilities.registry import CapabilityRegistry


def write_manifest(root, name, content):
    path = root / name / "agentpark.plugin.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    root = tmp_path / "plugins"
    broken = write_manifest(root, "broken", "{bad")
    write_manifest(root, "healthy", '{"id":"different-id","name":"Healthy"}')
    monkeypatch.setattr(registry_module, "list_available_plugin_options", lambda: loader.list_available_plugin_options(str(root)))
    # Keep these tests independent of the workspace's other capability catalogs.
    monkeypatch.setattr(registry_module, "list_available_tool_options", lambda: [])
    monkeypatch.setattr(registry_module, "list_available_mcp_server_options", lambda: [])
    monkeypatch.setattr(registry_module, "list_available_skill_options", lambda: [])
    return root, broken


@pytest.mark.parametrize("content", ['{bad', '{"name":"No ID"}', '{"id":"x","tools":42}'])
def test_invalid_manifest_is_reported_without_hiding_healthy_plugin(tmp_path, content):
    broken = write_manifest(tmp_path, "broken", content)
    write_manifest(tmp_path, "healthy", '{"id":"another-id","name":"Healthy"}')
    options = {item["value"]: item for item in loader.list_available_plugin_options(str(tmp_path))}
    assert options["healthy"] == {"value": "healthy", "label": "Healthy"}
    assert options["broken"]["status"] == "unavailable"
    diagnostic = options["broken"]["diagnostics"][0]
    assert str(broken) in diagnostic
    assert "manifest discovery" in diagnostic
    assert "PluginManifestError" in diagnostic
    assert str(content) not in diagnostic  # Report the reason, not the entire source document.


@pytest.mark.parametrize("error", [PermissionError("access denied"), UnicodeError("invalid encoding")])
def test_manifest_read_errors_keep_path_type_and_reason(tmp_path, monkeypatch, error):
    path = write_manifest(tmp_path, "broken", '{}')

    def fail(_path):
        raise error

    monkeypatch.setattr(loader, "read_plugin_manifest", fail)
    option = loader.list_available_plugin_options(str(tmp_path))[0]
    assert option["status"] == "unavailable"
    assert str(path) in option["diagnostics"][0]
    assert type(error).__name__ in option["diagnostics"][0]
    assert str(error) in option["diagnostics"][0]


def test_unexpected_programming_errors_are_not_hidden(tmp_path, monkeypatch):
    write_manifest(tmp_path, "broken", '{}')

    def fail(_path):
        raise RuntimeError("programming defect")

    monkeypatch.setattr(loader, "read_plugin_manifest", fail)
    with pytest.raises(RuntimeError, match="programming defect"):
        loader.list_available_plugin_options(str(tmp_path))


@pytest.mark.parametrize("selected", [[], ["broken"]])
def test_registry_preserves_discovery_diagnostics_without_loading_broken_plugin(catalog, monkeypatch, selected):
    def unexpected_load(*args, **kwargs):
        pytest.fail("invalid manifest must not be loaded again")

    monkeypatch.setattr(registry_module, "load_node_plugins", unexpected_load)
    payload = CapabilityRegistry().discover_payload({"plugins": selected}, kinds=["plugin"])["plugin"]
    option = next(item for item in payload["available"] if item["value"] == "broken")
    descriptor = next(item for item in payload["descriptors"] if item["id"] == "broken")
    assert option["status"] == descriptor["status"] == "unavailable"
    assert option["diagnostics"] == descriptor["diagnostics"]
    assert "PluginManifestError" in option["diagnostics"][0]
    assert option["enabled"] is bool(selected)
    assert payload["selected"] == selected


def test_fixed_manifest_recovers_after_refresh(catalog):
    root, path = catalog
    assert loader.list_available_plugin_options(str(root))[0]["status"] == "unavailable"
    path.write_text('{"id":"fixed","name":"Fixed"}', encoding="utf-8")
    invalidate_discovery_cache("plugins", str(root))
    options = loader.list_available_plugin_options(str(root))
    fixed = next(item for item in options if item["value"] == "broken")
    assert fixed == {"value": "broken", "label": "Fixed"}
    CapabilityRegistry().validate_requested("plugin", iter(["broken"]))


def test_management_rejects_enable_but_allows_removing_selected_broken_plugin(catalog, tmp_path):
    from functions.capability_management_tools import manage_agent_capabilities

    path = tmp_path / "config.json"
    path.write_text('{"plugins":[]}', encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    result = json.loads(manage_agent_capabilities("enable", "plugin", ["broken"], config_path=str(path)))
    assert result["status"] == "error"
    assert "PluginManifestError" in result["error"]
    assert path.read_text(encoding="utf-8") == before
    path.write_text('{"plugins":["broken"]}', encoding="utf-8")
    result = json.loads(manage_agent_capabilities("disable", "plugin", ["broken"], config_path=str(path)))
    assert result["status"] == "success"
    assert json.loads(path.read_text(encoding="utf-8"))["plugins"] == []


def test_cli_rejects_enable_but_allows_removing_selected_broken_plugin(catalog, tmp_path, monkeypatch):
    from src.cli_commands import capabilities

    path = tmp_path / "config.json"
    path.write_text('{"plugins":[]}', encoding="utf-8")
    monkeypatch.setattr(capabilities, "node_config_path", lambda *args: str(path))
    args = SimpleNamespace(graph="test", node="test", kind="plugin", name=["broken"], capability_action="enable")
    with pytest.raises(ValueError, match="PluginManifestError"):
        capabilities.mutate_capability(args)
    assert json.loads(path.read_text(encoding="utf-8"))["plugins"] == []
    path.write_text('{"plugins":["broken"]}', encoding="utf-8")
    args.capability_action = "disable"
    assert capabilities.mutate_capability(args)["status"] == "success"
    assert json.loads(path.read_text(encoding="utf-8"))["plugins"] == []

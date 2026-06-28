import json

from functions.capability_management_tools import manage_agent_capabilities


class DummyAgent:
    def __init__(self, memory_path):
        self._memory_path = str(memory_path)

    def getMemoryPath(self):
        return self._memory_path


def _write_config(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_manage_agent_capabilities_discovers_available_and_enabled_items(tmp_path):
    config_path = tmp_path / "node" / "config.json"
    _write_config(config_path, {"tools": ["file_read_tools"], "skills": [], "mcp_servers": [], "plugins": []})

    payload = json.loads(manage_agent_capabilities("discover", config_path=str(config_path)))

    assert payload["status"] == "success"
    assert payload["config_path"] == str(config_path)
    tools = payload["capabilities"]["tool"]
    assert tools["field"] == "tools"
    read_file = next(item for item in tools["available"] if item["value"] == "file_read_tools")
    assert read_file["enabled"] is True


def test_manage_agent_capabilities_refresh_invalidates_discovery_cache(monkeypatch, tmp_path):
    import functions.capability_management_tools as capability_tools

    config_path = tmp_path / "node" / "config.json"
    _write_config(config_path, {"tools": []})
    calls = {"count": 0}

    def fake_invalidate():
        calls["count"] += 1

    monkeypatch.setattr(capability_tools, "invalidate_discovery_cache", fake_invalidate)

    payload = json.loads(manage_agent_capabilities("discover", config_path=str(config_path), refresh=True))

    assert calls["count"] == 1
    assert payload["status"] == "success"


def test_manage_agent_capabilities_enable_disable_updates_node_config(tmp_path):
    config_path = tmp_path / "node" / "config.json"
    _write_config(config_path, {"tools": ["file_read_tools"], "skills": [], "mcp_servers": [], "plugins": []})

    enabled = json.loads(
        manage_agent_capabilities("enable", "tool", ["rg_tools", "file_read_tools"], config_path=str(config_path))
    )
    assert enabled["status"] == "success"
    assert enabled["change"]["before"] == ["file_read_tools"]
    assert enabled["change"]["after"] == ["file_read_tools", "rg_tools"]

    disabled = json.loads(manage_agent_capabilities("disable", "tool", ["file_read_tools"], config_path=str(config_path)))
    assert disabled["status"] == "success"

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["tools"] == ["rg_tools"]


def test_manage_agent_capabilities_resolves_config_from_agent_memory_path(tmp_path):
    node_dir = tmp_path / "node"
    memory_path = node_dir / "memory.md"
    config_path = node_dir / "config.json"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text("", encoding="utf-8")
    _write_config(config_path, {"tools": []})

    payload = json.loads(
        manage_agent_capabilities(
            "enable",
            "tool",
            ["file_read_tools"],
            agent=DummyAgent(memory_path),
        )
    )

    assert payload["status"] == "success"
    assert payload["config_path"] == str(config_path)
    assert json.loads(config_path.read_text(encoding="utf-8"))["tools"] == ["file_read_tools"]


def test_manage_agent_capabilities_rejects_unknown_names(tmp_path):
    config_path = tmp_path / "node" / "config.json"
    _write_config(config_path, {"tools": []})
    before = config_path.read_text(encoding="utf-8")

    payload = json.loads(manage_agent_capabilities("enable", "tool", ["missing_tool"], config_path=str(config_path)))

    assert payload["status"] == "error"
    assert payload["exception_type"] == "ValueError"
    assert "unknown tool name" in payload["error"]
    assert config_path.read_text(encoding="utf-8") == before


def test_manage_agent_capabilities_reports_corrupt_config(tmp_path):
    config_path = tmp_path / "node" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("{bad", encoding="utf-8")

    payload = json.loads(manage_agent_capabilities("discover", config_path=str(config_path)))

    assert payload["status"] == "error"
    assert payload["exception_type"] == "NodeConfigFormatError"
    assert "invalid JSON" in payload["error"]


def test_manage_agent_capabilities_rejects_non_object_config(tmp_path):
    config_path = tmp_path / "node" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("[]", encoding="utf-8")

    payload = json.loads(manage_agent_capabilities("enable", "tool", ["file_read_tools"], config_path=str(config_path)))

    assert payload["status"] == "error"
    assert payload["exception_type"] == "NodeConfigFormatError"
    assert "JSON object" in payload["error"]


def test_capability_management_tool_is_not_mixed_into_system_tools():
    import functions.system_tools as system_tools

    assert "manage_agent_capabilities" not in system_tools.__all__
    assert not hasattr(system_tools, "manage_agent_capabilities")

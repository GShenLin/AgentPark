from __future__ import annotations

import os

import pytest

from src.runtime_events.event_config_store import default_event_config
from src.runtime_events.event_registry import EventConfigError, RuntimeEventRegistryManager
from src.runtime_events.event_schema import runtime_event_schema


class _GraphRuntime:
    def _graph_dir(self, graph_id: str) -> str:
        return f"graph/{graph_id}"

    def _node_config_path(self, node_id: str, graph_id: str) -> str:
        return f"graph/{graph_id}/{node_id}/config.json"


class _Core:
    graph_runtime = _GraphRuntime()


def _manager() -> RuntimeEventRegistryManager:
    return RuntimeEventRegistryManager(_Core())


def test_compile_accepts_multiple_rules_for_one_event_source() -> None:
    config = default_event_config()
    config["rules"] = {
        "ToolFailure": {
            "Main": {
                "Worker": [
                    {"action": "context.produce", "target": "builtin.tool_failure_context"},
                    {"action": "notice.write", "target": "builtin.runtime_event_notice"},
                ]
            }
        }
    }

    registry = _manager().compile(config, strict_sources=False)

    rules = registry.rule_index[("Main", "Worker", "ToolFailure")]
    assert [rule.action for rule in rules] == ["context.produce", "notice.write"]
    assert registry.config["rules"]["ToolFailure"]["Main"]["Worker"][0]["action"] == "context.produce"


def test_compile_rejects_single_handler_object() -> None:
    config = default_event_config()
    config["rules"] = {
        "RuntimeNotice": {
            "Main": {
                "Worker": {"action": "context.produce", "target": "builtin.runtime_notice_context"}
            }
        }
    }

    with pytest.raises(EventConfigError) as exc_info:
        _manager().compile(config, strict_sources=False)

    assert any("handlers must be a list" in item["message"] for item in exc_info.value.errors)


def test_compile_rejects_legacy_flat_rules() -> None:
    config = default_event_config()
    config["rules"] = [
        {
            "event": "ToolFailure",
            "source": {"graph_id": "Main", "node_id": "Worker"},
            "action": "context.produce",
            "target": "builtin.tool_failure_context",
        },
        {
            "event": "ToolFailure",
            "source": {"graph_id": "Main", "node_id": "Worker"},
            "action": "notice.write",
            "target": "builtin.runtime_event_notice",
        },
    ]

    with pytest.raises(EventConfigError) as exc_info:
        _manager().compile(config, strict_sources=False)

    assert any("rules must be an object keyed by event" in item["message"] for item in exc_info.value.errors)


def test_compile_preserves_empty_event_handler_list() -> None:
    config = default_event_config()
    config["rules"] = {"ToolFailure": {"Main": {"Worker": []}}}

    registry = _manager().compile(config, strict_sources=False)

    assert registry.config["rules"]["ToolFailure"]["Main"]["Worker"] == []
    assert registry.rule_index == {}


def test_compile_allows_cleanup_when_source_node_no_longer_exists(monkeypatch) -> None:
    config = default_event_config()
    config["rules"] = {
        "WorkPersisted": {
            "default": {
                "GPT1": [
                    {
                        "action": "node.dispatch",
                        "target": "companion",
                        "params": {"profile_id": "legacy-value-that-would-otherwise-fail"},
                    }
                ]
            }
        }
    }
    manager = _manager()
    monkeypatch.setattr(manager, "_node_exists", lambda _graph_id, _node_id: False)

    registry = manager.compile(config, strict_sources=True)

    assert registry.rule_index == {}
    assert registry.config["rules"] == {}
    assert registry.warnings == (
        "rules.WorkPersisted.default.GPT1: source node not found; orphaned handlers were removed",
    )


def test_apply_persists_config_while_unrelated_missing_source_rule_is_inactive(monkeypatch) -> None:
    config = default_event_config()
    config["rules"] = {
        "WorkPersisted": {
            "default": {
                "GPT1": [
                    {
                        "action": "node.dispatch",
                        "target": "companion",
                        "params": {"profile_id": "legacy-value-that-would-otherwise-fail"},
                    }
                ]
            }
        }
    }
    manager = _manager()
    written: list[dict] = []
    monkeypatch.setattr(manager, "_node_exists", lambda _graph_id, _node_id: False)
    monkeypatch.setattr("src.runtime_events.event_registry.write_event_config", lambda payload: written.append(payload))

    result = manager.apply(config)

    assert result["ok"] is True
    assert result["compiled"]["rules"] == 0
    assert result["warnings"]
    assert written[0]["rules"] == {}


def test_startup_removes_and_persists_orphaned_source_rules(monkeypatch) -> None:
    config = default_event_config()
    config["rules"] = {
        "WorkPersisted": {
            "default": {
                "GPT1": [
                    {
                        "action": "context.append_file",
                        "target": "",
                        "params": {"paths": ["missing.md"], "role": "developer"},
                    }
                ]
            }
        }
    }
    manager = _manager()
    written: list[dict] = []
    monkeypatch.setattr(manager, "_node_exists", lambda _graph_id, _node_id: False)
    monkeypatch.setattr("src.runtime_events.event_registry.load_or_create_event_config", lambda: config)
    monkeypatch.setattr("src.runtime_events.event_registry.write_event_config", lambda payload: written.append(payload))

    result = manager.load_startup()

    assert result["ok"] is True
    assert result["warnings"] == [
        "rules.WorkPersisted.default.GPT1: source node not found; orphaned handlers were removed"
    ]
    assert manager.active().rule_index == {}
    assert written == [{**config, "rules": {}}]


def test_runtime_event_schema_is_frontend_consumable() -> None:
    schema = runtime_event_schema()

    assert schema["rules_shape"] == "rules[event][graph_id][node_id] = Handler[]"
    assert "ToolFailure" in schema["events"]
    assert "context.produce" in schema["actions"]
    assert "context.append_file" in schema["actions"]
    assert schema["context_roles"] == ["developer", "system", "user", "assistant"]


@pytest.mark.parametrize("event", ["OnInput", "ToolFailure", "RuntimeNotice", "NetError", "WorkPersisted", "WorkFailed"])
def test_compile_accepts_append_file_for_every_event(event: str) -> None:
    config = default_event_config()
    config["rules"] = {
        event: {
            "Main": {
                "Worker": [
                    {
                        "action": "context.append_file",
                        "target": "",
                        "params": {"paths": ["Soul.md", "Note.md"], "role": "assistant"},
                    }
                ]
            }
        }
    }

    registry = _manager().compile(config, strict_sources=False)

    rule = registry.rule_index[("Main", "Worker", event)][0]
    assert rule.params["paths"] == ["Soul.md", "Note.md"]
    assert rule.params["role"] == "assistant"


def test_compile_accepts_nested_node_relative_append_file_path() -> None:
    config = default_event_config()
    config["rules"] = {
        "OnInput": {
            "Main": {
                "Worker": [
                    {
                        "action": "context.append_file",
                        "target": "",
                        "params": {"paths": ["context/project.md"]},
                    }
                ]
            }
        }
    }

    registry = _manager().compile(config, strict_sources=False)

    assert registry.rule_index[("Main", "Worker", "OnInput")][0].params["paths"] == ["context/project.md"]
    assert registry.rule_index[("Main", "Worker", "OnInput")][0].params["role"] == "developer"


def test_compile_rejects_invalid_append_file_role() -> None:
    config = default_event_config()
    config["rules"] = {
        "OnInput": {
            "Main": {
                "Worker": [
                    {
                        "action": "context.append_file",
                        "target": "",
                        "params": {"paths": ["Soul.md"], "role": "tool"},
                    }
                ]
            }
        }
    }

    with pytest.raises(EventConfigError) as exc_info:
        _manager().compile(config, strict_sources=False)

    assert any("params.role must be developer, system, user, or assistant" in item["message"] for item in exc_info.value.errors)


def test_compile_accepts_append_file_path_outside_node() -> None:
    config = default_event_config()
    config["rules"] = {
        "OnInput": {
            "Main": {
                "Worker": [
                    {
                        "action": "context.append_file",
                        "target": "",
                        "params": {"paths": ["../User.md"]},
                    }
                ]
            }
        }
    }

    registry = _manager().compile(config, strict_sources=False)

    assert registry.rule_index[("Main", "Worker", "OnInput")][0].params["paths"] == ["../User.md"]


def test_compile_accepts_absolute_append_file_path(tmp_path) -> None:
    context_file = tmp_path / "shared" / "User.md"
    config = default_event_config()
    config["rules"] = {
        "OnInput": {
            "Main": {
                "Worker": [
                    {
                        "action": "context.append_file",
                        "target": "",
                        "params": {"paths": [str(context_file)]},
                    }
                ]
            }
        }
    }

    registry = _manager().compile(config, strict_sources=False)

    assert registry.rule_index[("Main", "Worker", "OnInput")][0].params["paths"] == [os.path.normpath(str(context_file))]


def test_compile_ignores_empty_path_on_disabled_append_file() -> None:
    config = default_event_config()
    config["rules"] = {
        "OnInput": {
            "Main": {
                "Worker": [
                    {
                        "enabled": False,
                        "action": "context.append_file",
                        "target": "",
                        "params": {"paths": [], "role": "developer"},
                    }
                ]
            }
        }
    }

    registry = _manager().compile(config, strict_sources=False)

    assert registry.rule_index == {}


def test_compile_rejects_duplicate_append_file_paths() -> None:
    config = default_event_config()
    config["rules"] = {
        "OnInput": {
            "Main": {
                "Worker": [
                    {
                        "action": "context.append_file",
                        "target": "",
                        "params": {"paths": ["Soul.md", "Soul.md"]},
                    }
                ]
            }
        }
    }

    with pytest.raises(EventConfigError) as exc_info:
        _manager().compile(config, strict_sources=False)

    assert any("duplicate context file path: Soul.md" in item["message"] for item in exc_info.value.errors)


def test_compile_rejects_legacy_single_append_file_path() -> None:
    config = default_event_config()
    config["rules"] = {
        "OnInput": {
            "Main": {
                "Worker": [
                    {
                        "action": "context.append_file",
                        "target": "",
                        "params": {"path": "Soul.md"},
                    }
                ]
            }
        }
    }

    with pytest.raises(EventConfigError) as exc_info:
        _manager().compile(config, strict_sources=False)

    assert any("legacy params.path is not supported; use params.paths" in item["message"] for item in exc_info.value.errors)


def test_compile_rejects_legacy_single_dispatch_profile() -> None:
    config = default_event_config()
    config["receiver_groups"] = {
        "companion": {
            "graph_id": "Companion",
            "merge_target": {"graph_id": "Companion", "node_id": "Companion"},
            "receivers": [],
        }
    }
    config["rules"] = {
        "WorkPersisted": {
            "Main": {
                "Worker": [
                    {
                        "action": "node.dispatch",
                        "target": "companion",
                        "params": {"profile_id": "legacy"},
                    }
                ]
            }
        }
    }

    with pytest.raises(EventConfigError) as exc_info:
        _manager().compile(config, strict_sources=False)

    assert any("legacy params.profile_id is not supported" in item["message"] for item in exc_info.value.errors)

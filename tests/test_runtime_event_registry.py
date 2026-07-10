from __future__ import annotations

from src.runtime_events.event_config_store import default_event_config
from src.runtime_events.event_registry import RuntimeEventRegistryManager
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


def test_compile_normalizes_single_rule_object_to_rule_list() -> None:
    config = default_event_config()
    config["rules"] = {
        "RuntimeNotice": {
            "Main": {
                "Worker": {"action": "context.produce", "target": "builtin.runtime_notice_context"}
            }
        }
    }

    registry = _manager().compile(config, strict_sources=False)

    assert len(registry.rule_index[("Main", "Worker", "RuntimeNotice")]) == 1
    assert isinstance(registry.config["rules"]["RuntimeNotice"]["Main"]["Worker"], list)


def test_legacy_flat_rules_append_instead_of_collapsing_duplicates() -> None:
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

    registry = _manager().compile(config, strict_sources=False)

    assert [rule.action for rule in registry.rule_index[("Main", "Worker", "ToolFailure")]] == [
        "context.produce",
        "notice.write",
    ]


def test_runtime_event_schema_is_frontend_consumable() -> None:
    schema = runtime_event_schema()

    assert schema["rules_shape"] == "rules[event][graph_id][node_id] = Rule[]"
    assert "ToolFailure" in schema["events"]
    assert "context.produce" in schema["actions"]

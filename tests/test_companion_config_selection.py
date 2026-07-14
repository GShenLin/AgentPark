from __future__ import annotations


def test_reasoning_choices_uses_current_provider_capability(monkeypatch):
    import src.cli_commands.companion_config_selection as selection

    monkeypatch.setattr(
        selection.ConfigLoader,
        "get_all_providers",
        lambda _self: {
            "provider-a": {
                "features": {
                    "reasoning_effort": {
                        "supported": True,
                        "values": ["low", "medium", "high"],
                    }
                }
            }
        },
    )

    assert selection.reasoning_choices("provider-a") == [
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
    ]


def test_reasoning_choices_is_empty_for_unsupported_provider(monkeypatch):
    import src.cli_commands.companion_config_selection as selection

    monkeypatch.setattr(
        selection.ConfigLoader,
        "get_all_providers",
        lambda _self: {
            "provider-a": {
                "features": {
                    "reasoning_effort": {
                        "supported": False,
                        "values": [],
                    }
                }
            }
        },
    )

    assert selection.reasoning_choices("provider-a") == []


def test_provider_switch_keeps_supported_current_reasoning(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace

    import src.cli_commands.companion_config_selection as selection

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"provider_id": "old", "reasoning_effort": "medium"}),
        encoding="utf-8",
    )
    target = SimpleNamespace(
        config_path=str(config_path),
        config={"provider_id": "old", "reasoning_effort": "medium"},
    )
    monkeypatch.setattr(
        selection.ConfigLoader,
        "get_all_providers",
        lambda _self: {
            "new": {
                "features": {
                    "reasoning_effort": {"supported": True, "values": ["low", "medium", "high"]}
                }
            }
        },
    )

    selected_effort = selection.update_companion_provider(target, "new")

    stored = json.loads(config_path.read_text(encoding="utf-8"))
    assert selected_effort == "medium"
    assert stored["provider_id"] == "new"
    assert stored["reasoning_effort"] == "medium"


def test_provider_switch_uses_provider_default_when_current_reasoning_is_unsupported(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace

    import src.cli_commands.companion_config_selection as selection

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"provider_id": "old", "reasoning_effort": "xhigh"}),
        encoding="utf-8",
    )
    target = SimpleNamespace(
        config_path=str(config_path),
        config={"provider_id": "old", "reasoning_effort": "xhigh"},
    )
    monkeypatch.setattr(
        selection.ConfigLoader,
        "get_all_providers",
        lambda _self: {
            "new": {
                "reasoningEffort": "medium",
                "features": {
                    "reasoning_effort": {"supported": True, "values": ["low", "medium", "high"]}
                },
            }
        },
    )

    selected_effort = selection.update_companion_provider(target, "new")

    stored = json.loads(config_path.read_text(encoding="utf-8"))
    assert selected_effort == "medium"
    assert stored["provider_id"] == "new"
    assert stored["reasoning_effort"] == "medium"


def test_provider_switch_uses_nearest_supported_reasoning_without_default(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace

    import src.cli_commands.companion_config_selection as selection

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"provider_id": "old", "reasoning_effort": "xhigh"}),
        encoding="utf-8",
    )
    target = SimpleNamespace(
        config_path=str(config_path),
        config={"provider_id": "old", "reasoning_effort": "xhigh"},
    )
    monkeypatch.setattr(
        selection.ConfigLoader,
        "get_all_providers",
        lambda _self: {
            "new": {
                "features": {
                    "reasoning_effort": {"supported": True, "values": ["high", "max"]}
                }
            }
        },
    )

    selected_effort = selection.update_companion_provider(target, "new")

    assert selected_effort == "high"
    assert target.config == {"provider_id": "new", "reasoning_effort": "high"}


def test_provider_switch_removes_reasoning_for_provider_without_support(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace

    import src.cli_commands.companion_config_selection as selection

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"provider_id": "old", "reasoning_effort": "high"}),
        encoding="utf-8",
    )
    target = SimpleNamespace(
        config_path=str(config_path),
        config={"provider_id": "old", "reasoning_effort": "high"},
    )
    monkeypatch.setattr(
        selection.ConfigLoader,
        "get_all_providers",
        lambda _self: {
            "new": {
                "features": {
                    "reasoning_effort": {"supported": False, "values": []}
                }
            }
        },
    )

    selected_effort = selection.update_companion_provider(target, "new")

    stored = json.loads(config_path.read_text(encoding="utf-8"))
    assert selected_effort is None
    assert stored["provider_id"] == "new"
    assert "reasoning_effort" not in stored


def test_capability_choices_returns_available_items_and_selected_state(monkeypatch):
    from types import SimpleNamespace

    import src.cli_commands.companion_config_selection as selection

    class Registry:
        def discover_payload(self, config):
            assert config["tools"] == ["tool-a"]
            return {
                "tool": {
                    "selected": ["tool-a"],
                    "available": [
                        {"value": "tool-a", "label": "Tool A"},
                        {"value": "tool-b", "label": "Tool B"},
                    ],
                }
            }

    monkeypatch.setattr(selection, "CapabilityRegistry", Registry)
    target = SimpleNamespace(config={"tools": ["tool-a"]})

    choices, selected = selection.capability_choices(target, "tool")

    assert choices == [("tool-a", "Tool A"), ("tool-b", "Tool B")]
    assert selected == {"tool-a"}


def test_toggle_capability_removes_existing_and_adds_missing(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace

    import src.cli_commands.companion_config_selection as selection

    validations = []

    class Registry:
        def validate_requested(self, kind, names, config):
            validations.append((kind, names, list(config.get("tools") or [])))

    monkeypatch.setattr(selection, "CapabilityRegistry", Registry)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"tools": ["tool-a"]}), encoding="utf-8")
    target = SimpleNamespace(config_path=str(config_path), config={"tools": ["tool-a"]})

    enabled_after_remove = selection.toggle_companion_capability(target, "tool", "tool-a")
    enabled_after_add = selection.toggle_companion_capability(target, "tool", "tool-b")

    stored = json.loads(config_path.read_text(encoding="utf-8"))
    assert enabled_after_remove is False
    assert enabled_after_add is True
    assert stored["tools"] == ["tool-b"]
    assert target.config["tools"] == ["tool-b"]
    assert validations == [("tool", ["tool-b"], [])]

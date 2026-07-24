from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


def test_base_agent_import_does_not_eagerly_import_provider_implementations():
    module = importlib.import_module("src.base_agent")

    assert module.BaseAgent.__name__ == "BaseAgent"


def test_provider_registry_loads_only_selected_provider(monkeypatch):
    from src.providers import registry

    captured = []

    class DemoAgent:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    registration = registry.ProviderRegistration("demo", "demo.provider", "DemoAgent")
    monkeypatch.setitem(registry.PROVIDER_REGISTRATIONS, "demo", registration)
    monkeypatch.setattr(registry.ConfigLoader, "get_provider_config", lambda _self, _id: {"type": "demo"})
    monkeypatch.setattr(registry, "import_module", lambda _module: SimpleNamespace(DemoAgent=DemoAgent))

    agent = registry.create_agent(
        "provider-demo",
        memory_file_path="memory.md",
        system_prompt="system",
        internal_memory_enabled=False,
    )

    assert isinstance(agent, DemoAgent)
    assert captured == [
        {
            "provider_id": "provider-demo",
            "memory_file_path": "memory.md",
            "system_prompt": "system",
            "internal_memory_enabled": False,
        }
    ]


def test_provider_registry_rejects_unknown_provider_type(monkeypatch):
    from src.providers import registry

    monkeypatch.setattr(registry.ConfigLoader, "get_provider_config", lambda _self, _id: {"type": "missing"})

    with pytest.raises(ValueError, match="unsupported type: missing"):
        registry.create_agent("provider-missing")

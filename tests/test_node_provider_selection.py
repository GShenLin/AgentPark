"""Agent and Codex expose the same Provider/Model configuration contract."""

import pytest

from nodes.agent_node_contract import AGENT_CONFIG_SCHEMA
from nodes.agent_node_schema import build_agent_config_schema
from nodes.codex_node import Node as CodexNode
from nodes.codex_node.contract import CODEX_CONFIG_SCHEMA


@pytest.mark.parametrize("provider_id,models", [("", []), ("first", ["a", "b"]), ("second", ["c"])])
def test_agent_and_codex_share_model_fields(monkeypatch, tmp_path, provider_id, models):
    monkeypatch.setattr("src.audio_speaker_catalog.AudioSpeakerCatalog._default_path",
                        staticmethod(lambda: str(tmp_path / "audio_speaker.json")))
    providers = {
        "first": {"models": ["a", "b"], "supportmode": ["chat"]},
        "second": {"models": ["c"], "supportmode": ["chat"]},
    }
    monkeypatch.setattr("src.config_loader.ConfigLoader.get_provider_catalog", lambda self: providers)
    monkeypatch.setattr("src.config_loader.ConfigLoader.get_provider_config", lambda self, key: providers[key])
    monkeypatch.setattr("src.audio_speaker_catalog.AudioSpeakerCatalog.get_provider_options", lambda self, key: [])
    monkeypatch.setattr("src.capabilities.registry.CapabilityRegistry.discover_payload", lambda self, context: {})

    context = {"provider_id": provider_id}
    agent = build_agent_config_schema(AGENT_CONFIG_SCHEMA, context)
    codex = CodexNode().get_config_schema(context)
    for schema in (AGENT_CONFIG_SCHEMA, CODEX_CONFIG_SCHEMA, agent, codex):
        assert list(schema)[:2] == ["provider_id", "model"]
    assert codex["model"] == agent["model"]
    assert codex["model"]["options"] == [{"value": model, "label": model} for model in models]
    # Resolving one provider must not mutate the static contracts or other nodes.
    assert AGENT_CONFIG_SCHEMA["model"]["options"] == []
    assert CODEX_CONFIG_SCHEMA["model"]["options"] == []

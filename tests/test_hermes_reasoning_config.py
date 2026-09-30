import json

import pytest

from nodes.hermes_agent_node import Node
from nodes.openclaw_node import Node as OpenClawNode
from nodes.minimax_code_node import Node as MiniMaxNode
from src.harness.config import load_cli_request
from src.harness.contracts import HarnessContext
from src.harness.reasoning_config import reasoning_options, validate_reasoning_effort


@pytest.fixture
def provider(monkeypatch):
    config = {"type": "deepseek", "model": "test", "models": ["test"], "supportmode": ["chat"]}
    monkeypatch.setattr("src.config_loader.ConfigLoader.get_provider_config", lambda self, key: dict(config))
    monkeypatch.setattr("src.harness.node.build_provider_options_for_support_modes", lambda *args, **kwargs: [])
    return config


@pytest.mark.parametrize("node_class", [Node, OpenClawNode, MiniMaxNode])
def test_node_exposes_provider_reasoning_options(provider, node_class):
    schema = node_class().get_config_schema({"provider_id": "p"})
    assert [item["value"] for item in schema["reasoning_effort"]["options"]] == ["", "high", "max"]


@pytest.mark.parametrize("effort", ["high", "max"])
@pytest.mark.parametrize("harness", ["hermes_agent", "openclaw", "minimax_code"])
def test_node_config_owns_effort_without_resetting_conversation(tmp_path, provider, effort, harness):
    path = tmp_path / "config.json"
    context = HarnessContext(str(path), str(tmp_path), {"provider_id": "p", "reasoning_effort": "medium"})
    path.write_text(json.dumps({"reasoning_effort": "high"}), encoding="utf-8")
    before = load_cli_request(harness, context)
    path.write_text(json.dumps({"reasoning_effort": effort}), encoding="utf-8")
    after = load_cli_request(harness, context)
    assert after.reasoning_effort == effort
    assert after.state_dir == before.state_dir


@pytest.mark.parametrize("effort", ["medium", "bogus", 1, None])
def test_unsupported_effort_fails_before_starting_sdk(provider, effort):
    with pytest.raises(ValueError, match="reasoning_effort"):
        validate_reasoning_effort(effort, provider)


def test_providers_without_reasoning_offer_no_explicit_efforts():
    assert reasoning_options({}) == []

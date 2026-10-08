from __future__ import annotations

import json
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from src.harness.config import load_cli_request
from src.harness.contracts import HarnessContext
from src.harness.provider_binding import ProviderBinding
from src.harness.registry import DESCRIPTORS, HARNESS_NODE_TYPES, create_adapter
from src.harness.responses_gateway import HarnessResponsesGateway
from nodes.claude_node.runtime.provider_gateway import ClaudeProviderGateway
from src.cli_provider_runtime.gateway_dispatch import GatewayDispatchResult


@pytest.fixture
def provider(monkeypatch):
    config = {"id": "p", "type": "openai", "model": "first", "models": ["first", "second"],
              "supportmode": ["chat"], "apiKey": "not-for-the-cli", "baseUrl": "https://example.test/v1"}
    monkeypatch.setattr("src.config_loader.ConfigLoader.get_provider_config", lambda self, key: dict(config))
    return config


def test_binding_validates_models_without_exposing_credentials(provider):
    binding = ProviderBinding.resolve("p", "second")
    assert binding.model_id == "second"
    assert binding.request_config()["model"] == "second"
    assert "not-for-the-cli" not in repr(binding)
    with pytest.raises(ValueError, match="not allowed"):
        ProviderBinding.resolve("p", "missing")


def test_gateway_keeps_node_reasoning_per_lease_and_preserves_other_fields(provider, monkeypatch):
    provider["responsesApi"] = True
    captured = []
    def dispatch(config, payload):
        captured.append(payload["reasoning"])
        return GatewayDispatchResult(200, "application/json", json_body={"ok": True})
    monkeypatch.setattr("src.harness.responses_gateway.dispatch_responses", dispatch)
    gateway = HarnessResponsesGateway()
    try:
        for selected, expected in [("max", "max"), ("none", "none"), ("", "low")]:
            lease = gateway.register("p", model="first", reasoning_effort=selected)
            request = urllib.request.Request(lease.base_url + "/responses",
                data=json.dumps({"model": "alias", "reasoning": {"effort": "low", "summary": "auto"}}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=3) as response:
                assert response.status == 200
            assert captured[-1] == {"effort": expected, "summary": "auto"}
            gateway.release(lease.token)
            assert lease.token not in gateway._reasoning_efforts
        with pytest.raises(ValueError, match="reasoning_effort"):
            gateway.register("p", reasoning_effort="invented")
    finally:
        gateway.close()


@pytest.mark.parametrize("gateway_class,patch_path,endpoint", [
    (HarnessResponsesGateway, "src.harness.responses_gateway.dispatch_responses", "/responses"),
    (ClaudeProviderGateway, "nodes.claude_node.runtime.provider_gateway.dispatch_messages", "/v1/messages"),
])
def test_gateway_binds_model_per_lease_and_revokes_access(provider, monkeypatch, gateway_class, patch_path, endpoint):
    captured = []

    def dispatch(config, payload):
        captured.append((config["model"], payload["model"]))
        return GatewayDispatchResult(200, "application/json", json_body={"ok": True})

    monkeypatch.setattr(patch_path, dispatch)
    gateway = gateway_class()
    first = gateway.register("p", model="first")
    second = gateway.register("p", model="second")
    try:
        for lease in [first, second, first]:
            request = urllib.request.Request(lease.base_url + endpoint,
                                             data=json.dumps({"model": "runtime-alias", "messages": []}).encode(),
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=3) as response:
                assert response.status == 200
        assert captured == [("first", "first"), ("second", "second"), ("first", "first")]
        gateway.release(second.token)
        assert second.token not in gateway._models
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(second.base_url + endpoint, data=b"{}"), timeout=3)
        assert error.value.code == 404
    finally:
        gateway.release(first.token)
        gateway.close()


def test_all_registered_nodes_have_concrete_adapters():
    assert len(DESCRIPTORS) == 7
    for item in DESCRIPTORS:
        assert callable(create_adapter(item.id).run)


@pytest.mark.parametrize("module", sorted(HARNESS_NODE_TYPES))
def test_harness_node_schema_exposes_selected_provider_models(provider, module):
    from importlib import import_module
    Node = import_module("nodes." + module).Node
    schema = Node().get_config_schema({"provider_id": "p"})
    assert list(schema)[:2] == ["provider_id", "model"]
    assert schema["model"]["options"] == [{"value": "first", "label": "first"}, {"value": "second", "label": "second"}]


def test_harness_api_routes_are_registered_with_request_validation():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.web_backend.core import BackendCore
    from src.web_backend.route_registry import ApiRouteRegistry
    app = FastAPI()
    core = BackendCore()
    ApiRouteRegistry.register(app, core)
    client = TestClient(app, client=("127.0.0.1", 12345))
    assert client.get("/api/harnesses/unknown").status_code == 404
    assert client.post("/api/harnesses/pi/operations", json={"action": "shell"}).status_code == 422
    assert client.get("/api/harness-jobs/unknown").status_code == 404


def test_cli_state_survives_binding_changes_and_rejects_invalid_access(provider, tmp_path):
    values = {"provider_id": "p", "model": "first", "working_path": str(tmp_path)}
    context = HarnessContext(str(tmp_path / "config.json"), str(tmp_path), values)
    first = load_cli_request("pi", context)
    values["model"] = "second"
    second = load_cli_request("pi", context)
    assert first.state_dir == second.state_dir
    values["provider_id"] = "other"
    assert load_cli_request("pi", context).state_dir == first.state_dir
    values["access_role"] = "nondeveloper"
    with pytest.raises(ValueError, match="developer access"):
        load_cli_request("pi", context)


def test_cli_timeout_contract(provider, tmp_path):
    for invalid in [False, 0, -1, "900", float("nan"), 86401]:
        context = HarnessContext(str(tmp_path / "config.json"), str(tmp_path),
                                 {"provider_id": "p", "timeout_seconds": invalid})
        with pytest.raises(ValueError, match="timeout_seconds"):
            load_cli_request("pi", context)


def test_minimax_permission_mode_is_explicit_and_validated(provider, tmp_path):
    values = {"provider_id": "p", "working_path": str(tmp_path)}
    context = HarnessContext(str(tmp_path / "config.json"), str(tmp_path), values)
    assert load_cli_request("minimax_code", context).permission_mode == "auto"
    for mode in ("default", "auto", "bypassPermissions"):
        values["permission_mode"] = mode
        assert load_cli_request("minimax_code", context).permission_mode == mode
    for invalid in (True, None, [], {}, "full-access"):
        values["permission_mode"] = invalid
        with pytest.raises(ValueError, match="permission_mode"):
            load_cli_request("minimax_code", context)


@pytest.mark.parametrize("harness_id", ["openclaw", "pi", "deepseek_harness", "minimax_code"])
def test_empty_workspace_does_not_inherit_host_project(provider, tmp_path, monkeypatch, harness_id):
    host = tmp_path / "host"
    host.mkdir()
    (host / "AGENTS.md").write_text("HOST_INSTRUCTIONS_MUST_NOT_LEAK", encoding="utf-8")
    monkeypatch.chdir(host)
    node = tmp_path / "memories" / "node"
    values = {"provider_id": "p", "model": "first", "working_path": ""}
    context = HarnessContext(str(node / "config.json"), str(node), values)
    request = load_cli_request(harness_id, context)
    workspace = node / ".harness" / harness_id / "workspace"
    assert request.cwd == str(workspace)
    assert workspace.is_dir()
    assert list(workspace.iterdir()) == []
    assert load_cli_request(harness_id, context).state_dir == request.state_dir
    values["model"] = "second"
    changed = load_cli_request(harness_id, context)
    assert changed.cwd == request.cwd
    assert changed.state_dir == request.state_dir
    other = tmp_path / "memories" / "other"
    assert load_cli_request(harness_id, HarnessContext(
        str(other / "config.json"), str(other), values)).cwd != request.cwd


def test_explicit_workspace_is_preserved_and_missing_directory_is_rejected(provider, tmp_path):
    values = {"provider_id": "p", "working_path": str(tmp_path)}
    context = HarnessContext(str(tmp_path / "config.json"), str(tmp_path), values)
    assert load_cli_request("openclaw", context).cwd == str(tmp_path)
    values["working_path"] = str(tmp_path / "missing")
    with pytest.raises(ValueError, match="working_path does not exist"):
        load_cli_request("openclaw", context)
    assert not (tmp_path / "missing").exists()

import pytest

from src.provider_options import (
    PROVIDER_VISIBILITY_CONTEXT_KEY,
    build_provider_options_for_support_modes,
    build_provider_support_list,
    provider_options_include_private,
)


def test_build_provider_options_for_support_modes_filters_and_sorts():
    providers = {
        "beta": {"supportmode": ["chat", "model_generation"]},
        "alpha": {"supportmode": ["image_generation"]},
        "audio": {"supportmode": ["audio_generation"]},
        "ignored": {"supportmode": ["chat"]},
        "empty": {"supportmode": []},
    }

    options = build_provider_options_for_support_modes(
        {"image_generation", "model_generation", "audio_generation"},
        providers,
    )

    assert [item["value"] for item in options] == ["alpha", "audio", "beta"]


def test_build_provider_options_for_support_modes_handles_loader_failure(monkeypatch):
    import src.provider_options as provider_options_module

    class DummyLoader:
        def get_all_providers(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(provider_options_module, "ConfigLoader", lambda: DummyLoader())

    assert build_provider_options_for_support_modes({"image_generation"}) == []


def test_build_provider_support_list_preserves_settings_support_modes():
    providers = build_provider_support_list(
        {
            "configured": {
                "supportmode": ["imagechat", "chat"],
                "features": {"thinking": {"supported": True}},
            },
            "unconfigured": {},
        }
    )

    assert providers == [
        {
            "id": "configured",
            "supportmode": ["imagechat", "chat"],
            "features": {"thinking": {"supported": True}},
        },
        {
            "id": "unconfigured",
            "supportmode": [],
            "features": {},
        },
    ]


def test_provider_option_builders_hide_private_providers_when_requested():
    providers = {
        "public-provider": {
            "supportmode": ["chat", "image_generation"],
            "private": False,
        },
        "private-provider": {
            "supportmode": ["chat", "image_generation"],
            "private": True,
        },
    }

    local_options = build_provider_options_for_support_modes(
        {"image_generation"},
        providers,
    )
    remote_options = build_provider_options_for_support_modes(
        {"image_generation"},
        providers,
        include_private=False,
    )
    remote_support = build_provider_support_list(
        providers,
        include_private=False,
    )

    assert [item["value"] for item in local_options] == [
        "private-provider",
        "public-provider",
    ]
    assert [item["value"] for item in remote_options] == ["public-provider"]
    assert [item["id"] for item in remote_support] == ["public-provider"]


def test_provider_visibility_context_requires_boolean_value():
    with pytest.raises(ValueError, match=PROVIDER_VISIBILITY_CONTEXT_KEY):
        provider_options_include_private(
            {PROVIDER_VISIBILITY_CONTEXT_KEY: "false"},
        )


def test_provider_and_node_template_apis_hide_private_providers_from_remote_clients(
    monkeypatch,
    tmp_path,
):
    import json

    from fastapi.testclient import TestClient

    import src.web_backend as backend
    from src.config_loader import ConfigLoader

    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "public-image": {
                        "type": "doubao",
                        "apiKey": "public-secret",
                        "baseUrl": "https://example.com/v1",
                        "model": "public-image-model",
                        "supportmode": ["image_generation"],
                    },
                    "public-audio": {
                        "type": "doubao",
                        "apiKey": "audio-secret",
                        "baseUrl": "https://example.com/v1",
                        "model": "public-audio-model",
                        "supportmode": ["audio_generation"],
                    },
                    "public-multi": {
                        "type": "doubao",
                        "apiKey": "multi-secret",
                        "baseUrl": "https://example.com/v1",
                        "model": "public-multi-model",
                        "supportmode": ["imagechat", "chat", "image_generation"],
                    },
                    "unconfigured": {
                        "type": "doubao",
                        "apiKey": "unconfigured-secret",
                        "baseUrl": "https://example.com/v1",
                        "model": "unconfigured-model",
                        "supportmode": [],
                    },
                    "private-image": {
                        "type": "doubao",
                        "apiKey": "private-secret",
                        "baseUrl": "https://example.com/v1",
                        "model": "private-image-model",
                        "supportmode": ["image_generation"],
                        "private": True,
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    ConfigLoader._instance = None

    try:
        app = backend.create_app()
        local_client = TestClient(app, client=("127.0.0.1", 12345))
        remote_client = TestClient(app, client=("192.0.2.10", 12345))

        local_provider_ids = {
            item["id"] for item in local_client.get("/api/providers").json()["providers"]
        }
        remote_provider_ids = {
            item["id"] for item in remote_client.get("/api/providers").json()["providers"]
        }
        assert local_provider_ids == {
            "public-audio",
            "public-image",
            "public-multi",
            "private-image",
            "unconfigured",
        }
        assert remote_provider_ids == {
            "public-audio",
            "public-image",
            "public-multi",
            "unconfigured",
        }

        remote_support = {
            item["id"]: item["supportmode"]
            for item in remote_client.get("/api/providers").json()["providers"]
        }
        assert remote_support["public-multi"] == ["imagechat", "chat", "image_generation"]
        assert remote_support["unconfigured"] == []

        assert local_client.get("/api/nodes/templates/agent_node").status_code == 200
        assert remote_client.get("/api/nodes/templates/agent_node").status_code == 200

        image_template = local_client.get(
            "/api/nodes/templates/agent_node",
            params={"provider_id": "public-image"},
        )
        assert image_template.status_code == 200
        image_payload = image_template.json()
        image_schema = image_payload["schema"]
        assert image_payload["support_modes"] == ["image_generation"]
        assert "mode" not in image_schema
        assert "image_model" not in image_schema
        assert "tools" not in image_schema
        assert "audio_operation" not in image_schema

        audio_template = local_client.get(
            "/api/nodes/templates/agent_node",
            params={"provider_id": "public-audio"},
        )
        assert audio_template.status_code == 200
        audio_payload = audio_template.json()
        audio_schema = audio_payload["schema"]
        assert audio_payload["support_modes"] == ["audio_generation"]
        assert "mode" not in audio_schema
        assert "audio_operation" in audio_schema
        assert "image_model" not in audio_schema
        assert "tools" not in audio_schema

        chat_template = local_client.get(
            "/api/nodes/templates/agent_node",
            params={"provider_id": "public-multi"},
        )
        assert chat_template.status_code == 200
        chat_payload = chat_template.json()
        chat_schema = chat_payload["schema"]
        assert chat_payload["support_modes"] == [
            "imagechat",
            "chat",
            "image_generation",
        ]
        assert "mode" not in chat_schema
        assert "tools" in chat_schema
        assert "audio_operation" not in chat_schema
        assert "image_model" not in chat_schema

        non_agent = local_client.get("/api/nodes/templates/echo_node")
        non_agent_with_agent_context = local_client.get(
            "/api/nodes/templates/echo_node",
            params={"provider_id": "missing-provider", "mode": "audio_generation"},
        )
        assert non_agent.status_code == 200
        assert non_agent_with_agent_context.status_code == 200
        assert non_agent_with_agent_context.json() == non_agent.json()
    finally:
        ConfigLoader._instance = None

import json

import pytest

from src.provider_api_key_store import (
    load_api_key_store,
    resolve_provider_credential_references,
)


def test_resolve_provider_credential_references_resolves_shared_names(tmp_path):
    store_path = tmp_path / "apiKey.json"
    store_path.write_text(
        json.dumps({"Ark": "secret-value", "Speech": "speech-secret"}),
        encoding="utf-8",
    )
    providers = {
        "chat": {"apiKey": "Ark"},
        "image": {"apiKey": "Ark", "xApiKey": "Speech"},
    }

    resolved = resolve_provider_credential_references(providers, store_path=str(store_path))

    assert resolved["chat"]["apiKey"] == "secret-value"
    assert resolved["image"] == {"apiKey": "secret-value", "xApiKey": "speech-secret"}


def test_resolve_provider_credential_references_rejects_missing_name(tmp_path):
    store_path = tmp_path / "apiKey.json"
    store_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="missing API key name 'Ark'"):
        resolve_provider_credential_references(
            {"chat": {"apiKey": "Ark"}},
            store_path=str(store_path),
        )


def test_load_api_key_store_rejects_empty_secret(tmp_path):
    store_path = tmp_path / "apiKey.json"
    store_path.write_text(json.dumps({"Ark": "  "}), encoding="utf-8")

    with pytest.raises(ValueError, match="Ark.*non-empty string"):
        load_api_key_store(str(store_path))


def test_empty_optional_credential_reference_does_not_require_store(tmp_path):
    resolved = resolve_provider_credential_references(
        {"chat": {"xApiKey": ""}},
        store_path=str(tmp_path / "missing.json"),
    )

    assert resolved == {"chat": {"xApiKey": ""}}

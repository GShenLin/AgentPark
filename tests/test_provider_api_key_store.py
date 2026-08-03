import json

import pytest

from src.provider_api_key_store import (
    add_api_key_alias,
    list_api_key_names,
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


def test_add_api_key_alias_creates_store_and_lists_names_without_secrets(tmp_path):
    store_path = tmp_path / ".auth" / "api-keys" / "aliases.json"

    names = add_api_key_alias(str(store_path), name="Work", api_key="secret-value")

    assert names == ["Work"]
    assert list_api_key_names(str(store_path)) == ["Work"]
    assert json.loads(store_path.read_text(encoding="utf-8")) == {"Work": "secret-value"}


def test_add_api_key_alias_rejects_duplicate_without_overwriting(tmp_path):
    store_path = tmp_path / "aliases.json"
    store_path.write_text(json.dumps({"Work": "original-secret"}), encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        add_api_key_alias(str(store_path), name="Work", api_key="replacement-secret")

    assert load_api_key_store(str(store_path)) == {"Work": "original-secret"}


def test_list_api_key_names_returns_empty_for_missing_store(tmp_path):
    assert list_api_key_names(str(tmp_path / "missing.json")) == []

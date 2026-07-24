from __future__ import annotations

import json
import os


API_KEY_STORE_RELATIVE_PATH = os.path.join(".env", "apiKey.json")
PROVIDER_CREDENTIAL_REFERENCE_FIELDS = (
    "apiKey",
    "xApiKey",
    "speechAccessKeyId",
    "speechSecretAccessKey",
)


def api_key_store_path(workspace_root: str) -> str:
    return os.path.join(os.path.abspath(workspace_root), API_KEY_STORE_RELATIVE_PATH)


def load_api_key_store(path: str) -> dict[str, str]:
    resolved_path = os.path.abspath(path)
    if not os.path.isfile(resolved_path):
        raise FileNotFoundError(f"API key store not found: {resolved_path}")
    with open(resolved_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"API key store must contain a top-level object: {resolved_path}")

    for raw_name, raw_value in payload.items():
        if not isinstance(raw_name, str) or not raw_name.strip() or raw_name != raw_name.strip():
            raise ValueError("API key store names must be non-empty strings without surrounding whitespace")
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise ValueError(f"API key store entry '{raw_name}' must be a non-empty string")
    return payload


def resolve_provider_credential_references(
    providers: dict,
    *,
    store_path: str,
) -> dict:
    key_store = None
    for raw_provider_name, provider in providers.items():
        provider_name = str(raw_provider_name)
        if not isinstance(provider, dict):
            continue
        for field_name in PROVIDER_CREDENTIAL_REFERENCE_FIELDS:
            if field_name not in provider:
                continue
            reference = provider[field_name]
            if isinstance(reference, str) and not reference.strip():
                continue
            if not isinstance(reference, str):
                raise ValueError(
                    f"Provider '{provider_name}' field '{field_name}' must reference a string key name"
                )
            if reference != reference.strip():
                raise ValueError(
                    f"Provider '{provider_name}' field '{field_name}' key name must not contain surrounding whitespace"
                )
            if key_store is None:
                key_store = load_api_key_store(store_path)
            if reference not in key_store:
                raise ValueError(
                    f"Provider '{provider_name}' field '{field_name}' references missing API key name "
                    f"'{reference}' in {os.path.abspath(store_path)}"
                )
            provider[field_name] = key_store[reference]
    return providers


__all__ = [
    "PROVIDER_CREDENTIAL_REFERENCE_FIELDS",
    "api_key_store_path",
    "load_api_key_store",
    "resolve_provider_credential_references",
]

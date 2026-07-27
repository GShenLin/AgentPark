from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from src.file_transaction import atomic_write_text, run_with_interprocess_lock
from src.workspace_settings import get_workspace_root


AUTH_DIRECTORY = ".auth"
_SAFE_PROVIDER = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class AuthStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredAccount:
    id: str
    provider: str
    kind: str
    credential: dict[str, Any]
    alias: str = ""
    identity: str = ""
    added_at: int = 0
    needs_reauth: bool = False


def auth_root() -> str:
    return os.path.join(get_workspace_root(), AUTH_DIRECTORY)


def provider_auth_dir(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if not _SAFE_PROVIDER.fullmatch(normalized):
        raise AuthStoreError(f"Invalid authorization provider id: {provider!r}")
    return os.path.join(auth_root(), normalized)


def _index_path(provider: str) -> str:
    return os.path.join(provider_auth_dir(provider), "accounts.json")


def _account_path(provider: str, account_id: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{12}", str(account_id or "")):
        raise AuthStoreError("Invalid authorization account id.")
    return os.path.join(provider_auth_dir(provider), "accounts", f"{account_id}.json")


def _read_json(path: str, *, missing: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return missing
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthStoreError(f"Failed to read authorization store {path}: {exc}") from exc


def _write_json(path: str, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(path, 0o600)


def _load_index(provider: str) -> dict[str, Any]:
    payload = _read_json(_index_path(provider), missing={"version": 1, "activeAccountId": "", "accounts": []})
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("accounts"), list):
        raise AuthStoreError(f"Invalid account index for provider '{provider}'.")
    return payload


def _stable_account_id(provider: str, identity: str) -> str:
    return hashlib.sha256(f"{provider.lower()}\0{identity}".encode("utf-8")).hexdigest()[:12]


def save_account(
    provider: str,
    *,
    kind: str,
    credential: dict[str, Any],
    identity: str,
    alias: str = "",
    activate: bool = True,
) -> StoredAccount:
    if kind not in {"oauth", "api_key"}:
        raise AuthStoreError(f"Unsupported credential kind: {kind}")
    if not isinstance(credential, dict) or not credential:
        raise AuthStoreError("Credential must be a non-empty object.")
    normalized_identity = str(identity or "").strip()
    if not normalized_identity:
        raise AuthStoreError("A stable account identity is required.")
    account_id = _stable_account_id(provider, normalized_identity)
    index_path = _index_path(provider)

    def mutate() -> StoredAccount:
        index = _load_index(provider)
        existing = next((item for item in index["accounts"] if item.get("id") == account_id), None)
        added_at = int(existing.get("addedAt") or time.time() * 1000) if existing else int(time.time() * 1000)
        metadata = {
            "id": account_id,
            "alias": str(alias or existing.get("alias") if existing else alias).strip(),
            "identity": normalized_identity,
            "kind": kind,
            "addedAt": added_at,
            "needsReauth": False,
        }
        if existing:
            existing.clear()
            existing.update(metadata)
        else:
            index["accounts"].append(metadata)
        if activate or not index.get("activeAccountId"):
            index["activeAccountId"] = account_id
        _write_json(_account_path(provider, account_id), {"version": 1, "kind": kind, "credential": credential})
        _write_json(index_path, index)
        return StoredAccount(account_id, provider, kind, dict(credential), metadata["alias"], normalized_identity, added_at)

    return run_with_interprocess_lock(f"{index_path}.lock", mutate)


def list_accounts(provider: str) -> list[dict[str, Any]]:
    index = _load_index(provider)
    active = str(index.get("activeAccountId") or "")
    return [
        {
            "id": str(item.get("id") or ""),
            "alias": str(item.get("alias") or ""),
            "identity": str(item.get("identity") or ""),
            "kind": str(item.get("kind") or ""),
            "addedAt": int(item.get("addedAt") or 0),
            "needsReauth": item.get("needsReauth") is True,
            "active": item.get("id") == active,
        }
        for item in index["accounts"]
    ]


def get_account(provider: str, account_id: str | None = None) -> StoredAccount | None:
    index = _load_index(provider)
    selected = str(account_id or index.get("activeAccountId") or "")
    metadata = next((item for item in index["accounts"] if item.get("id") == selected), None)
    if not metadata:
        return None
    payload = _read_json(_account_path(provider, selected), missing=None)
    if not isinstance(payload, dict) or not isinstance(payload.get("credential"), dict):
        raise AuthStoreError(f"Credential file is missing or invalid for {provider}/{selected}.")
    return StoredAccount(
        selected,
        provider,
        str(payload.get("kind") or metadata.get("kind") or ""),
        dict(payload["credential"]),
        str(metadata.get("alias") or ""),
        str(metadata.get("identity") or ""),
        int(metadata.get("addedAt") or 0),
        metadata.get("needsReauth") is True,
    )


def set_active_account(provider: str, account_id: str) -> bool:
    index_path = _index_path(provider)

    def mutate() -> bool:
        index = _load_index(provider)
        if not any(item.get("id") == account_id for item in index["accounts"]):
            return False
        index["activeAccountId"] = account_id
        _write_json(index_path, index)
        return True

    return run_with_interprocess_lock(f"{index_path}.lock", mutate)


def remove_account(provider: str, account_id: str) -> bool:
    index_path = _index_path(provider)

    def mutate() -> bool:
        index = _load_index(provider)
        remaining = [item for item in index["accounts"] if item.get("id") != account_id]
        if len(remaining) == len(index["accounts"]):
            return False
        index["accounts"] = remaining
        if index.get("activeAccountId") == account_id:
            index["activeAccountId"] = str(remaining[0].get("id") or "") if remaining else ""
        try:
            os.remove(_account_path(provider, account_id))
        except FileNotFoundError:
            pass
        _write_json(index_path, index)
        return True

    return run_with_interprocess_lock(f"{index_path}.lock", mutate)


def update_account_credential(provider: str, account_id: str, credential: dict[str, Any]) -> StoredAccount:
    current = get_account(provider, account_id)
    if current is None:
        raise AuthStoreError(f"Unknown account '{account_id}' for provider '{provider}'.")
    return save_account(
        provider,
        kind=current.kind,
        credential=credential,
        identity=current.identity,
        alias=current.alias,
        activate=False,
    )


__all__ = [
    "AUTH_DIRECTORY",
    "AuthStoreError",
    "StoredAccount",
    "auth_root",
    "get_account",
    "list_accounts",
    "provider_auth_dir",
    "remove_account",
    "save_account",
    "set_active_account",
    "update_account_credential",
]

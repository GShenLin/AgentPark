from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Any

from src.cli_provider_runtime.provider_adapter import provider_protocol
from src.config_loader import ConfigLoader
from src.file_transaction import atomic_write_text
from src.file_transaction import run_with_interprocess_lock
from src.provider_auth.store import get_account
from src.provider_auth.store import list_accounts
from src.workspace_settings import get_workspace_root


CONFIG_VERSION = 1
PROTOCOLS = ("responses", "chat_completions", "messages")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_ACCOUNT_ID = re.compile(r"^[a-f0-9]{12}$")
_KEY_ID = re.compile(r"^[a-f0-9]{12}$")


class PublicGatewayStore:
    def __init__(self, workspace_root: str | None = None) -> None:
        self.workspace_root = os.path.abspath(workspace_root or get_workspace_root())
        self.config_path = os.path.join(self.workspace_root, "config", "publicGateway.json")
        self.keys_path = os.path.join(self.workspace_root, ".auth", "gateway", "keys.json")

    def snapshot(self) -> dict[str, Any]:
        config = self.load_config()
        return {
            "enabled": config["enabled"],
            "requireApiKey": config["requireApiKey"],
            "models": list(config["models"]),
            "keys": self.list_keys(),
            "providers": self.list_providers(),
            "sourceErrors": self.list_source_errors(),
        }

    def load_config(self) -> dict[str, Any]:
        payload = self._read_json(
            self.config_path,
            missing={
                "version": CONFIG_VERSION,
                "enabled": True,
                "requireApiKey": True,
                "models": [],
            },
        )
        return self._validate_config(payload)

    def update_options(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Gateway options must be an object.")
        if not isinstance(payload.get("enabled"), bool):
            raise ValueError("Gateway enabled must be a boolean.")
        if not isinstance(payload.get("requireApiKey"), bool):
            raise ValueError("Gateway requireApiKey must be a boolean.")

        def mutate() -> dict[str, Any]:
            config = self.load_config()
            config["enabled"] = payload["enabled"]
            config["requireApiKey"] = payload["requireApiKey"]
            self._write_json(self.config_path, config)
            return config

        return run_with_interprocess_lock(self.config_path + ".lock", mutate)

    def upsert_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        model = self._validate_model(payload)
        self._validate_model_source(model)

        def mutate() -> dict[str, Any]:
            config = self.load_config()
            models = [item for item in config["models"] if item["id"] != model["id"]]
            models.append(model)
            config["models"] = sorted(models, key=lambda item: item["id"].lower())
            self._write_json(self.config_path, config)
            return model

        return run_with_interprocess_lock(self.config_path + ".lock", mutate)

    def delete_model(self, model_id: str) -> dict[str, Any]:
        safe_id = self._model_id(model_id)

        def mutate() -> dict[str, Any]:
            config = self.load_config()
            models = [item for item in config["models"] if item["id"] != safe_id]
            if len(models) == len(config["models"]):
                raise KeyError(f"Gateway model {safe_id!r} does not exist.")
            config["models"] = models
            self._write_json(self.config_path, config)
            return {"deleted": True, "id": safe_id}

        return run_with_interprocess_lock(self.config_path + ".lock", mutate)

    def resolve_model(self, model_id: str, protocol: str) -> tuple[dict[str, Any], dict[str, Any]]:
        safe_id = self._model_id(model_id)
        if protocol not in PROTOCOLS:
            raise ValueError(f"Unsupported Gateway protocol: {protocol!r}.")
        config = self.load_config()
        if not config["enabled"]:
            raise RuntimeError("AgentPark Public Gateway is disabled.")
        model = next((item for item in config["models"] if item["id"] == safe_id), None)
        if model is None:
            raise KeyError(f"Gateway model {safe_id!r} does not exist.")
        if not model["enabled"]:
            raise RuntimeError(f"Gateway model {safe_id!r} is disabled.")
        if protocol not in model["protocols"]:
            raise ValueError(f"Gateway model {safe_id!r} does not enable protocol {protocol!r}.")
        self._validate_model_source(model)
        provider_config = self._resolve_source_config(model["providerId"])
        if model["accountId"]:
            provider_config = {**provider_config, "authAccountId": model["accountId"]}
        return model, provider_config

    def list_public_models(self) -> list[dict[str, Any]]:
        config = self.load_config()
        if not config["enabled"]:
            return []
        return [dict(item) for item in config["models"] if item["enabled"]]

    def list_providers(self) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for provider_id, config in ConfigLoader().get_provider_catalog().items():
            modes = config.get("supportmode")
            if not isinstance(modes, list) or not any(mode in {"chat", "imagechat"} for mode in modes):
                continue
            try:
                protocol = provider_protocol(config)
            except ValueError:
                continue
            auth_provider = str(config.get("authProvider") or config.get("type") or "").strip().lower()
            accounts = list_accounts(auth_provider) if auth_provider else []
            output.append(
                {
                    "id": provider_id,
                    "model": str(config.get("model") or ""),
                    "protocol": protocol,
                    "authProvider": auth_provider,
                    "accounts": accounts,
                    "kind": "provider",
                }
            )
        return sorted(output, key=lambda item: item["id"].lower())

    def list_source_errors(self) -> list[dict[str, str]]:
        return []

    def list_keys(self) -> list[dict[str, Any]]:
        payload = self._load_keys()
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "prefix": item["prefix"],
                "createdAt": item["createdAt"],
            }
            for item in payload["keys"]
        ]

    def create_key(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Gateway key payload must be an object.")
        name = str(payload.get("name") or "").strip()
        if not name or len(name) > 80:
            raise ValueError("Gateway key name must contain 1 to 80 characters.")
        supplied = payload.get("key")
        if supplied is not None and not isinstance(supplied, str):
            raise ValueError("Gateway custom key must be a string.")
        key_id = secrets.token_hex(6)
        plaintext = str(supplied or "").strip() or f"apg_{key_id}_{secrets.token_urlsafe(32)}"
        if len(plaintext) < 8 or len(plaintext) > 512:
            raise ValueError("Gateway key must contain 8 to 512 characters.")
        digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
        record = {
            "id": key_id,
            "name": name,
            "prefix": _key_prefix(plaintext),
            "sha256": digest,
            "createdAt": int(time.time() * 1000),
        }

        def mutate() -> dict[str, Any]:
            keys = self._load_keys()
            if any(hmac.compare_digest(item["sha256"], digest) for item in keys["keys"]):
                raise ValueError("Gateway key already exists.")
            keys["keys"].append(record)
            self._write_json(self.keys_path, keys)
            return {
                "id": key_id,
                "name": name,
                "prefix": record["prefix"],
                "createdAt": record["createdAt"],
                "key": plaintext,
            }

        return run_with_interprocess_lock(self.keys_path + ".lock", mutate)

    def delete_key(self, key_id: str) -> dict[str, Any]:
        safe_id = str(key_id or "").strip()
        if not _KEY_ID.fullmatch(safe_id):
            raise ValueError("Invalid Gateway key id.")

        def mutate() -> dict[str, Any]:
            keys = self._load_keys()
            retained = [item for item in keys["keys"] if item["id"] != safe_id]
            if len(retained) == len(keys["keys"]):
                raise KeyError(f"Gateway key {safe_id!r} does not exist.")
            keys["keys"] = retained
            self._write_json(self.keys_path, keys)
            return {"deleted": True, "id": safe_id}

        return run_with_interprocess_lock(self.keys_path + ".lock", mutate)

    def authenticate(self, plaintext: str) -> bool:
        value = str(plaintext or "")
        if not value:
            return False
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return any(hmac.compare_digest(item["sha256"], digest) for item in self._load_keys()["keys"])

    def _validate_config(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("version") != CONFIG_VERSION:
            raise ValueError("config/publicGateway.json must be a version 1 object.")
        enabled = payload.get("enabled")
        require_key = payload.get("requireApiKey")
        models = payload.get("models")
        if not isinstance(enabled, bool) or not isinstance(require_key, bool):
            raise ValueError("Gateway enabled and requireApiKey must be booleans.")
        if not isinstance(models, list):
            raise ValueError("Gateway models must be an array.")
        normalized = [self._validate_model(item) for item in models]
        ids = [item["id"] for item in normalized]
        if len(ids) != len(set(ids)):
            raise ValueError("Gateway model ids must be unique.")
        return {
            "version": CONFIG_VERSION,
            "enabled": enabled,
            "requireApiKey": require_key,
            "models": normalized,
        }

    def _validate_model(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Gateway model must be an object.")
        model_id = self._model_id(payload.get("id"))
        provider_id = str(payload.get("providerId") or "").strip()
        if not provider_id:
            raise ValueError("Gateway model providerId is required.")
        protocols = payload.get("protocols")
        if not isinstance(protocols, list) or not protocols:
            raise ValueError("Gateway model protocols must be a non-empty array.")
        normalized_protocols: list[str] = []
        for value in protocols:
            protocol = str(value or "").strip()
            if protocol not in PROTOCOLS:
                raise ValueError(f"Unsupported Gateway protocol: {protocol!r}.")
            if protocol not in normalized_protocols:
                normalized_protocols.append(protocol)
        account_id = str(payload.get("accountId") or "").strip()
        if account_id and not _ACCOUNT_ID.fullmatch(account_id):
            raise ValueError("Gateway model accountId must be a 12-character account id.")
        enabled = payload.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("Gateway model enabled must be a boolean.")
        return {
            "id": model_id,
            "providerId": provider_id,
            "accountId": account_id,
            "protocols": normalized_protocols,
            "enabled": enabled,
        }

    def _validate_model_source(self, model: dict[str, Any]) -> None:
        provider = self._resolve_source_config(model["providerId"])
        provider_protocol(provider)
        account_id = model["accountId"]
        if not account_id:
            return
        auth_provider = str(
            provider.get("authProvider")
            or provider.get("type")
            or ("openai" if provider.get("authMode") == "codex" else "")
        ).strip().lower()
        if not auth_provider or get_account(auth_provider, account_id) is None:
            raise ValueError(
                f"Gateway model account {account_id!r} does not exist for {auth_provider or 'provider'}."
            )

    def _resolve_source_config(self, source_id: str) -> dict[str, Any]:
        safe_source_id = str(source_id or "").strip()
        return ConfigLoader().get_provider_config(safe_source_id)

    def _load_keys(self) -> dict[str, Any]:
        payload = self._read_json(self.keys_path, missing={"version": CONFIG_VERSION, "keys": []})
        if not isinstance(payload, dict) or payload.get("version") != CONFIG_VERSION:
            raise ValueError("Gateway key store must be a version 1 object.")
        keys = payload.get("keys")
        if not isinstance(keys, list):
            raise ValueError("Gateway key store keys must be an array.")
        for item in keys:
            if (
                not isinstance(item, dict)
                or not _KEY_ID.fullmatch(str(item.get("id") or ""))
                or not isinstance(item.get("sha256"), str)
            ):
                raise ValueError("Gateway key store contains an invalid key record.")
        return payload

    @staticmethod
    def _model_id(value: Any) -> str:
        model_id = str(value or "").strip()
        if not _MODEL_ID.fullmatch(model_id):
            raise ValueError("Gateway model id contains unsupported characters or length.")
        return model_id

    @staticmethod
    def _read_json(path: str, *, missing: Any) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return missing
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Failed to read Gateway store {path}: {exc}") from exc

    @staticmethod
    def _write_json(path: str, payload: Any) -> None:
        atomic_write_text(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _key_prefix(value: str) -> str:
    return value if len(value) <= 12 else f"{value[:12]}…"


__all__ = ["PROTOCOLS", "PublicGatewayStore"]

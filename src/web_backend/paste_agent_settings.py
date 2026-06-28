import json
import os

from src.file_transaction import atomic_write_text

from . import runtime_paths
from .service_host import HostBoundService
from .shared import ConfigLoader, HTTPException


class PasteAgentSettings(HostBoundService):
    def _paste_agent_config_path(self) -> str:
        return os.path.join(runtime_paths._get_runtime_root(), "config", "pastagent.json")

    def _map_provider_alias(self, provider_id: object) -> str:
        value = str(provider_id or "").strip()
        if not value:
            return ""

        try:
            providers = ConfigLoader().get_all_providers()
        except Exception:
            providers = {}
        if not isinstance(providers, dict) or not providers:
            return value

        if value in providers:
            return value

        lowered = value.lower()
        for key in providers.keys():
            key_text = str(key or "").strip()
            if key_text.lower() == lowered:
                return key_text
        return value

    def _default_provider_id(self) -> str:
        try:
            providers = ConfigLoader().get_all_providers()
        except Exception:
            providers = {}

        if isinstance(providers, dict) and providers:
            if "gemini" in providers:
                return "gemini"
            first_key = next(iter(providers.keys()), "")
            return self._map_provider_alias(first_key)
        return "gemini"

    def _default_paste_agent_config(self) -> dict:
        provider_id = self._default_provider_id()

        return {
            "agent_id": "pastagent",
            "name": "PasteAgent",
            "provider_id": provider_id,
            "mode": "chat",
            "web_search": "enabled",
            "thinking": "enabled",
            "reasoning_effort": "high",
            "system_prompt": "You are an assistant created from pasted text. Keep responses concise and actionable.",
            "tools": [],
        }

    def _build_paste_agent_config(self, raw: dict | None) -> dict:
        default = self._default_paste_agent_config()
        payload = raw if isinstance(raw, dict) else {}
        provider_id = self._map_provider_alias(payload.get("provider_id") or default.get("provider_id") or "")
        if not provider_id:
            provider_id = self._default_provider_id()

        tools = payload.get("tools")
        safe_tools: list[str] = []
        if isinstance(tools, list):
            seen = set()
            for item in tools:
                value = str(item or "").strip()
                if not value:
                    continue
                key = value.lower()
                if key in seen:
                    continue
                seen.add(key)
                safe_tools.append(value)
        web_search = payload.get("web_search")
        if web_search is None:
            web_search = default.get("web_search")
        thinking = payload.get("thinking")
        if thinking is None:
            thinking = default.get("thinking")
        reasoning_effort = payload.get("reasoning_effort")
        if reasoning_effort is None:
            reasoning_effort = default.get("reasoning_effort")

        return {
            "agent_id": "pastagent",
            "name": str(payload.get("name") or default.get("name") or "PasteAgent"),
            "provider_id": provider_id,
            "mode": str(payload.get("mode") or default.get("mode") or "chat"),
            "web_search": web_search,
            "thinking": thinking,
            "reasoning_effort": reasoning_effort,
            "system_prompt": str(payload.get("system_prompt") or default.get("system_prompt") or ""),
            "tools": safe_tools,
        }

    def _write_paste_agent_config(self, config_payload: dict) -> str:
        config_path = self._paste_agent_config_path()
        if not isinstance(config_payload, dict):
            raise ValueError("pastagent config payload must be an object")
        atomic_write_text(config_path, json.dumps(config_payload, ensure_ascii=False, indent=2) + "\n")
        return config_path

    def _read_paste_agent_config(self, ensure_exists: bool = True) -> dict:
        config_path = self._paste_agent_config_path()
        raw: dict = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"pastagent config contains invalid JSON: {config_path}: line {exc.lineno} column {exc.colno}: {exc.msg}"
                ) from exc
            except OSError as exc:
                raise ValueError(f"failed to read pastagent config {config_path}: {type(exc).__name__}: {exc}") from exc
            if not isinstance(loaded, dict):
                raise ValueError(f"pastagent config must be a JSON object: {config_path}")
            raw = loaded

        mapped = self._build_paste_agent_config(raw)
        if ensure_exists:
            needs_write = not os.path.exists(config_path)
            if not needs_write:
                needs_write = raw != mapped
            if needs_write:
                self._write_paste_agent_config(mapped)
        return mapped

    def get_paste_agent_config(self):
        try:
            config = self._read_paste_agent_config(ensure_exists=True)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to read pastagent config: {str(e)}")
        return {"config": config}

    def update_paste_agent_config(self, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")

        current = self._read_paste_agent_config(ensure_exists=True)
        merged = dict(current)

        if "name" in payload:
            merged["name"] = payload.get("name")
        if "provider_id" in payload:
            merged["provider_id"] = payload.get("provider_id")
        if "mode" in payload:
            merged["mode"] = payload.get("mode")
        if "web_search" in payload:
            merged["web_search"] = payload.get("web_search")
        if "thinking" in payload:
            merged["thinking"] = payload.get("thinking")
        if "reasoning_effort" in payload:
            merged["reasoning_effort"] = payload.get("reasoning_effort")
        if "system_prompt" in payload:
            merged["system_prompt"] = payload.get("system_prompt")
        if "tools" in payload:
            tools = payload.get("tools")
            if tools is not None and not isinstance(tools, list):
                raise HTTPException(status_code=400, detail="tools must be array")
            merged["tools"] = tools

        mapped = self._build_paste_agent_config(merged)
        try:
            self._write_paste_agent_config(mapped)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to write pastagent config: {str(e)}")
        return {"ok": True, "config": mapped}

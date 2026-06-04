import copy
import json
import os

from .workspace_settings import get_workspace_root


class ConfigLoader:
    CONFIG_PATH_ENV = "AITOOLS_CONFIG_PATH"

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_runtime_root(self):
        return get_workspace_root()

    def _resolve_config_path(self):
        explicit_path = str(os.environ.get(self.CONFIG_PATH_ENV) or "").strip()
        if explicit_path:
            resolved = os.path.abspath(explicit_path)
            if not os.path.isfile(resolved):
                raise FileNotFoundError(
                    f"Config file from {self.CONFIG_PATH_ENV} not found: {resolved}"
                )
            return resolved

        runtime_root = self._get_runtime_root()
        candidates = [
            os.path.join(runtime_root, "config", "moduleProvider.json"),
            os.path.join(os.getcwd(), "config", "moduleProvider.json"),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        raise FileNotFoundError(f"Config file not found. Checked: {candidates}")

    def _normalize_support_modes(self, provider_name, value):
        if value is None:
            return []
        if not isinstance(value, (list, tuple, set)):
            raise ValueError(
                f"Provider '{provider_name}' has invalid supportmode; expected an array."
            )
        modes = []
        seen = set()
        for item in value:
            text = str(item or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            modes.append(text)
        return modes

    def _normalize_timeout_ms(self, provider_name, value):
        if value is None or value == "":
            return value
        try:
            timeout_ms = int(float(value))
        except Exception as exc:
            raise ValueError(
                f"Provider '{provider_name}' has invalid timeoutMs: {value!r}"
            ) from exc
        if timeout_ms <= 0:
            raise ValueError(
                f"Provider '{provider_name}' timeoutMs must be greater than zero."
            )
        return timeout_ms

    def _normalize_provider_config(self, provider_name, payload, require_api_key):
        if not isinstance(payload, dict):
            raise ValueError(
                f"Provider '{provider_name}' configuration must be an object."
            )

        provider = copy.deepcopy(payload)
        provider_type = str(provider.get("type") or "").strip().lower()
        if provider_type:
            provider["type"] = provider_type

        provider["supportmode"] = self._normalize_support_modes(
            provider_name, provider.get("supportmode")
        )

        if "timeoutMs" in provider:
            provider["timeoutMs"] = self._normalize_timeout_ms(
                provider_name, provider.get("timeoutMs")
            )

        provider.pop("apiKeyEnv", None)
        provider["apiKey"] = str(provider.get("apiKey") or "").strip()

        if require_api_key and not provider["apiKey"]:
            raise ValueError(
                f"Provider '{provider_name}' requires a non-empty apiKey."
            )

        return provider

    def _load_config(self):
        config_path = self._resolve_config_path()
        with open(config_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        if not isinstance(payload, dict):
            raise ValueError("moduleProvider.json must contain a top-level object.")

        providers = payload.get("providers")
        if providers is None:
            providers = {}
        if not isinstance(providers, dict):
            raise ValueError("moduleProvider.json 'providers' must be an object.")

        normalized = copy.deepcopy(payload)
        normalized["providers"] = {
            str(provider_name): self._normalize_provider_config(
                str(provider_name),
                provider_payload,
                require_api_key=False,
            )
            for provider_name, provider_payload in providers.items()
        }
        return normalized

    def get_config(self):
        return self._load_config()

    def get_provider_config(self, provider_name):
        provider_id = str(provider_name or "").strip()
        if not provider_id:
            raise ValueError("provider_name is required")

        providers = self.get_config().get("providers", {})
        if provider_id not in providers:
            raise ValueError(f"Provider '{provider_id}' not found in configuration")

        return self._normalize_provider_config(
            provider_id,
            providers[provider_id],
            require_api_key=True,
        )

    def get_all_providers(self):
        return self.get_config().get("providers", {})

import copy
import json
import os

from src.provider_feature_matrix import build_provider_feature_matrix
from src.doubao_reasoning_effort import normalize_doubao_reasoning_effort
from src.value_parsing import parse_optional_int_value
from .workspace_settings import get_workspace_root


class ConfigLoader:
    CONFIG_PATH_ENV = "AGENTPARK_CONFIG_PATH"

    def _resolve_provider_config_path(self):
        explicit_path = str(os.environ.get(self.CONFIG_PATH_ENV) or "").strip()
        if explicit_path:
            resolved = os.path.abspath(explicit_path)
            if not os.path.isfile(resolved):
                raise FileNotFoundError(
                    f"Config file from {self.CONFIG_PATH_ENV} not found: {resolved}"
                )
            return resolved

        runtime_root = get_workspace_root()
        candidates = [
            os.path.join(runtime_root, "config", "moduleProvider.json"),
            os.path.join(os.getcwd(), "config", "moduleProvider.json"),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        raise FileNotFoundError(f"Config file not found. Checked: {candidates}")

    def _resolve_workspace_config_path(self, provider_config_path):
        explicit_path = str(os.environ.get(self.CONFIG_PATH_ENV) or "").strip()
        if explicit_path:
            candidate = os.path.join(os.path.dirname(os.path.abspath(provider_config_path)), "config.json")
            return candidate if os.path.isfile(candidate) else ""

        runtime_root = get_workspace_root()
        candidates = [
            os.path.join(runtime_root, "config", "config.json"),
            os.path.join(os.getcwd(), "config", "config.json"),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        return ""

    def _load_workspace_config(self, provider_config_path):
        path = self._resolve_workspace_config_path(provider_config_path)
        if not path:
            return {}
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            raise ValueError("config/config.json must contain a top-level object.")
        return payload

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
            return parse_optional_int_value("timeoutMs", value, minimum=1)
        except ValueError as exc:
            raise ValueError(
                f"Provider '{provider_name}' has invalid timeoutMs: {value!r}"
            ) from exc

    def _normalize_provider_config(self, provider_name, payload, require_api_key):
        if not isinstance(payload, dict):
            raise ValueError(
                f"Provider '{provider_name}' configuration must be an object."
            )

        provider = copy.deepcopy(payload)
        provider_type = str(provider.get("type") or "").strip().lower()
        if provider_type:
            provider["type"] = provider_type
        if provider_type == "doubao":
            self._normalize_doubao_reasoning_effort_fields(provider)

        provider["supportmode"] = self._normalize_support_modes(
            provider_name, provider.get("supportmode")
        )

        if "timeoutMs" in provider:
            provider["timeoutMs"] = self._normalize_timeout_ms(
                provider_name, provider.get("timeoutMs")
            )
        if "responsesApi" in provider and not isinstance(provider.get("responsesApi"), bool):
            raise ValueError(
                f"Provider '{provider_name}' has invalid responsesApi; expected a boolean."
            )
        if "streamEnabled" not in provider:
            provider["streamEnabled"] = True
        elif not isinstance(provider["streamEnabled"], bool):
            raise ValueError(
                f"Provider '{provider_name}' has invalid streamEnabled; expected a boolean."
            )
        self._validate_responses_provider_config(provider_name, provider, provider_type)

        provider.pop("apiKeyEnv", None)
        provider["apiKey"] = str(provider.get("apiKey") or "").strip()
        provider["features"] = build_provider_feature_matrix(provider)

        if require_api_key and not provider["apiKey"]:
            raise ValueError(
                f"Provider '{provider_name}' requires a non-empty apiKey."
            )

        return provider

    def _normalize_doubao_reasoning_effort_fields(self, provider):
        for key in ("reasoningEffort", "reasoning_effort"):
            if key not in provider:
                continue
            effort = normalize_doubao_reasoning_effort(provider.get(key))
            if effort:
                provider[key] = effort
            else:
                provider[key] = provider.get(key)

    def _validate_responses_provider_config(self, provider_name, provider, provider_type):
        if provider.get("responsesApi") is not True:
            return
        required = (
            "toolResultSubmissionMaxChars",
            "toolContextCompactionEnabled",
            "toolContextCompactionEveryToolCalls",
        )
        for key in required:
            if key not in provider:
                raise ValueError(
                    f"Provider '{provider_name}' has responsesApi=true but missing required field {key}."
                )

        if not isinstance(provider.get("toolContextCompactionEnabled"), bool):
            raise ValueError(
                f"Provider '{provider_name}' has invalid toolContextCompactionEnabled; expected a boolean."
            )

        for key in ("toolResultSubmissionMaxChars", "toolContextCompactionEveryToolCalls"):
            try:
                value = int(provider.get(key))
            except Exception as exc:
                raise ValueError(
                    f"Provider '{provider_name}' has invalid {key}; expected a positive integer."
                ) from exc
            if value <= 0:
                raise ValueError(
                    f"Provider '{provider_name}' has invalid {key}; expected a positive integer."
                )
            provider[key] = value

        if provider_type == "openai":
            if "responsesReplayReasoningItems" not in provider:
                raise ValueError(
                    f"Provider '{provider_name}' has responsesApi=true but missing required field responsesReplayReasoningItems."
                )
            if not isinstance(provider.get("responsesReplayReasoningItems"), bool):
                raise ValueError(
                    f"Provider '{provider_name}' has invalid responsesReplayReasoningItems; expected a boolean."
                )

    def _load_config(self):
        provider_config_path = self._resolve_provider_config_path()
        with open(provider_config_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        if not isinstance(payload, dict):
            raise ValueError("moduleProvider.json must contain a top-level object.")

        providers = payload.get("providers")
        if providers is None:
            providers = {}
        if not isinstance(providers, dict):
            raise ValueError("moduleProvider.json 'providers' must be an object.")

        normalized = copy.deepcopy(self._load_workspace_config(provider_config_path))
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

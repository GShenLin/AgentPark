import copy
import json
import os

from src.provider_feature_matrix import build_provider_feature_matrix
from src.doubao_reasoning_effort import require_doubao_reasoning_effort
from src.grok_reasoning_effort import require_grok_reasoning_effort
from .workspace_settings import get_workspace_root


class ConfigLoader:
    CONFIG_PATH_ENV = "AGENTPARK_CONFIG_PATH"
    OPENAI_REASONING_SUMMARY_VALUES = {"auto", "concise", "detailed", "disabled"}
    PROVIDER_UNSUPPORTED_CONFIG_KEYS = {
        "anthropic_beta",
        "claudeThinkingBudgetTokens",
        "claudeWebSearchAllowedCallers",
        "claudeWebSearchAllowedDomains",
        "claudeWebSearchBlockedDomains",
        "claudeWebSearchMaxUses",
        "claudeWebSearchResponseInclusion",
        "claudeWebSearchToolType",
        "claudeWebSearchUserLocation",
        "clear_thinking",
        "debug_sse",
        "debugSse",
        "default_instructions",
        "default_instructions_text",
        "do_sample",
        "contentGenerationMaxWaitSec",
        "contentGenerationPollIntervalSec",
        "image_model",
        "image_size",
        "imageModel",
        "imageModelId",
        "max_retries",
        "max_tokens",
        "reasoning_effort",
        "retry_delay_sec",
        "response_format",
        "responsesContinuationMode",
        "responses_continuation_mode",
        "responses_parallel_tool_calls",
        "responses_tool_choice",
        "tool_choice",
        "tool_stream",
        "web_search_limit",
        "web_search_max_keyword",
        "web_search_sources",
        "task_status_base_url",
        "video_change_person_mode",
        "videoChangePersonCheckImage",
        "videoChangePersonMaxWaitSec",
        "videoChangePersonMode",
        "videoChangePersonPollIntervalSec",
        "videoModel",
        "videoModelId",
        "video_model",
        "wan_animate_mix_mode",
    }

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

    def _validate_support_modes(self, provider_name, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError(
                f"Provider '{provider_name}' has invalid supportmode; expected an array."
            )
        modes = []
        seen = set()
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    f"Provider '{provider_name}' has invalid supportmode; expected non-empty strings."
                )
            text = item.strip()
            if text in seen:
                raise ValueError(
                    f"Provider '{provider_name}' has invalid supportmode; duplicate value: {text}."
                )
            seen.add(text)
            modes.append(text)
        return modes

    def _validate_timeout_ms(self, provider_name, value):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(
                f"Provider '{provider_name}' has invalid timeoutMs; expected a positive integer."
            )
        return value

    def _validate_optional_positive_int(self, provider_name, field_name, value):
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(
                f"Provider '{provider_name}' has invalid {field_name}; expected a positive integer."
            )
        return value

    def _validate_provider_config(self, provider_name, payload, require_api_key):
        if not isinstance(payload, dict):
            raise ValueError(
                f"Provider '{provider_name}' configuration must be an object."
            )

        provider = copy.deepcopy(payload)
        unsupported_keys = sorted(key for key in self.PROVIDER_UNSUPPORTED_CONFIG_KEYS if key in provider)
        if unsupported_keys:
            joined = ", ".join(unsupported_keys)
            raise ValueError(
                f"Provider '{provider_name}' uses unsupported config field(s): {joined}."
            )
        raw_provider_type = provider.get("type")
        provider_type = ""
        if raw_provider_type not in (None, ""):
            if not isinstance(raw_provider_type, str):
                raise ValueError(
                    f"Provider '{provider_name}' has invalid type; expected a lowercase string."
                )
            provider_type = raw_provider_type.strip()
            if not provider_type or provider_type != provider_type.lower():
                raise ValueError(
                    f"Provider '{provider_name}' has invalid type; expected a lowercase string."
                )
            provider["type"] = provider_type
        if provider_type == "doubao":
            self._validate_doubao_reasoning_effort_fields(provider)
        if provider_type == "grok":
            self._validate_grok_reasoning_effort_fields(provider)

        auth_mode = str(provider.get("authMode") or "api_key").strip().lower()
        if auth_mode not in {"api_key", "codex"}:
            raise ValueError(
                f"Provider '{provider_name}' has invalid authMode; expected 'api_key' or 'codex'."
            )
        if auth_mode == "codex" and provider_type != "openai":
            raise ValueError(f"Provider '{provider_name}' can use authMode 'codex' only with type 'openai'.")

        provider["supportmode"] = self._validate_support_modes(
            provider_name, provider.get("supportmode")
        )

        if "timeoutMs" in provider:
            provider["timeoutMs"] = self._validate_timeout_ms(
                provider_name, provider.get("timeoutMs")
            )
        for pressure_key in ("concurrencyLimit", "rpmLimit"):
            if pressure_key in provider:
                pressure_value = self._validate_optional_positive_int(
                    provider_name,
                    pressure_key,
                    provider.get(pressure_key),
                )
                if pressure_value is None:
                    provider.pop(pressure_key, None)
                else:
                    provider[pressure_key] = pressure_value
        if "responsesApi" in provider and not isinstance(provider.get("responsesApi"), bool):
            raise ValueError(
                f"Provider '{provider_name}' has invalid responsesApi; expected a boolean."
            )
        if provider_type == "deepseek" and provider.get("responsesApi") is True:
            raise ValueError(
                f"Provider '{provider_name}' has type 'deepseek' but responsesApi=true; DeepSeek uses chat completions."
            )
        if "streamEnabled" not in provider:
            provider["streamEnabled"] = True
        elif not isinstance(provider["streamEnabled"], bool):
            raise ValueError(
                f"Provider '{provider_name}' has invalid streamEnabled; expected a boolean."
            )
        self._validate_responses_provider_config(provider_name, provider, provider_type)

        provider.pop("apiKeyEnv", None)
        if auth_mode == "codex":
            if provider.get("responsesApi") is not True:
                raise ValueError(f"Provider '{provider_name}' with authMode 'codex' requires responsesApi=true.")
            if str(provider.get("apiKey") or "").strip():
                raise ValueError(f"Provider '{provider_name}' with authMode 'codex' must not contain apiKey.")
            provider["authMode"] = "codex"
            provider.pop("apiKey", None)
            provider["baseUrl"] = "https://chatgpt.com/backend-api/codex"
        else:
            provider["authMode"] = "api_key"
            provider["apiKey"] = str(provider.get("apiKey") or "").strip()
        provider["features"] = build_provider_feature_matrix(provider)

        if require_api_key and auth_mode == "api_key" and not provider["apiKey"]:
            raise ValueError(
                f"Provider '{provider_name}' requires a non-empty apiKey."
            )

        return provider

    def _validate_doubao_reasoning_effort_fields(self, provider):
        if "reasoningEffort" not in provider:
            return
        effort = require_doubao_reasoning_effort(provider.get("reasoningEffort"))
        if effort:
            provider["reasoningEffort"] = effort

    def _validate_grok_reasoning_effort_fields(self, provider):
        if "reasoningSummary" in provider:
            raise ValueError("Grok providers do not support reasoningSummary.")
        if "reasoningEffort" not in provider:
            return
        effort = require_grok_reasoning_effort(
            provider.get("model"),
            provider.get("reasoningEffort"),
        )
        if effort:
            provider["reasoningEffort"] = effort

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
            value = provider.get(key)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(
                    f"Provider '{provider_name}' has invalid {key}; expected a positive integer."
                )
            if value <= 0:
                raise ValueError(
                    f"Provider '{provider_name}' has invalid {key}; expected a positive integer."
                )

        if provider_type in {"openai", "grok"}:
            if provider_type == "openai":
                self._validate_openai_reasoning_summary(provider_name, provider)
            if "responsesReplayReasoningItems" not in provider:
                raise ValueError(
                    f"Provider '{provider_name}' has responsesApi=true but missing required field responsesReplayReasoningItems."
                )
            if not isinstance(provider.get("responsesReplayReasoningItems"), bool):
                raise ValueError(
                    f"Provider '{provider_name}' has invalid responsesReplayReasoningItems; expected a boolean."
                )

    def _validate_openai_reasoning_summary(self, provider_name, provider):
        if "reasoningSummary" not in provider:
            return
        value = provider.get("reasoningSummary")
        if value is None or value == "":
            provider.pop("reasoningSummary", None)
            return
        if not isinstance(value, str):
            raise ValueError(
                f"Provider '{provider_name}' has invalid reasoningSummary; expected auto, concise, detailed, or disabled."
            )
        summary = value.strip().lower()
        if summary not in self.OPENAI_REASONING_SUMMARY_VALUES:
            raise ValueError(
                f"Provider '{provider_name}' has invalid reasoningSummary; expected auto, concise, detailed, or disabled."
            )
        provider["reasoningSummary"] = summary

    def _load_provider_document(self):
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

        return provider_config_path, payload, providers

    def _load_config(self):
        provider_config_path, _, providers = self._load_provider_document()

        normalized = copy.deepcopy(self._load_workspace_config(provider_config_path))
        normalized["providers"] = {
            str(provider_name): self._validate_provider_config(
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

        _, _, providers = self._load_provider_document()
        if provider_id not in providers:
            raise ValueError(f"Provider '{provider_id}' not found in configuration")

        return self._validate_provider_config(
            provider_id,
            providers[provider_id],
            require_api_key=True,
        )

    def get_all_providers(self):
        return self.get_config().get("providers", {})

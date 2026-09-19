from __future__ import annotations

from dataclasses import dataclass

from src.cli_provider_runtime.provider_adapter import provider_protocol
from src.config_loader import ConfigLoader
from src.provider_models import resolve_provider_model


@dataclass(frozen=True)
class ProviderBinding:
    provider_id: str
    model_id: str
    protocol: str

    @classmethod
    def resolve(cls, provider_id: str, model_id: str = "") -> "ProviderBinding":
        config = ConfigLoader().get_provider_config(provider_id)
        modes = config.get("supportmode")
        if not isinstance(modes, list) or not {"chat", "imagechat"}.intersection(modes):
            raise ValueError(f"Provider {provider_id!r} does not declare chat or imagechat support.")
        model = resolve_provider_model(config, model_id)
        if not model:
            raise ValueError(f"Provider {provider_id!r} has no model.")
        return cls(provider_id, model, provider_protocol(config))

    def request_config(self) -> dict:
        config = ConfigLoader().get_provider_config(self.provider_id)
        config["model"] = resolve_provider_model(config, self.model_id)
        return config

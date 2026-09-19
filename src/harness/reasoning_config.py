"""Provider-owned reasoning choices shared by configurable CLI harnesses."""
from src.provider_feature_matrix import build_provider_feature_matrix


def reasoning_options(provider_config: dict) -> list[str]:
    feature = build_provider_feature_matrix(provider_config)["reasoning_effort"]
    return list(feature["values"]) if feature["supported"] else []


def validate_reasoning_effort(value: object, provider_config: dict) -> str:
    if not isinstance(value, str):
        raise ValueError("Harness reasoning_effort must be a string.")
    if value and value not in reasoning_options(provider_config):
        allowed = ", ".join(reasoning_options(provider_config)) or "no explicit reasoning effort"
        raise ValueError(f"Harness reasoning_effort {value!r} is unsupported by this Provider; choose {allowed}.")
    return value

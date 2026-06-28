from collections.abc import Iterable

from src.config_loader import ConfigLoader


def build_provider_options_for_support_modes(supported_modes: Iterable[str], providers: object | None = None) -> list[dict]:
    if providers is None:
        try:
            providers = ConfigLoader().get_all_providers()
        except Exception:
            providers = {}

    supported_mode_set = {str(item or "").strip().lower() for item in supported_modes if str(item or "").strip()}
    options: list[dict] = []
    if not supported_mode_set or not isinstance(providers, dict):
        return options

    for provider_id, config in providers.items():
        if not isinstance(config, dict):
            continue
        modes = config.get("supportmode")
        mode_set = {str(item or "").strip().lower() for item in modes} if isinstance(modes, list) else set()
        if not mode_set.intersection(supported_mode_set):
            continue
        text = str(provider_id or "").strip()
        if text:
            options.append({"value": text, "label": text})

    options.sort(key=lambda item: item["label"].lower())
    return options


def build_provider_support_list(providers: object | None = None) -> list[dict]:
    if providers is None:
        try:
            providers = ConfigLoader().get_all_providers()
        except Exception:
            providers = {}

    items: list[dict] = []
    if not isinstance(providers, dict):
        return items

    for provider_id, config in providers.items():
        if not isinstance(provider_id, str):
            provider_id = str(provider_id)
        modes: list[str] = []
        features: dict = {}
        if isinstance(config, dict):
            raw_modes = config.get("supportmode")
            if isinstance(raw_modes, (list, tuple, set)):
                for mode in raw_modes:
                    if mode is None:
                        continue
                    value = str(mode).strip().lower()
                    if value:
                        modes.append(value)
            raw_features = config.get("features")
            if isinstance(raw_features, dict):
                features = dict(raw_features)
        if not modes:
            modes = ["chat"]
        items.append({"id": provider_id, "supportmode": modes, "features": features})

    items.sort(key=lambda item: item.get("id", ""))
    return items

"""Voice-call fields are independent of the node's inference Provider and modes."""
from src.providers.voice_registry import provider_voice_catalog


VOICE_CONFIG_SCHEMA = {
    "voice_provider_id": {
        "type": "select",
        "label": "语音 Provider",
        "options": [],
        "description": "独立于节点主模型。模型和音色随此 Provider 联动，修改后从下次通话生效。",
    },
    "voice_model": {
        "type": "select",
        "label": "语音模型",
        "options": [],
        "description": "选择此供应商支持的实时语音模型。模型访问权限由供应商校验。",
    },
    "voice": {
        "type": "select",
        "label": "音色",
        "options": [],
        "description": "仅用于此节点的语音通话，单人和多人通话共用此设置。",
    },
}


def materialize_voice_schema(schema: dict, providers: dict) -> dict:
    result = dict(schema)
    catalogs = {provider_id: config.get("voice") if "voice" in config else provider_voice_catalog(config)
                for provider_id, config in sorted(providers.items())}
    catalogs = {key: value for key, value in catalogs.items() if value is not None}
    result["voice_provider_id"] = {
        **VOICE_CONFIG_SCHEMA["voice_provider_id"],
        "catalogs": catalogs,
        "options": [
            {"value": "", "label": "请选择语音 Provider"},
            *[
                {"value": provider_id, "label": provider_id}
                for provider_id in catalogs
            ],
        ],
    }
    return result

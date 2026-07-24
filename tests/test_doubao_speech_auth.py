import pytest

from src.providers.doubao_speech_auth import (
    require_doubao_x_api_key,
    resolve_doubao_x_api_key,
)


def test_resolve_doubao_x_api_key_trims_configured_value():
    assert resolve_doubao_x_api_key({"xApiKey": "  speech-key  "}) == "speech-key"


@pytest.mark.parametrize("config", [None, {}, {"xApiKey": "   "}, {"apiKey": "general-key"}])
def test_require_doubao_x_api_key_rejects_missing_or_empty_value(config):
    with pytest.raises(ValueError, match="requires provider xApiKey"):
        require_doubao_x_api_key(config, "audio_generation")

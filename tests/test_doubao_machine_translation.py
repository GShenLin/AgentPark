import json

import pytest


class _TranslationHost:
    def __init__(self, result):
        self.config = {
            "apiKey": "general-key",
            "xApiKey": "speech-key",
            "speechBaseUrl": "https://openspeech.bytedance.com",
        }
        self.result = result
        self.request = None

    def _read_provider_config_from_file(self):
        return dict(self.config)

    def _post_json_with_retry(self, **kwargs):
        self.request = kwargs
        return self.result


def test_machine_translation_uses_input_text_and_returns_structured_items():
    from src.providers.doubao_machine_translation import DoubaoMachineTranslation

    host = _TranslationHost({
        "code": 20000000,
        "message": "ok",
        "data": {"translation_list": [{"translation": "Hello", "detected_source_language": "zh"}]},
    })
    result = DoubaoMachineTranslation(host).translate_text(
        [{"role": "user", "content": "你好"}],
        translation_target_language="en",
    )

    assert result["response"] == "Hello"
    payload = json.loads(host.request["payload_json"])
    assert payload == {"target_language": "en", "text_list": ["你好"]}
    assert host.request["headers"]["X-Api-Resource-Id"] == "volc.speech.mt"
    assert host.request["headers"]["X-Api-Key"] == "speech-key"


def test_machine_translation_enforces_list_contract():
    from src.providers.doubao_machine_translation import DoubaoMachineTranslation

    service = DoubaoMachineTranslation(_TranslationHost({}))
    with pytest.raises(ValueError, match="16-item"):
        service.translate_text(
            [],
            translation_text_list=json.dumps([str(index) for index in range(17)]),
        )

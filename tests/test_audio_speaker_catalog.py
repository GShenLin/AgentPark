import json

import pytest

from src.audio_speaker_catalog import AudioSpeakerCatalog


def test_audio_speaker_catalog_indexes_options_by_provider_and_voice_type(tmp_path):
    path = tmp_path / "audio_speaker.json"
    catalog = AudioSpeakerCatalog(str(path))

    count = catalog.replace_provider_index(
        "seed_audio",
        ["seed-tts-2.0"],
        [
            {"value": "speaker-1", "label": "Speaker One"},
            {"value": "speaker-2", "label": "Speaker Two"},
        ],
    )

    document = json.loads(path.read_text(encoding="utf-8"))
    assert count == 2
    assert document == {
        "version": 1,
        "providers": {
            "seed_audio": {
                "resource_ids": ["seed-tts-2.0"],
                "speakers": {
                    "speaker-1": "Speaker One",
                    "speaker-2": "Speaker Two",
                },
            }
        },
    }
    assert catalog.get_provider_options("seed_audio") == [
        {"value": "speaker-1", "label": "Speaker One"},
        {"value": "speaker-2", "label": "Speaker Two"},
    ]
    assert catalog.get_provider_options("other") == []


def test_audio_speaker_catalog_replaces_one_provider_without_removing_others(tmp_path):
    path = tmp_path / "audio_speaker.json"
    catalog = AudioSpeakerCatalog(str(path))
    catalog.replace_provider_index("first", ["resource-a"], [{"value": "a", "label": "A"}])
    catalog.replace_provider_index("second", ["resource-b"], [{"value": "b", "label": "B"}])
    catalog.replace_provider_index("first", ["resource-c"], [{"value": "c", "label": "C"}])

    assert catalog.get_provider_options("first") == [{"value": "c", "label": "C"}]
    assert catalog.get_provider_options("second") == [{"value": "b", "label": "B"}]


def test_audio_speaker_catalog_rejects_duplicate_voice_types(tmp_path):
    catalog = AudioSpeakerCatalog(str(tmp_path / "audio_speaker.json"))

    with pytest.raises(ValueError, match="duplicate VoiceType 'same'"):
        catalog.replace_provider_index(
            "seed_audio",
            ["seed-tts-2.0"],
            [
                {"value": "same", "label": "First"},
                {"value": "same", "label": "Second"},
            ],
        )


def test_audio_speaker_catalog_uses_provider_config_sibling(monkeypatch, tmp_path):
    provider_path = tmp_path / "modelProvider.json"
    provider_path.write_text('{"providers": {}}', encoding="utf-8")
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(provider_path))

    assert AudioSpeakerCatalog().path == str(tmp_path / "audio_speaker.json")

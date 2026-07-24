import json

import pytest


@pytest.fixture(autouse=True)
def isolated_memories_root(monkeypatch, tmp_path):
    from src import memory_root

    memories_root = tmp_path / "memories"
    monkeypatch.setattr(memory_root, "_active_memories_root", str(memories_root))


@pytest.fixture(autouse=True)
def isolated_provider_api_keys(monkeypatch, tmp_path):
    key_names = {
        "Ark", "DashScope", "DeepSeek", "DeepSeekTavern", "Hyper3D", "Kimi", "Krill",
        "Mimo", "NanoBanana371", "SeedAudio", "SeedAudioAccessKeyId",
        "SeedAudioSecretAccessKey", "SeedAudioXApiKey", "TencentHY3", "Speech", "ak-id",
        "audio-secret", "claude-key", "deepseek-key", "doubao-key", "first-key", "gemini-key",
        "general-key", "grok-key", "inline-secret", "kimi-key", "multi-secret", "openai-key",
        "private-secret", "public-secret", "second-key", "secret", "secret-key", "secret-value",
        "sk-secret", "speech-credential", "speech-key", "speech-secret", "test", "test-key",
        "token", "unconfigured-secret", "valid-key", "zhipu-key",
    }
    store_path = tmp_path / "apiKey.json"
    store_path.write_text(
        json.dumps({name: name for name in key_names}),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.config_loader.api_key_store_path", lambda _root: str(store_path))

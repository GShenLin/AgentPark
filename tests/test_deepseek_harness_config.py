import json

import pytest

from src.harness.adapters.deepseek_config import configure_runtime


def models(path):
    return json.loads(path.read_text(encoding="utf-8"))[0]["config"]["providers"]["agentpark"]


def test_overlay_keeps_history_and_refreshes_gateway(tmp_path):
    path = configure_runtime(tmp_path, "first", "http://localhost/first")
    assert models(path)["models"] == [{"id": "first"}]
    assert configure_runtime(tmp_path, "second", "http://localhost/second") == path
    assert models(path)["models"] == [{"id": "first"}, {"id": "second"}]
    assert models(path)["baseURL"] == "http://localhost/second"
    assert not (tmp_path / "settings.yaml").exists()


@pytest.mark.parametrize("name", ["settings.yaml", "settings.yaml.imported"])
def test_adopts_exact_existing_models_before_native_resume(tmp_path, name):
    source = tmp_path / name
    source.write_text(json.dumps({"llm-pi-ai": {"providers": {"agentpark": {
        "models": [{"id": "previous"}]}}}}), encoding="utf-8")
    path = configure_runtime(tmp_path, "current", "http://localhost/new")
    assert models(path)["models"] == [{"id": "previous"}, {"id": "current"}]
    assert not (tmp_path / "settings.yaml").exists()
    configure_runtime(tmp_path, "third", "http://localhost/third")
    assert models(path)["models"][-1] == {"id": "third"}


def test_invalid_overlay_is_not_replaced(tmp_path):
    path = tmp_path / "agentpark.patch.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="one llm-pi-ai"):
        configure_runtime(tmp_path, "new", "http://localhost/new")
    assert path.read_text() == "[]"

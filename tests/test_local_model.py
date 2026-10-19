import json
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.local_model.catalog import Catalog
from src.local_model.comfyui import ComfyAdapter
from src.local_model.contracts import Operation, ServiceConfig
from src.local_model.http import LocalHttp
from src.local_model.runtime import LocalModelService
from src.local_model.strata import StrataAdapter
from src.web_backend.local_model_api import register_local_model_routes


def config(tmp_path, kind="strata"):
    return ServiceConfig(name=kind, kind=kind, install_path=str(tmp_path),
                         python_path=sys.executable, endpoint="http://127.0.0.1:8080")


def strata_model(tmp_path):
    (tmp_path / "serve").mkdir()
    (tmp_path / "serve/server.py").touch()
    (tmp_path / "engine.exe").touch()
    (tmp_path / "model.gguf").write_bytes(b"test")
    path = tmp_path / "strata-test.json"
    path.write_text(json.dumps({"exe": str(tmp_path / "engine.exe"), "args": ["--native", str(tmp_path / "model.gguf")],
                                "model_name": "test-model"}), encoding="utf-8")
    return path


def test_catalog_survives_restart_and_does_not_delete_models(tmp_path):
    catalog = Catalog(tmp_path)
    item = catalog.save(config(tmp_path))
    assert Catalog(tmp_path).get(item["id"])["kind"] == "strata"
    with pytest.raises(ValueError, match="已经登记"):
        catalog.save(config(tmp_path))
    model = tmp_path / "weights.gguf"
    model.touch()
    catalog.remove(item["id"])
    assert model.exists()
    assert catalog.list() == []


@pytest.mark.parametrize("endpoint", ["https://example.com:8080", "http://127.0.0.1:8080/v1", "http://user:pass@localhost:8080", "http://localhost"])
def test_local_endpoint_contract(tmp_path, endpoint):
    with pytest.raises(ValidationError):
        config(tmp_path).model_copy(update={}).__class__(**{**config(tmp_path).model_dump(), "endpoint": endpoint})


def test_detection_works_offline_without_loading(tmp_path, monkeypatch):
    strata_model(tmp_path)
    calls = []
    def probe(self, path):
        calls.append(path)
        return None, "offline"
    monkeypatch.setattr(LocalHttp, "probe", probe)
    adapter = StrataAdapter(config(tmp_path).model_dump())
    result = adapter.inspect()
    assert result["installed"] and not result["online"]
    assert result["models"][0]["available"]
    assert calls == ["/health"]
    (tmp_path / "model.gguf").unlink()
    assert not adapter.inspect()["models"][0]["available"]


def test_strata_refuses_wrong_engine_and_wrong_loaded_model(tmp_path, monkeypatch):
    strata_model(tmp_path)
    monkeypatch.setattr(LocalHttp, "probe", lambda *_: ({"service": "other"}, ""))
    adapter = StrataAdapter(config(tmp_path).model_dump())
    assert not adapter.inspect()["online"]
    monkeypatch.setattr(LocalHttp, "request", lambda *_: {"service": "strata", "model": "different"})
    with pytest.raises(RuntimeError, match="另一份"):
        adapter.load("strata-test.json")


def test_strata_confirms_load_and_unload_and_passes_model(tmp_path, monkeypatch):
    strata_model(tmp_path)
    calls = []
    def request(self, path, body=None, **kwargs):
        calls.append((path, body))
        return {"service": "strata", "model": "test-model", "loaded": path != "/v1/unload"}
    monkeypatch.setattr(LocalHttp, "request", request)
    adapter = StrataAdapter(config(tmp_path).model_dump())
    adapter.load("strata-test.json")
    adapter.unload()
    assert ("/v1/load", {"model": "test-model"}) in calls
    assert ("/v1/unload", {}) in calls
    command = adapter.command(sys.executable, "strata-test.json", 8080)
    assert "--lazy" in command


def test_strata_import_keeps_original_and_does_not_overwrite(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = strata_model(source_dir)
    target = tmp_path / "target"
    target.mkdir()
    adapter = StrataAdapter(config(target).model_dump())
    adapter.import_model(str(source), "")
    assert source.exists()
    assert json.loads((target / source.name).read_text())["cwd"] == str(source_dir)
    with pytest.raises(ValueError, match="已经存在"):
        adapter.import_model(str(source), "")


def test_comfy_import_and_extra_paths(tmp_path, monkeypatch):
    source = tmp_path / "weights.safetensors"
    source.write_bytes(b"weights")
    adapter = ComfyAdapter(config(tmp_path, "comfyui").model_dump())
    adapter.import_model(str(source), "loras")
    assert source.exists()
    assert (tmp_path / "models/loras/weights.safetensors").read_bytes() == b"weights"
    with pytest.raises(ValueError, match="已经存在"):
        adapter.import_model(str(source), "loras")
    with pytest.raises(ValueError):
        adapter.import_model(str(source), "../outside")
    extra = tmp_path / "external"
    extra.mkdir()
    (extra / "other.gguf").touch()
    (tmp_path / "extra_model_paths.yaml").write_text("test:\n  base_path: external\n  diffusion_models: .\n")
    monkeypatch.setattr(LocalHttp, "probe", lambda *_: (None, "offline"))
    names = [m["name"] for m in adapter.inspect()["models"]]
    assert "weights.safetensors" in names and "other.gguf" in names


def test_comfy_busy_unload_and_workflow_contract(tmp_path, monkeypatch):
    adapter = ComfyAdapter(config(tmp_path, "comfyui").model_dump())
    calls = []
    def busy(self, path, *args, **kwargs):
        calls.append(path)
        if path == "/system_stats":
            return {"system": {"comfyui_version": "test"}}
        return {"queue_running": [[1]], "queue_pending": []}
    monkeypatch.setattr(LocalHttp, "request", busy)
    with pytest.raises(RuntimeError, match="任务"):
        adapter.unload()
    assert "/free" not in calls
    workflow = tmp_path / "workflow.json"
    workflow.write_text('{"nodes": []}')
    adapter.config["workflow_path"] = str(workflow)
    with pytest.raises(ValueError, match="API 格式"):
        adapter.load("")


def test_comfy_unload_reports_submission_not_completion(tmp_path, monkeypatch):
    adapter = ComfyAdapter(config(tmp_path, "comfyui").model_dump())
    calls = []
    def request(self, path, body=None, **kwargs):
        calls.append((path, body))
        return {"system": {"comfyui_version": "test"}, "queue_running": [], "queue_pending": []}
    monkeypatch.setattr(LocalHttp, "request", request)
    assert "已提交" in adapter.unload()["message"]
    assert calls[-1] == ("/free", {"unload_models": True, "free_memory": True})


def test_only_one_operation_and_failed_job_visible(tmp_path, monkeypatch):
    service = LocalModelService(tmp_path)
    item = service.save(config(tmp_path))
    gate = threading.Event()
    def load(_):
        gate.wait(2)
        raise RuntimeError("explicit failure")
    monkeypatch.setattr(StrataAdapter, "load", lambda self, model_id: load(model_id))
    job = service.operate(item["id"], Operation(action="load"))
    try:
        with pytest.raises(RuntimeError):
            service.operate(item["id"], Operation(action="unload"))
        with pytest.raises(RuntimeError):
            service.remove(item["id"])
    finally:
        gate.set()
    for _ in range(100):
        result = service.job(job["id"])
        if result["state"] != "running":
            break
        time.sleep(.01)
    assert result["state"] == "failed" and result["message"] == "explicit failure"


def test_api_owner_access_and_persistence(tmp_path):
    app = FastAPI()
    register_local_model_routes(app, LocalModelService(tmp_path))
    with TestClient(app, client=("10.0.0.2", 1234)) as client:
        assert client.get("/api/local-model").status_code == 403
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        result = client.post("/api/local-model", json=config(tmp_path).model_dump())
        assert result.status_code == 200
        assert client.get("/api/local-model").json()["services"][0]["name"] == "strata"
        assert client.get("/api/local-model/jobs/missing").status_code == 404
        assert client.post("/api/local-model", json={**config(tmp_path).model_dump(), "automatic": True}).status_code == 422

import json
from pathlib import Path
import runpy
from types import SimpleNamespace
import uuid

from PIL import Image
import pytest

from nodes.agent_skill_loader import load_node_skills
from nodes.agent_skill_scripts import register_skill_script_tools
from src.providers.curl_types import CurlResponse, CurlTransportError
from src.tool.base_tool import BaseTool

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents/skills/qwen-turbo-image-edit"
edit = SimpleNamespace(**runpy.run_path(str(SKILL / "scripts/comfy_edit.py")))


def response(payload, status=200):
    return CurlResponse(json.dumps(payload), status)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    node = tmp_path / "node"
    node.mkdir()
    monkeypatch.setenv("AGENTPARK_NODE_DIRECTORY", str(node))
    monkeypatch.delenv("AGENTPARK_COMFYUI_URL", raising=False)
    source = tmp_path / "原图.png"
    Image.new("RGB", (32, 32), "blue").save(source)
    return node, source


def object_info():
    graph = json.loads((SKILL / "assets/edit-api.json").read_text())
    info = {node["class_type"]: {} for node in graph.values()}
    for node_id, field in (("1", "unet_name"), ("2", "clip_name"), ("3", "vae_name")):
        node = graph[node_id]
        info[node["class_type"]] = {"input": {"required": {field: [[node["inputs"][field]]]}}}
    return info


def receipt(node, **updates):
    token = uuid.uuid4().hex
    path = node / "generated_images/qwen_turbo" / token / "job.json"
    path.parent.mkdir(parents=True)
    job = {"kind": edit.KIND, "client_id": token, "prompt_id": str(uuid.uuid4()),
           "server": "http://127.0.0.1:8188", "status": "submitted"}
    job.update(updates)
    edit.save_job(path, job)
    return path, job


def test_submit_uploads_exact_original_and_keeps_turbo_contract(workspace, monkeypatch):
    node, source = workspace
    original = source.read_bytes()
    calls = []
    pid = str(uuid.uuid4())

    def exchange(self, **kwargs):
        calls.append(kwargs)
        if kwargs["url"].endswith("/object_info"):
            return response(object_info())
        if kwargs["url"].endswith("/upload/image"):
            assert original in kwargs["body"]
            return response({"name": "uploaded.png", "subfolder": "folder", "type": "input"})
        return response({"prompt_id": pid, "node_errors": {}})

    monkeypatch.setattr(edit.CurlHttpTransport, "request", exchange)
    result = edit.submit({"image_path": str(source), "prompt": "只把茶壶改红", "seed": 123})
    assert result["status"] == "submitted" and result["prompt_id"] == pid
    assert source.read_bytes() == original
    graph = json.loads(calls[-1]["body"])["prompt"]
    assert graph["7"]["inputs"]["image"] == "folder/uploaded.png"
    assert graph["6"]["inputs"]["prompt"] == "只把茶壶改红"
    assert graph["8"]["inputs"]["latent_image"] == ["6", 2]
    assert graph["8"]["inputs"]["cfg"] == 1 and graph["8"]["inputs"]["noise_seed"] == 123
    assert graph["5"]["inputs"]["sigmas"] == "1, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0"
    assert all(not call["follow_redirects"] and not call["trust_env"] for call in calls)
    assert Path(result["job_file"]).parent.parent == node / "generated_images/qwen_turbo"


def test_missing_model_stops_before_upload(workspace, monkeypatch):
    info = object_info()
    info["UNETLoader"]["input"]["required"]["unet_name"] = [[]]
    calls = []
    def exchange(self, **kwargs):
        calls.append(kwargs)
        return response(info)
    monkeypatch.setattr(edit.CurlHttpTransport, "request", exchange)
    with pytest.raises(ValueError, match="Required model"):
        edit.submit({"image_path": str(workspace[1]), "prompt": "edit"})
    assert len(calls) == 1


@pytest.mark.parametrize("url", ["https://127.0.0.1:8188", "http://example.com", "http://127.0.0.1.evil.test", "http://user@localhost", "http://localhost/path"])
def test_only_local_comfy_endpoint(url):
    with pytest.raises(ValueError):
        edit.local_url(url)


def test_jpeg_input_supported(tmp_path):
    path = tmp_path / "photo.jpg"
    Image.new("RGB", (16, 16)).save(path)
    assert edit.image_bytes(path)[1] == ".jpg"


@pytest.mark.parametrize("status", [400, 500, None])
def test_failed_submission_keeps_receipt_without_retry(workspace, monkeypatch, status):
    calls = []
    def exchange(self, **kwargs):
        calls.append(kwargs["url"])
        if kwargs["url"].endswith("object_info"):
            return response(object_info())
        if kwargs["url"].endswith("upload/image"):
            return response({"name": "a.png", "type": "input"})
        if status is None:
            raise CurlTransportError("connection lost")
        return response({"error": "failed"}, status)
    monkeypatch.setattr(edit.CurlHttpTransport, "request", exchange)
    job = edit.submit({"image_path": str(workspace[1]), "prompt": "edit"})
    assert job["status"] == ("error" if status == 400 else "submission_unknown")
    assert Path(job["job_file"]).is_file() and len(calls) == 3


def test_result_downloads_and_survives_server_history_clear(workspace, monkeypatch):
    path, job = receipt(workspace[0])
    image = workspace[1].read_bytes()
    def exchange(self, **kwargs):
        if "/history/" in kwargs["url"]:
            return response({job["prompt_id"]: {"status": {"status_str": "success"}, "outputs": {"10": {"images": [{"filename": "a.png", "subfolder": "x", "type": "output"}]}}}})
        return CurlResponse("", 200, raw_body=image)
    monkeypatch.setattr(edit.CurlHttpTransport, "request", exchange)
    result = edit.result({"job_file": str(path), "wait_seconds": 0})
    assert result["status"] == "success" and Path(result["image_path"]).read_bytes() == image
    monkeypatch.setattr(edit.CurlHttpTransport, "request", lambda *a, **k: pytest.fail("Cached result should not contact ComfyUI"))
    assert edit.result({"job_file": str(path)})["image_path"] == result["image_path"]


def test_queued_result_never_submits(workspace, monkeypatch):
    path, job = receipt(workspace[0])
    def exchange(self, **kwargs):
        assert kwargs["method"] == "GET"
        return response({"queue_running": [], "queue_pending": [[0, job["prompt_id"]]]} if kwargs["url"].endswith("/queue") else {})
    monkeypatch.setattr(edit.CurlHttpTransport, "request", exchange)
    assert edit.result({"job_file": str(path), "wait_seconds": 0})["status"] == "queued"


def test_uncertain_submission_recovers_by_client_id(workspace, monkeypatch):
    path, job = receipt(workspace[0], prompt_id=None, status="submission_unknown")
    pid = str(uuid.uuid4())
    def exchange(self, **kwargs):
        assert kwargs["method"] == "GET"
        if kwargs["url"].endswith("/queue"):
            return response({"queue_running": [[0, pid, {}, {"client_id": job["client_id"]}]], "queue_pending": []})
        return response({})
    monkeypatch.setattr(edit.CurlHttpTransport, "request", exchange)
    result = edit.result({"job_file": str(path), "wait_seconds": 0})
    assert result["status"] == "running" and result["prompt_id"] == pid


def test_execution_error_is_not_an_image(workspace, monkeypatch):
    path, job = receipt(workspace[0])
    monkeypatch.setattr(edit.CurlHttpTransport, "request", lambda *a, **k: response({job["prompt_id"]: {"status": {"status_str": "error", "messages": [["execution_error", {"exception_message": "OOM"}]]}}}))
    result = edit.result({"job_file": str(path)})
    assert result["status"] == "error" and "image_path" not in result
    assert "OOM" in json.dumps(result)


def test_skill_registers_and_real_subprocess_rejects_bad_input():
    class Agent:
        config = {}
    agent = Agent()
    agent.tools = BaseTool(agent)
    skill = load_node_skills(["qwen-turbo-image-edit"], skill_root=str(ROOT / ".agents/skills"))
    names = register_skill_script_tools(agent, skill)
    assert names == ["skill__qwen-turbo-image-edit__submit", "skill__qwen-turbo-image-edit__result"]
    result = json.loads(agent.tools.function_map[names[0]](image_path="relative.png", prompt="edit", resolution=2048))
    assert result["status"] == "error" and "resolution" in result["stderr"]

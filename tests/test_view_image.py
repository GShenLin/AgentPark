import base64
from io import BytesIO
import json
from types import SimpleNamespace

from PIL import Image
import pytest

from functions.image_tools import view_image
from src.providers.responses_followup import build_responses_followup_items
from src.providers.tool_image_input import build_tool_image_content_item
from src.tool.base_tool import BaseTool
from src.tool.local_image import image_dimensions
from src.tool.tool_call_protocol import from_openai_tool_call


def make_agent(tmp_path):
    return SimpleNamespace(config={
        "working_path": str(tmp_path), "model": "vision-test", "responsesApi": True,
    })


def image_call(path, **kwargs):
    return from_openai_tool_call({"id": "call-image", "function": {
        "name": "view_image", "arguments": json.dumps({"path": str(path), **kwargs}),
    }})


def image_tools(agent):
    tools = BaseTool(agent)
    tools.addTool("system_tools")
    return tools


def test_local_image_reaches_responses_as_image_in_own_tool_output(tmp_path):
    path = tmp_path / "图 片.png"
    Image.new("RGB", (47, 31), "red").save(path)
    execution = image_tools(make_agent(tmp_path)).execute_tool_call(image_call(path.name))
    assert execution.status == "completed"
    assert "base64" not in execution.cleaned_result
    assert json.loads(execution.cleaned_result)["image_path"] == str(path)
    calls = []
    runtime = SimpleNamespace(
        _responses_tool_output=lambda value: value.cleaned_result,
        Message=lambda *args, **kwargs: calls.append((args, kwargs)),
        _build_non_retryable_tool_warning=lambda *args: "",
        _validate_responses_followup_call_id=lambda call_id: None,
    )
    followup = build_responses_followup_items(runtime, [execution])
    assert len(followup) == 1
    assert followup[0]["type"] == "function_call_output"
    assert followup[0]["call_id"] == "call-image"
    image = followup[0]["output"][1]
    assert image["type"] == "input_image"
    assert image["detail"] == "high"
    assert base64.b64decode(image["image_url"].split(",", 1)[1]) == path.read_bytes()
    assert "data:image" not in str(calls)


@pytest.mark.parametrize("detail,expected", [("high", (1600, 1600)), ("original", (3200, 3200))])
def test_image_detail_resizes_with_codex_patch_budget(tmp_path, detail, expected):
    path = tmp_path / "large.png"
    Image.new("RGB", (4000, 4000), "blue").save(path)
    result = json.loads(view_image(str(path), detail=detail))
    image = Image.open(BytesIO(base64.b64decode(result["base64_image"])))
    assert image.size == expected
    assert result["source_width"] == result["source_height"] == 4000
    assert result["resized"] is True


@pytest.mark.parametrize("size", [(655, 549), (1, 10000), (10000, 1), (8000, 3500), (1024, 1024)])
@pytest.mark.parametrize("detail,dimension,patches", [("high", 2048, 2500), ("original", 6000, 10000)])
def test_prepared_dimensions_fit_detail_limits(size, detail, dimension, patches):
    w, h = image_dimensions(*size, detail)
    assert 0 < w <= min(size[0], dimension)
    assert 0 < h <= min(size[1], dimension)
    assert ((w + 31) // 32) * ((h + 31) // 32) <= patches


def test_exif_orientation_is_applied_before_image_dimensions(tmp_path):
    path = tmp_path / "rotate.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (80, 40), "red").save(path, exif=exif)
    result = json.loads(view_image(str(path)))
    assert (result["width"], result["height"]) == (40, 80)
    decoded = Image.open(BytesIO(base64.b64decode(result["base64_image"])))
    assert decoded.size == (40, 80)


@pytest.mark.parametrize("target", ["missing.png", "bad.png", "."])
def test_bad_image_is_a_model_visible_tool_error(tmp_path, target):
    (tmp_path / "bad.png").write_text("not an image", encoding="utf-8")
    execution = image_tools(make_agent(tmp_path)).execute_tool_call(image_call(target))
    assert execution.status == "exception"
    assert execution.images == ()
    assert json.loads(execution.cleaned_result)["error"]


def test_path_only_tool_image_is_encoded_instead_of_sent_as_windows_path(tmp_path):
    path = tmp_path / "image.png"
    Image.new("RGB", (2, 3), "green").save(path)
    image = build_tool_image_content_item({"path": str(path)})
    assert image["image_url"].startswith("data:image/png;base64,")
    assert base64.b64decode(image["image_url"].split(",", 1)[1]) == path.read_bytes()


def test_remote_view_image_uses_worker_bytes_and_preserves_path(tmp_path, monkeypatch):
    from src.remote_workspace.operations import WorkspaceOperationRegistry
    from src.remote_worker.protocol import RemoteTask
    from src.remote_workspace.routing import remote_workspace_target

    path = tmp_path / "remote.png"
    Image.new("RGB", (13, 17), "green").save(path)
    agent = make_agent(tmp_path)
    agent.config.update(remote_enabled=True, remote_worker_id="worker-1")
    assert remote_workspace_target(agent, "view_image") is not None
    calls = []

    def dispatch(_agent, name, args, **kwargs):
        calls.append(name)
        task = RemoteTask(task_id="task-image", tool_name=name, arguments=args,
                          working_path=str(tmp_path), timeout_seconds=10)
        return True, WorkspaceOperationRegistry().execute(task)

    monkeypatch.setattr("src.tool.base_tool.dispatch_remote_workspace_tool", dispatch)
    execution = image_tools(agent).execute_tool_call(image_call("remote.png"))
    assert calls == ["view_image"]
    assert execution.status == "completed", execution.error
    assert base64.b64decode(execution.images[0]["base64"]) == path.read_bytes()

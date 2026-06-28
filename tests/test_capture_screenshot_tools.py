import json

from functions import capture_screenshot_tools
from src.tool.base_tool import BaseTool
from src.tool.tool_result_processing import process_tool_result_outcome


class _DummyAgent:
    config = {}


def test_capture_screenshot_returns_image_without_saving(monkeypatch):
    from PIL import Image

    captured = {}

    def fake_capture(region, backend):
        captured["region"] = region
        captured["backend"] = backend
        return Image.new("RGB", (region["width"], region["height"]), (10, 20, 30)), backend, dict(region)

    monkeypatch.setattr(capture_screenshot_tools, "capture_image", fake_capture)

    raw = capture_screenshot_tools.capture_screenshot(
        capture_region={"left": 11, "top": 22, "width": 5, "height": 4},
        backend="gdi",
        png_compress_level=0,
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert payload["backend"] == "gdi"
    assert payload["saved"] is False
    assert isinstance(payload["base64_image"], str) and payload["base64_image"]
    assert payload["mime_type"] == "image/png"
    assert payload["width"] == 5
    assert payload["height"] == 4
    assert payload["encoded_size_bytes"] > 0
    assert payload["capture_region"] == {"left": 11, "top": 22, "width": 5, "height": 4}
    assert captured["region"] == {"left": 11, "top": 22, "width": 5, "height": 4}
    assert captured["backend"] == "gdi"

    outcome = process_tool_result_outcome(payload)
    assert outcome.image_data is not None
    assert outcome.image_data["base64"]
    assert outcome.image_data["path"] == ""
    assert outcome.image_data["mime_type"] == "image/png"


def test_process_tool_result_passes_base64_image_through_unchanged():
    payload = {
        "status": "success",
        "base64_image": "raw-image-data",
        "mime_type": "image/png",
        "path": "",
    }

    outcome = process_tool_result_outcome(payload)

    assert outcome.image_data is not None
    assert outcome.image_data["base64"] == "raw-image-data"
    assert outcome.diagnostics == ()


def test_capture_screenshot_auto_format_returns_png_without_file_output(monkeypatch):
    from PIL import Image

    def fake_capture(region, backend):
        return Image.new("RGB", (3, 2), (10, 20, 30)), backend, dict(region)

    monkeypatch.setattr(capture_screenshot_tools, "capture_image", fake_capture)

    raw = capture_screenshot_tools.capture_screenshot(
        capture_region={"left": 0, "top": 0, "width": 3, "height": 2},
        backend="gdi",
        image_format="auto",
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert payload["saved"] is False
    assert payload["mime_type"] == "image/png"
    assert payload["format"] == "png"
    assert isinstance(payload["base64_image"], str) and payload["base64_image"]


def test_capture_screenshot_rejects_invalid_region():
    raw = capture_screenshot_tools.capture_screenshot(capture_region={"left": 0, "top": 0, "width": 0, "height": 10})
    payload = json.loads(raw)

    assert payload["status"] == "error"
    assert "width and capture_region.height must be positive" in payload["error"]


def test_capture_screenshot_rejects_boolean_region_values():
    raw = capture_screenshot_tools.capture_screenshot(
        capture_region={"left": True, "top": 0, "width": 100, "height": 100}
    )
    payload = json.loads(raw)

    assert payload["status"] == "error"
    assert "capture_region.left must be a number" in payload["error"]


def test_capture_screenshot_treats_zero_sized_region_as_full_screen(monkeypatch):
    from PIL import Image

    captured = {}

    def fake_capture(region, backend):
        captured["region"] = region
        return Image.new("RGB", (7, 6), (10, 20, 30)), backend, {"left": 0, "top": 0, "width": 7, "height": 6}

    monkeypatch.setattr(capture_screenshot_tools, "capture_image", fake_capture)

    raw = capture_screenshot_tools.capture_screenshot(
        capture_region={"left": 0, "top": 0, "width": 0, "height": 0},
        backend="gdi",
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert captured["region"] is None
    assert isinstance(payload["base64_image"], str) and payload["base64_image"]
    assert payload["capture_region"] == {"left": 0, "top": 0, "width": 7, "height": 6}


def test_capture_screenshot_tool_registers_as_standalone_tool_only():
    direct = BaseTool(_DummyAgent())
    direct.addTool("capture_screenshot_tools")
    assert "capture_screenshot" in direct.function_map
    assert any(item.get("function", {}).get("name") == "capture_screenshot" for item in direct.tool_declarations)
    parameters = capture_screenshot_tools.capture_screenshot_declaration["function"]["parameters"]
    assert "output_path" not in parameters["properties"]
    assert "save_to_file" not in parameters["properties"]

    system = BaseTool(_DummyAgent())
    system.addTool("system_tools")
    assert "capture_screenshot" not in system.function_map

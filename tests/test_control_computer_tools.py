import json

from functions import control_computer_tools
from src import desktop_input
from src.tool.base_tool import BaseTool


class _DummyAgent:
    config = {}


class _FakePyAutoGui:
    def __init__(self):
        self.PAUSE = None
        self.calls = []

    def moveTo(self, x, y, duration=0):
        self.calls.append(("moveTo", x, y, duration))

    def click(self, **kwargs):
        self.calls.append(("click", kwargs))

    def mouseDown(self, **kwargs):
        self.calls.append(("mouseDown", kwargs))

    def mouseUp(self, **kwargs):
        self.calls.append(("mouseUp", kwargs))

    def dragTo(self, x, y, duration=0, button="left"):
        self.calls.append(("dragTo", x, y, duration, button))

    def press(self, key, presses=1, interval=0):
        self.calls.append(("press", key, presses, interval))

    def keyDown(self, key):
        self.calls.append(("keyDown", key))

    def keyUp(self, key):
        self.calls.append(("keyUp", key))

    def hotkey(self, *keys, interval=0):
        self.calls.append(("hotkey", keys, interval))

    def write(self, text, interval=0):
        self.calls.append(("write", text, interval))


def test_control_computer_click_dispatches_to_backend(monkeypatch):
    fake = _FakePyAutoGui()
    monkeypatch.setattr(desktop_input, "_load_pyautogui", lambda: fake)

    raw = control_computer_tools.control_computer(
        action="click",
        x=10,
        y=20,
        button="right",
        clicks=2,
        interval_ms=25,
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert payload["action"] == "click"
    assert payload["x"] == 10
    assert payload["y"] == 20
    assert payload["button"] == "right"
    assert payload["clicks"] == 2
    assert fake.calls == [
        ("click", {"x": 10, "y": 20, "button": "right", "clicks": 2, "interval": 0.025})
    ]


def test_control_computer_drag_and_hotkey(monkeypatch):
    fake = _FakePyAutoGui()
    monkeypatch.setattr(desktop_input, "_load_pyautogui", lambda: fake)

    drag_payload = json.loads(
        control_computer_tools.control_computer(
            action="drag",
            x=1,
            y=2,
            end_x=30,
            end_y=40,
            duration_ms=150,
        )
    )
    hotkey_payload = json.loads(
        control_computer_tools.control_computer(
            action="hotkey",
            keys=["ctrl", "shift", "esc"],
            interval_ms=10,
        )
    )

    assert drag_payload["status"] == "success"
    assert hotkey_payload["status"] == "success"
    assert fake.calls == [
        ("moveTo", 1, 2, 0),
        ("dragTo", 30, 40, 0.15, "left"),
        ("hotkey", ("ctrl", "shift", "esc"), 0.01),
    ]


def test_control_computer_hold_key_releases_key_on_success(monkeypatch):
    fake = _FakePyAutoGui()
    monkeypatch.setattr(desktop_input, "_load_pyautogui", lambda: fake)
    monkeypatch.setattr(desktop_input.time, "sleep", lambda _seconds: None)

    payload = json.loads(
        control_computer_tools.control_computer(action="hold_key", key="shift", duration_ms=500)
    )

    assert payload["status"] == "success"
    assert payload["key"] == "shift"
    assert fake.calls == [("keyDown", "shift"), ("keyUp", "shift")]


def test_control_computer_hold_mouse_releases_button(monkeypatch):
    fake = _FakePyAutoGui()
    monkeypatch.setattr(desktop_input, "_load_pyautogui", lambda: fake)
    monkeypatch.setattr(desktop_input.time, "sleep", lambda _seconds: None)

    payload = json.loads(
        control_computer_tools.control_computer(
            action="hold_mouse",
            x=5,
            y=6,
            button="left",
            duration_ms=300,
        )
    )

    assert payload["status"] == "success"
    assert payload["action"] == "hold_mouse"
    assert payload["duration_ms"] == 300
    assert fake.calls == [
        ("mouseDown", {"x": 5, "y": 6, "button": "left"}),
        ("mouseUp", {"x": 5, "y": 6, "button": "left"}),
    ]


def test_control_computer_rejects_invalid_action_without_backend(monkeypatch):
    def fail_load():
        raise AssertionError("backend should not load for invalid action")

    monkeypatch.setattr(desktop_input, "_load_pyautogui", fail_load)

    payload = json.loads(control_computer_tools.control_computer(action="unknown"))

    assert payload["status"] == "error"
    assert "action must be one of" in payload["error"]


def test_control_computer_tool_registers_as_standalone_tool_only():
    direct = BaseTool(_DummyAgent())
    direct.addTool("control_computer_tools")
    assert "control_computer" in direct.function_map
    assert any(item.get("function", {}).get("name") == "control_computer" for item in direct.tool_declarations)
    actions = control_computer_tools.control_computer_declaration["function"]["parameters"]["properties"]["action"]
    assert "hold_mouse" in actions["enum"]

    system = BaseTool(_DummyAgent())
    system.addTool("system_tools")
    assert "control_computer" not in system.function_map

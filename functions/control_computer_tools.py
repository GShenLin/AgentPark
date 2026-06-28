import json

from src.desktop_input import DesktopInputError, perform_desktop_input
from src.runtime_cancellation import CancellationRequested, cancel_source_from_agent, raise_if_cancel_requested


def control_computer(
    action,
    x=None,
    y=None,
    end_x=None,
    end_y=None,
    button="left",
    clicks=1,
    interval_ms=80,
    duration_ms=0,
    key="",
    keys=None,
    text="",
    agent=None,
):
    """
    Simulate local mouse and keyboard input.
    """
    try:
        cancel_source = cancel_source_from_agent(agent)
        raise_if_cancel_requested(cancel_source)
        result = perform_desktop_input(
            action=action,
            x=x,
            y=y,
            end_x=end_x,
            end_y=end_y,
            button=button,
            clicks=clicks,
            interval_ms=interval_ms,
            duration_ms=duration_ms,
            key=key,
            keys=keys,
            text=text,
        )
        raise_if_cancel_requested(cancel_source)
        return json.dumps(result.to_payload(), ensure_ascii=False)
    except CancellationRequested as exc:
        return json.dumps({"status": "stopped", "tool": "control_computer", "error": str(exc)}, ensure_ascii=False)
    except DesktopInputError as exc:
        return json.dumps({"status": "error", "tool": "control_computer", "error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {
                "status": "exception",
                "tool": "control_computer",
                "error": f"{type(exc).__name__}: {exc}",
            },
            ensure_ascii=False,
        )


control_computer_declaration = {
    "type": "function",
    "function": {
        "name": "control_computer",
        "description": (
            "Simulate local desktop mouse and keyboard input. Use after capture_screenshot to act on visible UI, "
            "then capture another screenshot to verify the result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "move_mouse",
                        "click",
                        "hold_mouse",
                        "mouse_down",
                        "mouse_up",
                        "drag",
                        "press_key",
                        "hold_key",
                        "hotkey",
                        "type_text",
                    ],
                    "description": "The input action to perform.",
                },
                "x": {
                    "type": "integer",
                    "description": "Screen x coordinate for mouse actions. Required for move_mouse and drag start.",
                },
                "y": {
                    "type": "integer",
                    "description": "Screen y coordinate for mouse actions. Required for move_mouse and drag start.",
                },
                "end_x": {
                    "type": "integer",
                    "description": "Drag target x coordinate. Required for drag.",
                },
                "end_y": {
                    "type": "integer",
                    "description": "Drag target y coordinate. Required for drag.",
                },
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "description": "Mouse button for click, hold_mouse, mouse_down, mouse_up, and drag.",
                    "default": "left",
                },
                "clicks": {
                    "type": "integer",
                    "description": "Number of mouse clicks or key presses. Range: 1-20.",
                    "default": 1,
                },
                "interval_ms": {
                    "type": "integer",
                    "description": "Delay between repeated clicks, key presses, or hotkey key-down events. Range: 0-30000.",
                    "default": 80,
                },
                "duration_ms": {
                    "type": "integer",
                    "description": "Movement, drag, or hold duration. Range: 0-30000.",
                    "default": 0,
                },
                "key": {
                    "type": "string",
                    "description": "Keyboard key name for press_key or hold_key, for example enter, tab, ctrl, shift, a.",
                },
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keyboard combination for hotkey, for example ['ctrl', 'l'] or ['ctrl', 'shift', 'esc'].",
                },
                "text": {
                    "type": "string",
                    "description": "Text to type for type_text. Maximum 4000 characters.",
                },
            },
            "required": ["action"],
        },
    },
}

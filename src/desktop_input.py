from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


class DesktopInputError(ValueError):
    pass


_ACTIONS = {
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
}
_BUTTONS = {"left", "right", "middle"}
_MAX_DURATION_MS = 30000
_MAX_CLICKS = 20
_MAX_TEXT_CHARS = 4000


@dataclass(frozen=True)
class DesktopInputResult:
    action: str
    elapsed_ms: int
    details: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": "success",
            "action": self.action,
            "elapsed_ms": self.elapsed_ms,
            **self.details,
        }


def perform_desktop_input(
    *,
    action: str,
    x: Any = None,
    y: Any = None,
    end_x: Any = None,
    end_y: Any = None,
    button: Any = "left",
    clicks: Any = 1,
    interval_ms: Any = 80,
    duration_ms: Any = 0,
    key: Any = "",
    keys: Any = None,
    text: Any = "",
) -> DesktopInputResult:
    validated_action = _validate_action(action)
    started_at = time.perf_counter()
    controller = _load_pyautogui()

    if validated_action == "move_mouse":
        x_value, y_value = _parse_point(x, y)
        move_duration = _duration_seconds(duration_ms)
        controller.moveTo(x_value, y_value, duration=move_duration)
        return _result(started_at, validated_action, x=x_value, y=y_value, duration_ms=int(move_duration * 1000))

    if validated_action == "click":
        x_value, y_value = _parse_optional_point(x, y)
        button_value = _validate_button(button)
        click_count = _parse_clicks(clicks)
        interval_seconds = _interval_seconds(interval_ms)
        if x_value is None:
            controller.click(button=button_value, clicks=click_count, interval=interval_seconds)
        else:
            controller.click(x=x_value, y=y_value, button=button_value, clicks=click_count, interval=interval_seconds)
        return _result(
            started_at,
            validated_action,
            x=x_value,
            y=y_value,
            button=button_value,
            clicks=click_count,
            interval_ms=int(interval_seconds * 1000),
        )

    if validated_action == "hold_mouse":
        x_value, y_value = _parse_optional_point(x, y)
        button_value = _validate_button(button)
        hold_duration = _duration_seconds(duration_ms, default_ms=500)
        if x_value is None:
            controller.mouseDown(button=button_value)
        else:
            controller.mouseDown(x=x_value, y=y_value, button=button_value)
        try:
            time.sleep(hold_duration)
        finally:
            if x_value is None:
                controller.mouseUp(button=button_value)
            else:
                controller.mouseUp(x=x_value, y=y_value, button=button_value)
        return _result(
            started_at,
            validated_action,
            x=x_value,
            y=y_value,
            button=button_value,
            duration_ms=int(hold_duration * 1000),
        )

    if validated_action == "mouse_down":
        x_value, y_value = _parse_optional_point(x, y)
        button_value = _validate_button(button)
        if x_value is None:
            controller.mouseDown(button=button_value)
        else:
            controller.mouseDown(x=x_value, y=y_value, button=button_value)
        return _result(started_at, validated_action, x=x_value, y=y_value, button=button_value)

    if validated_action == "mouse_up":
        x_value, y_value = _parse_optional_point(x, y)
        button_value = _validate_button(button)
        if x_value is None:
            controller.mouseUp(button=button_value)
        else:
            controller.mouseUp(x=x_value, y=y_value, button=button_value)
        return _result(started_at, validated_action, x=x_value, y=y_value, button=button_value)

    if validated_action == "drag":
        x_value, y_value = _parse_point(x, y)
        end_x_value, end_y_value = _parse_point(end_x, end_y, prefix="end_")
        button_value = _validate_button(button)
        drag_duration = _duration_seconds(duration_ms, default_ms=200)
        controller.moveTo(x_value, y_value, duration=0)
        controller.dragTo(end_x_value, end_y_value, duration=drag_duration, button=button_value)
        return _result(
            started_at,
            validated_action,
            x=x_value,
            y=y_value,
            end_x=end_x_value,
            end_y=end_y_value,
            button=button_value,
            duration_ms=int(drag_duration * 1000),
        )

    if validated_action == "press_key":
        key_value = _validate_key(key)
        press_count = _parse_clicks(clicks)
        interval_seconds = _interval_seconds(interval_ms)
        controller.press(key_value, presses=press_count, interval=interval_seconds)
        return _result(
            started_at,
            validated_action,
            key=key_value,
            presses=press_count,
            interval_ms=int(interval_seconds * 1000),
        )

    if validated_action == "hold_key":
        key_value = _validate_key(key)
        hold_duration = _duration_seconds(duration_ms, default_ms=500)
        controller.keyDown(key_value)
        try:
            time.sleep(hold_duration)
        finally:
            controller.keyUp(key_value)
        return _result(started_at, validated_action, key=key_value, duration_ms=int(hold_duration * 1000))

    if validated_action == "hotkey":
        key_values = _validate_keys(keys)
        interval_seconds = _interval_seconds(interval_ms)
        controller.hotkey(*key_values, interval=interval_seconds)
        return _result(started_at, validated_action, keys=key_values, interval_ms=int(interval_seconds * 1000))

    if validated_action == "type_text":
        text_value = _validate_text(text)
        interval_seconds = _interval_seconds(interval_ms, default_ms=0)
        controller.write(text_value, interval=interval_seconds)
        return _result(
            started_at,
            validated_action,
            chars=len(text_value),
            interval_ms=int(interval_seconds * 1000),
        )

    raise DesktopInputError(f"unsupported action: {validated_action}")


def _load_pyautogui():
    import pyautogui  # type: ignore

    pyautogui.PAUSE = 0
    return pyautogui


def _validate_action(value: Any) -> str:
    if not isinstance(value, str):
        raise DesktopInputError(f"action must be one of: {', '.join(sorted(_ACTIONS))}")
    text = value.strip()
    if text not in _ACTIONS:
        raise DesktopInputError(f"action must be one of: {', '.join(sorted(_ACTIONS))}")
    return text


def _validate_button(value: Any) -> str:
    if value is None:
        text = "left"
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise DesktopInputError(f"button must be one of: {', '.join(sorted(_BUTTONS))}")
    if text not in _BUTTONS:
        raise DesktopInputError(f"button must be one of: {', '.join(sorted(_BUTTONS))}")
    return text


def _validate_key(value: Any) -> str:
    if not isinstance(value, str):
        raise DesktopInputError("key is required")
    text = value.strip()
    if not text:
        raise DesktopInputError("key is required")
    return text


def _validate_keys(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise DesktopInputError("keys must contain at least two key names")
    keys: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise DesktopInputError("keys must contain only strings")
        text = item.strip()
        if not text:
            raise DesktopInputError("keys must contain only non-empty strings")
        keys.append(text)
    if len(keys) < 2:
        raise DesktopInputError("keys must contain at least two key names")
    return keys


def _validate_text(value: Any) -> str:
    if not isinstance(value, str):
        raise DesktopInputError("text is required")
    text = value
    if not text:
        raise DesktopInputError("text is required")
    if len(text) > _MAX_TEXT_CHARS:
        raise DesktopInputError(f"text is too long; max {_MAX_TEXT_CHARS} characters")
    return text


def _parse_point(x_value: Any, y_value: Any, *, prefix: str = "") -> tuple[int, int]:
    return _parse_coordinate(x_value, f"{prefix}x"), _parse_coordinate(y_value, f"{prefix}y")


def _parse_optional_point(x_value: Any, y_value: Any) -> tuple[int | None, int | None]:
    has_x = x_value is not None
    has_y = y_value is not None
    if not has_x and not has_y:
        return None, None
    if has_x != has_y:
        raise DesktopInputError("x and y must be supplied together")
    return _parse_point(x_value, y_value)


def _parse_coordinate(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DesktopInputError(f"{name} must be an integer")
    parsed = value
    if parsed < 0:
        raise DesktopInputError(f"{name} must be non-negative")
    return parsed


def _parse_clicks(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DesktopInputError("clicks must be an integer")
    parsed = value
    if parsed < 1 or parsed > _MAX_CLICKS:
        raise DesktopInputError(f"clicks must be between 1 and {_MAX_CLICKS}")
    return parsed


def _duration_seconds(value: Any, *, default_ms: int = 0) -> float:
    return _bounded_milliseconds(value, name="duration_ms", default_ms=default_ms) / 1000.0


def _interval_seconds(value: Any, *, default_ms: int = 80) -> float:
    return _bounded_milliseconds(value, name="interval_ms", default_ms=default_ms) / 1000.0


def _bounded_milliseconds(value: Any, *, name: str, default_ms: int) -> int:
    if value is None:
        parsed = default_ms
    elif isinstance(value, bool) or not isinstance(value, int):
        raise DesktopInputError(f"{name} must be an integer")
    else:
        parsed = value
    if parsed < 0 or parsed > _MAX_DURATION_MS:
        raise DesktopInputError(f"{name} must be between 0 and {_MAX_DURATION_MS}")
    return parsed


def _result(started_at: float, action: str, **details: Any) -> DesktopInputResult:
    elapsed_ms = int(round((time.perf_counter() - started_at) * 1000))
    return DesktopInputResult(action=action, elapsed_ms=elapsed_ms, details=details)

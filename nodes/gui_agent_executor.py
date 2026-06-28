import time

from nodes.gui_agent_markers import to_point


def execute_gui_action(parsed: dict, dry_run: bool, default_wait_seconds: float) -> dict:
    action_name = str(parsed.get("name") or "").strip().lower()
    if not action_name:
        return {"ok": False, "error": "empty action"}
    if action_name == "finished":
        return {"ok": True, "kind": "finished"}
    if action_name == "wait":
        wait_seconds = max(0.1, float(default_wait_seconds))
        time.sleep(wait_seconds)
        return {"ok": True, "kind": "wait", "wait_seconds": wait_seconds}
    if dry_run:
        return _dry_run_payload(action_name, parsed)

    try:
        import pyautogui  # type: ignore
    except Exception as e:
        return {"ok": False, "error": f"pyautogui unavailable: {str(e)}"}

    try:
        if action_name == "click":
            return _execute_click(pyautogui, parsed, action_name)
        if action_name == "left_double":
            return _execute_left_double(pyautogui, parsed, action_name)
        if action_name == "right_single":
            return _execute_right_single(pyautogui, parsed, action_name)
        if action_name == "drag":
            return _execute_drag(pyautogui, parsed, action_name)
        if action_name == "type":
            content = str(parsed.get("content") or "")
            pyautogui.write(content, interval=0.01)
            return {"ok": True, "kind": action_name, "content_len": len(content)}
        if action_name == "scroll":
            return _execute_scroll(pyautogui, parsed, action_name)
        if action_name == "long_press":
            return _execute_long_press(pyautogui, parsed, action_name)
        if action_name == "press_back":
            pyautogui.press("esc")
            return {"ok": True, "kind": action_name}
        if action_name == "press_home":
            pyautogui.press("home")
            return {"ok": True, "kind": action_name}
        return {"ok": False, "error": f"unsupported action: {action_name}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _dry_run_payload(action_name: str, parsed: dict) -> dict:
    dry_payload = {"ok": True, "dry_run": True, "kind": action_name}
    point = to_point(parsed.get("point"))
    start = to_point(parsed.get("start"))
    end = to_point(parsed.get("end"))
    if point is not None:
        dry_payload["point"] = [point[0], point[1]]
    if start is not None:
        dry_payload["start"] = [start[0], start[1]]
    if end is not None:
        dry_payload["end"] = [end[0], end[1]]
    direction = str(parsed.get("direction") or "").strip().lower()
    if direction:
        dry_payload["direction"] = direction
    return dry_payload


def _execute_click(pyautogui: object, parsed: dict, action_name: str) -> dict:
    x, y = parsed.get("point") or (None, None)
    if x is None or y is None:
        return {"ok": False, "error": "click missing point"}
    pyautogui.click(x=x, y=y)
    return {"ok": True, "kind": action_name, "point": [x, y]}


def _execute_left_double(pyautogui: object, parsed: dict, action_name: str) -> dict:
    x, y = parsed.get("point") or (None, None)
    if x is None or y is None:
        return {"ok": False, "error": "left_double missing point"}
    pyautogui.doubleClick(x=x, y=y)
    return {"ok": True, "kind": action_name, "point": [x, y]}


def _execute_right_single(pyautogui: object, parsed: dict, action_name: str) -> dict:
    x, y = parsed.get("point") or (None, None)
    if x is None or y is None:
        return {"ok": False, "error": "right_single missing point"}
    pyautogui.rightClick(x=x, y=y)
    return {"ok": True, "kind": action_name, "point": [x, y]}


def _execute_drag(pyautogui: object, parsed: dict, action_name: str) -> dict:
    start = parsed.get("start")
    end = parsed.get("end")
    if not start or not end:
        return {"ok": False, "error": "drag missing start/end"}
    pyautogui.moveTo(x=int(start[0]), y=int(start[1]))
    pyautogui.dragTo(x=int(end[0]), y=int(end[1]), duration=0.2, button="left")
    return {"ok": True, "kind": action_name, "start": list(start), "end": list(end)}


def _execute_scroll(pyautogui: object, parsed: dict, action_name: str) -> dict:
    direction = str(parsed.get("direction") or "down").lower()
    point = parsed.get("point")
    if point:
        pyautogui.moveTo(x=int(point[0]), y=int(point[1]))
    amount = 600
    if direction == "up":
        pyautogui.scroll(amount)
    elif direction == "down":
        pyautogui.scroll(-amount)
    elif direction == "right" and hasattr(pyautogui, "hscroll"):
        pyautogui.hscroll(amount)
    elif direction == "left" and hasattr(pyautogui, "hscroll"):
        pyautogui.hscroll(-amount)
    else:
        pyautogui.scroll(-amount)
    payload = {"ok": True, "kind": action_name, "direction": direction}
    point_xy = to_point(point)
    if point_xy is not None:
        payload["point"] = [point_xy[0], point_xy[1]]
    return payload


def _execute_long_press(pyautogui: object, parsed: dict, action_name: str) -> dict:
    x, y = parsed.get("point") or (None, None)
    if x is None or y is None:
        return {"ok": False, "error": "long_press missing point"}
    pyautogui.mouseDown(x=x, y=y, button="left")
    time.sleep(1.0)
    pyautogui.mouseUp(button="left")
    return {"ok": True, "kind": action_name, "point": [x, y]}

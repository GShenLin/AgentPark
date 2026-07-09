import re
from typing import Any


def parse_action(text: str) -> tuple[str, str]:
    content = str(text or "")
    match = re.search(r"^\s*Action\s*:\s*(.+?)\s*$", content, flags=re.IGNORECASE | re.MULTILINE)
    action = str(match.group(1) or "").strip() if match else ""
    action = action.strip().strip("`").rstrip(";")
    thought_match = re.search(r"Thought\s*:\s*(.+?)(?:\n\s*Action\s*:|$)", content, flags=re.IGNORECASE | re.DOTALL)
    thought = str(thought_match.group(1) or "").strip() if thought_match else ""
    return thought, action


def is_supported_action_name(action_name: str, supported_action_names: set[str]) -> bool:
    name = str(action_name or "").strip().lower()
    if not name:
        return False
    return name in supported_action_names


def parse_single_quoted_arg(action: str, key: str) -> str:
    pattern = rf"{re.escape(key)}\s*=\s*'((?:\\.|[^'])*)'"
    match = re.search(pattern, action)
    if not match:
        return ""
    text = str(match.group(1) or "")
    return text.replace("\\n", "\n").replace("\\'", "'").replace('\\"', '"')


def parse_point_tag(action: str, key: str) -> tuple[int, int] | None:
    pattern = rf"{re.escape(key)}\s*=\s*'?\s*<point>\s*(-?\d+)\s+(-?\d+)\s*</point>\s*'?"
    m = re.search(pattern, action, flags=re.IGNORECASE)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def parse_bbox_center(action: str, key: str) -> tuple[int, int] | None:
    pattern = rf"{re.escape(key)}\s*=\s*'?\s*<bbox>\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*</bbox>\s*'?"
    m = re.search(pattern, action, flags=re.IGNORECASE)
    if not m:
        return None
    x1 = int(m.group(1))
    y1 = int(m.group(2))
    x2 = int(m.group(3))
    y2 = int(m.group(4))
    return int(round((x1 + x2) / 2)), int(round((y1 + y2) / 2))


def scale_coord(value: int, max_value: int, scale_value: int = 1000) -> int:
    if max_value <= 1:
        return 0
    scaled = int(round((float(value) / float(scale_value)) * float(max_value - 1)))
    return max(0, min(max_value - 1, scaled))


def parse_action_args(action_text: str, width: int, height: int, coordinate_scale: int = 1000) -> dict:
    out: dict[str, Any] = {}
    action = str(action_text or "")
    fn_match = re.match(r"\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", action)
    action_name = str(fn_match.group(1) or "").strip().lower() if fn_match else action.strip().lower()
    out["name"] = action_name

    def parse_point_any(*keys: str) -> tuple[int, int] | None:
        for key in keys:
            value = parse_point_tag(action, key) or parse_bbox_center(action, key)
            if value is None:
                continue
            x = scale_coord(value[0], width, coordinate_scale)
            y = scale_coord(value[1], height, coordinate_scale)
            return x, y
        return None

    point = parse_point_any("point", "start_point", "start_box")
    if point is not None:
        out["point"] = point

    start = parse_point_any("start_point", "start_box", "point")
    end = parse_point_any("end_point", "end_box")
    if start is not None:
        out["start"] = start
    if end is not None:
        out["end"] = end

    key = parse_single_quoted_arg(action, "key")
    if key:
        out["key"] = key
    content = parse_single_quoted_arg(action, "content")
    if content:
        out["content"] = content
    direction = parse_single_quoted_arg(action, "direction")
    if direction:
        out["direction"] = direction.lower().strip()
    target = parse_single_quoted_arg(action, "target")
    if target:
        out["target"] = target.lower().strip()
    return out


def validate_action_args(parsed: dict) -> str:
    action_name = str((parsed or {}).get("name") or "").strip().lower()
    if not action_name:
        return "empty action"
    if action_name in {"finished", "wait", "press_back", "press_home"}:
        return ""
    if action_name in {"click", "left_double", "right_single", "long_press"}:
        if not parsed.get("point"):
            return f"{action_name} missing point"
        return ""
    if action_name == "drag":
        if not parsed.get("start") or not parsed.get("end"):
            return "drag missing start/end"
        return ""
    if action_name == "type":
        content = str(parsed.get("content") or "")
        if not content:
            return "type missing content"
        return ""
    if action_name == "scroll":
        return ""
    return f"unsupported action: {action_name}"

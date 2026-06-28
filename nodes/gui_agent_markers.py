import hashlib
import os


def image_signature(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 128)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def image_change_ratio(before_path: str, after_path: str) -> float:
    try:
        from PIL import Image, ImageChops  # type: ignore

        with Image.open(before_path) as before_img, Image.open(after_path) as after_img:
            before = before_img.convert("L").resize((320, 180))
            after = after_img.convert("L").resize((320, 180))
            diff = ImageChops.difference(before, after)
            changed = 0
            total = 0
            pixels = diff.get_flattened_data() if hasattr(diff, "get_flattened_data") else diff.getdata()
            for value in pixels:
                total += 1
                if int(value) >= 12:
                    changed += 1
            if total <= 0:
                return -1.0
            return float(changed) / float(total)
    except Exception:
        return -1.0


def draw_click_marker(image_path: str, point: tuple[int, int], save_path: str) -> tuple[bool, str]:
    try:
        from PIL import Image, ImageDraw  # type: ignore

        save_dir = os.path.dirname(save_path)
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
        with Image.open(image_path) as source_img:
            img = source_img.convert("RGB")
            width, height = img.size
            if width <= 0 or height <= 0:
                return False, "invalid image size"

            x = max(0, min(width - 1, int(point[0])))
            y = max(0, min(height - 1, int(point[1])))
            radius = max(8, int(round(min(width, height) * 0.03)))
            stroke = max(2, int(round(radius * 0.18)))

            draw = ImageDraw.Draw(img)
            draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                outline=(255, 0, 0),
                width=stroke,
            )
            center_r = max(2, stroke)
            draw.ellipse(
                (x - center_r, y - center_r, x + center_r, y + center_r),
                fill=(255, 0, 0),
            )
            img.save(save_path)
        return True, ""
    except Exception as e:
        return False, str(e)


def to_point(value: object) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        return int(value[0]), int(value[1])
    except Exception:
        return None


def clamp_point(point: tuple[int, int], width: int, height: int) -> tuple[int, int]:
    x = max(0, min(max(0, width - 1), int(point[0])))
    y = max(0, min(max(0, height - 1), int(point[1])))
    return x, y


def extract_coordinate_marker_meta(
    action_name: str,
    parsed: dict,
    exec_result: dict,
    width: int,
    height: int,
) -> dict:
    name = str(action_name or "").strip().lower()
    if width <= 0 or height <= 0:
        return {}

    if name in {"click", "left_double", "right_single", "long_press"}:
        point = to_point(exec_result.get("point")) or to_point(parsed.get("point"))
        if point is None:
            return {}
        point = clamp_point(point, width, height)
        return {"action": name, "point": [point[0], point[1]]}

    if name == "drag":
        start = to_point(exec_result.get("start")) or to_point(parsed.get("start"))
        end = to_point(exec_result.get("end")) or to_point(parsed.get("end"))
        if start is None or end is None:
            return {}
        start = clamp_point(start, width, height)
        end = clamp_point(end, width, height)
        return {"action": name, "start": [start[0], start[1]], "end": [end[0], end[1]]}

    if name == "scroll":
        direction = str(exec_result.get("direction") or parsed.get("direction") or "down").strip().lower()
        point = to_point(exec_result.get("point")) or to_point(parsed.get("point"))
        if point is None:
            point = (int(width / 2), int(height / 2))
        point = clamp_point(point, width, height)
        return {"action": name, "point": [point[0], point[1]], "direction": direction}

    return {}


def draw_action_marker(
    image_path: str,
    action_name: str,
    parsed: dict,
    exec_result: dict,
    save_path: str,
) -> tuple[bool, str, dict]:
    try:
        from PIL import Image, ImageDraw  # type: ignore

        save_dir = os.path.dirname(save_path)
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
        with Image.open(image_path) as source_img:
            img = source_img.convert("RGB")
            width, height = img.size
            if width <= 0 or height <= 0:
                return False, "invalid image size", {}

            marker_meta = extract_coordinate_marker_meta(
                action_name=action_name,
                parsed=parsed,
                exec_result=exec_result,
                width=width,
                height=height,
            )
            if not marker_meta:
                return False, "no coordinates to mark", {}

            draw = ImageDraw.Draw(img)
            radius = max(8, int(round(min(width, height) * 0.03)))
            stroke = max(2, int(round(radius * 0.18)))
            name = str(action_name or "").strip().lower()

            def draw_point(
                point_xy: tuple[int, int],
                color: tuple[int, int, int],
                label: str = "",
                label_offset: tuple[int, int] = (8, -18),
            ) -> None:
                x, y = clamp_point(point_xy, width, height)
                draw.ellipse(
                    (x - radius, y - radius, x + radius, y + radius),
                    outline=color,
                    width=stroke,
                )
                center_r = max(2, stroke)
                draw.ellipse(
                    (x - center_r, y - center_r, x + center_r, y + center_r),
                    fill=color,
                )
                if label:
                    lx = max(0, min(width - 1, x + int(label_offset[0])))
                    ly = max(0, min(height - 1, y + int(label_offset[1])))
                    draw.text((lx, ly), label, fill=color)

            if name in {"click", "left_double", "right_single", "long_press"}:
                raw_point = marker_meta.get("point")
                if isinstance(raw_point, list) and len(raw_point) == 2:
                    point = (int(raw_point[0]), int(raw_point[1]))
                    label = f"{name}:({point[0]},{point[1]})"
                    draw_point(point_xy=point, color=(255, 0, 0), label=label)

            if name == "drag":
                _draw_drag_marker(draw, draw_point, marker_meta, radius, stroke)

            if name == "scroll":
                _draw_scroll_marker(draw, draw_point, marker_meta, width, height, stroke)

            img.save(save_path)
        return True, "", marker_meta
    except Exception as e:
        return False, str(e), {}


def _draw_drag_marker(draw, draw_point, marker_meta: dict, radius: int, stroke: int) -> None:
    raw_start = marker_meta.get("start")
    raw_end = marker_meta.get("end")
    if not (
        isinstance(raw_start, list)
        and len(raw_start) == 2
        and isinstance(raw_end, list)
        and len(raw_end) == 2
    ):
        return

    start = (int(raw_start[0]), int(raw_start[1]))
    end = (int(raw_end[0]), int(raw_end[1]))
    draw.line((start[0], start[1], end[0], end[1]), fill=(255, 220, 0), width=max(2, stroke))
    dx = float(end[0] - start[0])
    dy = float(end[1] - start[1])
    length = (dx * dx + dy * dy) ** 0.5
    if length > 0.01:
        ux = dx / length
        uy = dy / length
        head_len = max(8, int(round(radius * 0.9)))
        wing = max(4, int(round(head_len * 0.5)))
        p1 = (end[0], end[1])
        p2 = (
            int(end[0] - ux * head_len - uy * wing),
            int(end[1] - uy * head_len + ux * wing),
        )
        p3 = (
            int(end[0] - ux * head_len + uy * wing),
            int(end[1] - uy * head_len - ux * wing),
        )
        draw.polygon((p1, p2, p3), fill=(255, 220, 0))
    draw_point(start, color=(0, 180, 0), label=f"start:({start[0]},{start[1]})")
    draw_point(end, color=(255, 0, 0), label=f"end:({end[0]},{end[1]})")


def _draw_scroll_marker(draw, draw_point, marker_meta: dict, width: int, height: int, stroke: int) -> None:
    raw_point = marker_meta.get("point")
    direction = str(marker_meta.get("direction") or "down").strip().lower()
    if not isinstance(raw_point, list) or len(raw_point) != 2:
        return

    point = (int(raw_point[0]), int(raw_point[1]))
    arrow_len = max(16, int(round(min(width, height) * 0.12)))
    vx = 0
    vy = arrow_len
    if direction == "up":
        vy = -arrow_len
    elif direction == "left":
        vx = -arrow_len
        vy = 0
    elif direction == "right":
        vx = arrow_len
        vy = 0
    end = clamp_point((point[0] + vx, point[1] + vy), width, height)
    draw.line((point[0], point[1], end[0], end[1]), fill=(0, 180, 255), width=max(2, stroke))
    draw_point(point, color=(0, 180, 255), label=f"scroll-{direction}:({point[0]},{point[1]})")
    draw_point(end, color=(0, 180, 255))

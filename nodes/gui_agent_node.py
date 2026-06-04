import base64
import hashlib
import json
import os
import queue
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from typing import Any

from nodes.base_node import BaseNode
from src.message_protocol import build_resource_part, normalize_envelope
from src.providers import create_agent


class Node(BaseNode):
    name = "GUI Agent"
    description = "Single-node GUI loop: capture, plan, execute, verify"
    gui_mode = "GUIAgent"
    supported_action_names = {
        "click",
        "left_double",
        "right_single",
        "drag",
        "type",
        "scroll",
        "wait",
        "finished",
        "long_press",
        "press_back",
        "press_home",
    }
    input_capabilities = ["text", "resource:image", "resource:url"]
    output_capabilities = ["text", "resource:image", "structured", "meta"]
    coordinate_scale = 1000
    min_screen_change_ratio = 0.0015
    default_wait_seconds = 2.0
    config_defaults = {
        "provider_id": "",
        "mode": gui_mode,
        "verify_mode": gui_mode,
        "instruction": "",
        "system_prompt": (
            "You are a GUI planning agent. Analyze the screenshot and output exactly:\n"
            "Thought: <short analysis>\n"
            "Action: <one action>\n"
            "Coordinates must use normalized 0-1000 values relative to screenshot width/height.\n"
            "Allowed actions: click, left_double, right_single, drag, type, scroll, wait, finished, long_press."
        ),
        "verify_prompt": (
            "Check if the GUI task is complete based on screenshot.\n"
            "Respond JSON only: {\"done\": true|false, \"reason\": \"...\"}."
        ),
        "verify_on_finish": "true",
        "dry_run": "false",
        "capture_region": "{}",
        "mock_actions": "[]",
        "planner_timeout_seconds": "120",
        "verify_timeout_seconds": "60",
    }
    config_schema = {
        "provider_id": {"type": "text", "label": "provider_id"},
        "instruction": {"type": "text", "label": "instruction (fallback if input empty)"},
        "system_prompt": {"type": "text", "label": "planner system_prompt"},
        "verify_prompt": {"type": "text", "label": "verify prompt"},
        "verify_on_finish": {"type": "text", "label": "verify on finished(true/false)"},
        "dry_run": {"type": "text", "label": "dry run(true/false)"},
        "capture_region": {"type": "json", "label": "capture region json"},
        "mock_actions": {"type": "json", "label": "mock actions array for offline test"},
        "planner_timeout_seconds": {"type": "text", "label": "planner timeout seconds"},
        "verify_timeout_seconds": {"type": "text", "label": "verify timeout seconds"},
    }

    def on_create(self, config: dict, context: dict | None = None) -> None:
        super().on_create(config, context)
        if not isinstance(config, dict):
            return
        if "max_steps" in config:
            config.pop("max_steps", None)
        if "no_change_limit" in config:
            config.pop("no_change_limit", None)
        if "verifier_provider_id" in config:
            config.pop("verifier_provider_id", None)
        if "wait_seconds" in config:
            config.pop("wait_seconds", None)
        if "step_delay_seconds" in config:
            config.pop("step_delay_seconds", None)
        if "auto_scale_coords" in config:
            config.pop("auto_scale_coords", None)

    @staticmethod
    def _to_bool(value: object, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        if not text:
            return default
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
        return default

    @staticmethod
    def _to_int(value: object, default: int) -> int:
        try:
            return int(float(value))
        except Exception:
            return default

    @staticmethod
    def _to_float(value: object, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _parse_json(value: object, fallback: Any) -> Any:
        if isinstance(value, (dict, list)):
            return value
        text = str(value or "").strip()
        if not text:
            return fallback
        try:
            return json.loads(text)
        except Exception:
            return fallback

    def _node_dir(self, context: dict) -> str:
        memory_path = self._resolve_memory_path(context)
        if memory_path:
            return os.path.dirname(memory_path)
        graph_id = self._sanitize_graph_id(context.get("graph_id"))
        node_id = self._sanitize_node_id(context.get("node_instance_id") or context.get("node_id") or "gui_agent")
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "memories", graph_id, node_id)

    def _run_dir(self, context: dict) -> str:
        node_dir = self._node_dir(context)
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        path = os.path.join(node_dir, "gui_runs", run_id)
        os.makedirs(path, exist_ok=True)
        return path

    def _extract_instruction(self, message: dict, context: dict) -> str:
        input_text = self._message_text(message).strip()
        fallback_text = str(context.get("instruction") or "").strip()
        return input_text or fallback_text

    def _extract_image_fallbacks(self, message: dict) -> list[str]:
        output: list[str] = []
        parts = message.get("parts") if isinstance(message, dict) else None
        if not isinstance(parts, list):
            return output
        for part in parts:
            if not isinstance(part, dict):
                continue
            if str(part.get("type") or "").strip().lower() != "resource":
                continue
            res = part.get("resource")
            if not isinstance(res, dict):
                continue
            kind = str(res.get("kind") or "").strip().lower()
            uri = str(res.get("uri") or "").strip()
            if not uri:
                continue
            if kind and kind != "image":
                continue
            raw = uri[7:] if uri.startswith("file://") else uri
            if os.path.isfile(raw):
                output.append(raw)
        return output

    @staticmethod
    def _encode_image_data_url(path: str) -> str:
        ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
        if ext == "jpg":
            ext = "jpeg"
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/{ext};base64,{encoded}"

    @staticmethod
    def _image_signature(path: str) -> str:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024 * 128)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _image_change_ratio(before_path: str, after_path: str) -> float:
        try:
            from PIL import Image, ImageChops  # type: ignore

            with Image.open(before_path) as before_img, Image.open(after_path) as after_img:
                before = before_img.convert("L").resize((320, 180))
                after = after_img.convert("L").resize((320, 180))
                diff = ImageChops.difference(before, after)
                changed = 0
                total = 0
                for value in diff.getdata():
                    total += 1
                    if int(value) >= 12:
                        changed += 1
                if total <= 0:
                    return -1.0
                return float(changed) / float(total)
        except Exception:
            return -1.0

    @staticmethod
    def _draw_click_marker(image_path: str, point: tuple[int, int], save_path: str) -> tuple[bool, str]:
        try:
            from PIL import Image, ImageDraw  # type: ignore

            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with Image.open(image_path) as img:
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

    @staticmethod
    def _to_point(value: object) -> tuple[int, int] | None:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        try:
            return int(value[0]), int(value[1])
        except Exception:
            return None

    @staticmethod
    def _clamp_point(point: tuple[int, int], width: int, height: int) -> tuple[int, int]:
        x = max(0, min(max(0, width - 1), int(point[0])))
        y = max(0, min(max(0, height - 1), int(point[1])))
        return x, y

    def _extract_coordinate_marker_meta(
        self,
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
            point = self._to_point(exec_result.get("point")) or self._to_point(parsed.get("point"))
            if point is None:
                return {}
            point = self._clamp_point(point, width, height)
            return {"action": name, "point": [point[0], point[1]]}

        if name == "drag":
            start = self._to_point(exec_result.get("start")) or self._to_point(parsed.get("start"))
            end = self._to_point(exec_result.get("end")) or self._to_point(parsed.get("end"))
            if start is None or end is None:
                return {}
            start = self._clamp_point(start, width, height)
            end = self._clamp_point(end, width, height)
            return {"action": name, "start": [start[0], start[1]], "end": [end[0], end[1]]}

        if name == "scroll":
            direction = str(exec_result.get("direction") or parsed.get("direction") or "down").strip().lower()
            point = self._to_point(exec_result.get("point")) or self._to_point(parsed.get("point"))
            if point is None:
                point = (int(width / 2), int(height / 2))
            point = self._clamp_point(point, width, height)
            return {"action": name, "point": [point[0], point[1]], "direction": direction}

        return {}

    def _draw_action_marker(
        self,
        image_path: str,
        action_name: str,
        parsed: dict,
        exec_result: dict,
        save_path: str,
    ) -> tuple[bool, str, dict]:
        try:
            from PIL import Image, ImageDraw  # type: ignore

            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with Image.open(image_path) as img:
                width, height = img.size
                if width <= 0 or height <= 0:
                    return False, "invalid image size", {}

                marker_meta = self._extract_coordinate_marker_meta(
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
                    x, y = self._clamp_point(point_xy, width, height)
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
                    raw_start = marker_meta.get("start")
                    raw_end = marker_meta.get("end")
                    if (
                        isinstance(raw_start, list)
                        and len(raw_start) == 2
                        and isinstance(raw_end, list)
                        and len(raw_end) == 2
                    ):
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

                if name == "scroll":
                    raw_point = marker_meta.get("point")
                    direction = str(marker_meta.get("direction") or "down").strip().lower()
                    if isinstance(raw_point, list) and len(raw_point) == 2:
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
                        end = self._clamp_point((point[0] + vx, point[1] + vy), width, height)
                        draw.line((point[0], point[1], end[0], end[1]), fill=(0, 180, 255), width=max(2, stroke))
                        draw_point(point, color=(0, 180, 255), label=f"scroll-{direction}:({point[0]},{point[1]})")
                        draw_point(end, color=(0, 180, 255))

                img.save(save_path)
            return True, "", marker_meta
        except Exception as e:
            return False, str(e), {}

    @staticmethod
    def _append_run_log(run_dir: str, payload: dict) -> None:
        if not run_dir:
            return
        try:
            os.makedirs(run_dir, exist_ok=True)
            log_path = os.path.join(run_dir, "execution.jsonl")
            record = {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                **(payload if isinstance(payload, dict) else {"payload": str(payload)}),
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            return

    def _parse_capture_region(self, value: object) -> dict | None:
        region = self._parse_json(value, {})
        if not isinstance(region, dict) or not region:
            return None
        keys = ["left", "top", "width", "height"]
        out: dict[str, int] = {}
        for key in keys:
            if key not in region:
                return None
            try:
                num = int(float(region.get(key)))
            except Exception:
                return None
            if num < 0 and key in {"left", "top"}:
                num = 0
            if num <= 0 and key in {"width", "height"}:
                return None
            out[key] = num
        return out

    def _capture_screenshot(
        self,
        save_path: str,
        capture_region: dict | None,
        fallback_images: list[str],
        fallback_index: int,
    ) -> tuple[dict, int]:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        region_tuple = None
        if isinstance(capture_region, dict):
            region_tuple = (
                int(capture_region["left"]),
                int(capture_region["top"]),
                int(capture_region["width"]),
                int(capture_region["height"]),
            )

        capture_error = ""
        try:
            import pyautogui  # type: ignore

            image = pyautogui.screenshot(region=region_tuple)
            image.save(save_path)
            width, height = image.size
            return {
                "ok": True,
                "path": save_path,
                "width": int(width),
                "height": int(height),
                "source": "screen",
            }, fallback_index
        except Exception as e:
            capture_error = str(e)

        if fallback_images and fallback_index < len(fallback_images):
            src = fallback_images[fallback_index]
            fallback_index += 1
            try:
                shutil.copyfile(src, save_path)
                width = 1920
                height = 1080
                try:
                    from PIL import Image  # type: ignore

                    with Image.open(save_path) as img:
                        width, height = img.size
                except Exception:
                    pass
                return {
                    "ok": True,
                    "path": save_path,
                    "width": int(width),
                    "height": int(height),
                    "source": "fallback",
                }, fallback_index
            except Exception as e:
                capture_error = f"{capture_error}; fallback_failed={str(e)}" if capture_error else str(e)

        return {"ok": False, "error": capture_error or "capture failed"}, fallback_index

    def _parse_action(self, text: str) -> tuple[str, str]:
        content = str(text or "")
        match = re.search(r"^\s*Action\s*:\s*(.+?)\s*$", content, flags=re.IGNORECASE | re.MULTILINE)
        action = str(match.group(1) or "").strip() if match else ""
        action = action.strip().strip("`").rstrip(";")
        thought_match = re.search(r"Thought\s*:\s*(.+?)(?:\n\s*Action\s*:|$)", content, flags=re.IGNORECASE | re.DOTALL)
        thought = str(thought_match.group(1) or "").strip() if thought_match else ""
        return thought, action

    def _is_supported_action_name(self, action_name: str) -> bool:
        name = str(action_name or "").strip().lower()
        if not name:
            return False
        return name in self.supported_action_names

    @staticmethod
    def _parse_single_quoted_arg(action: str, key: str) -> str:
        pattern = rf"{re.escape(key)}\s*=\s*'((?:\\.|[^'])*)'"
        match = re.search(pattern, action)
        if not match:
            return ""
        text = str(match.group(1) or "")
        return text.replace("\\n", "\n").replace("\\'", "'").replace('\\"', '"')

    @staticmethod
    def _parse_point_tag(action: str, key: str) -> tuple[int, int] | None:
        pattern = rf"{re.escape(key)}\s*=\s*'?\s*<point>\s*(-?\d+)\s+(-?\d+)\s*</point>\s*'?"
        m = re.search(pattern, action, flags=re.IGNORECASE)
        if not m:
            return None
        return int(m.group(1)), int(m.group(2))

    @staticmethod
    def _parse_bbox_center(action: str, key: str) -> tuple[int, int] | None:
        pattern = rf"{re.escape(key)}\s*=\s*'?\s*<bbox>\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*</bbox>\s*'?"
        m = re.search(pattern, action, flags=re.IGNORECASE)
        if not m:
            return None
        x1 = int(m.group(1))
        y1 = int(m.group(2))
        x2 = int(m.group(3))
        y2 = int(m.group(4))
        return int(round((x1 + x2) / 2)), int(round((y1 + y2) / 2))

    @staticmethod
    def _scale_coord(value: int, max_value: int, scale_value: int = 1000) -> int:
        if max_value <= 1:
            return 0
        scaled = int(round((float(value) / float(scale_value)) * float(max_value - 1)))
        return max(0, min(max_value - 1, scaled))

    def _parse_action_args(self, action_text: str, width: int, height: int) -> dict:
        out: dict[str, Any] = {}
        action = str(action_text or "")
        fn_match = re.match(r"\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", action)
        action_name = str(fn_match.group(1) or "").strip().lower() if fn_match else action.strip().lower()
        out["name"] = action_name

        def parse_point_any(*keys: str) -> tuple[int, int] | None:
            for key in keys:
                value = self._parse_point_tag(action, key) or self._parse_bbox_center(action, key)
                if value is None:
                    continue
                x = self._scale_coord(value[0], width, self.coordinate_scale)
                y = self._scale_coord(value[1], height, self.coordinate_scale)
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

        key = self._parse_single_quoted_arg(action, "key")
        if key:
            out["key"] = key
        content = self._parse_single_quoted_arg(action, "content")
        if content:
            out["content"] = content
        text_value = self._parse_single_quoted_arg(action, "text")
        if text_value and "content" not in out:
            out["content"] = text_value
        direction = self._parse_single_quoted_arg(action, "direction")
        if direction:
            out["direction"] = direction.lower().strip()
        target = self._parse_single_quoted_arg(action, "target")
        if target:
            out["target"] = target.lower().strip()
        return out

    def _validate_action_args(self, parsed: dict) -> str:
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

    def _repair_unsupported_action(
        self,
        planner_agent: object,
        instruction: str,
        step_index: int,
        screenshot_path: str,
        history: list[dict],
        bad_response: str,
        bad_action_text: str,
        bad_action_name: str,
        mode: str,
        execution_error: str = "",
    ) -> str:
        short_history = history[-6:]
        history_lines = []
        for item in short_history:
            idx = int(item.get("step") or 0)
            action_text = str(item.get("action") or "")
            result_text = str(item.get("result") or "")
            history_lines.append(f"{idx}. action={action_text}; result={result_text}")
        history_text = "\n".join(history_lines) if history_lines else "(none)"
        action_hint = (
            "Allowed Action forms:\n"
            "Action: click(point='<point>x y</point>')\n"
            "Action: left_double(point='<point>x y</point>')\n"
            "Action: right_single(point='<point>x y</point>')\n"
            "Action: drag(start_point='<point>x1 y1</point>', end_point='<point>x2 y2</point>')\n"
            "Action: type(content='text')\n"
            "Action: scroll(direction='down', point='<point>x y</point>')\n"
            "Action: long_press(point='<point>x y</point>')\n"
            "Action: wait\n"
            "Action: finished(content='done')\n"
            "Action: press_back\n"
            "Action: press_home\n"
            "Coordinates must be normalized 0-1000 values relative to screenshot width/height."
        )
        execution_error_line = f"Execution error: {execution_error}\n" if execution_error else ""
        prompt = (
            f"Task: {instruction}\n"
            f"Step: {step_index}\n"
            f"Recent history:\n{history_text}\n"
            "Your previous answer is not executable by the GUI executor.\n"
            f"Previous planner response:\n{bad_response}\n"
            f"Parsed action text: {bad_action_text}\n"
            f"Parsed action name: {bad_action_name}\n"
            f"{execution_error_line}"
            f"{action_hint}\n"
            "Rules:\n"
            "- Return exactly two lines.\n"
            "- First line starts with 'Thought:'.\n"
            "- Second line starts with 'Action:'.\n"
            "- Use only one action in function-call style.\n"
            "- Do not return JSON.\n"
            "- If latest result has screen_changed=false, treat it as ineffective and choose a different target/action.\n"
            "- Do not output natural language instructions.\n"
            "- The action name must be one of: click, left_double, right_single, drag, type, scroll, wait, finished, long_press, press_back, press_home."
        )
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": self._encode_image_data_url(screenshot_path)}},
        ]
        planner_agent.Message("user", content, persist=False)
        response = planner_agent.Send(run_tools=False, mode=mode)
        return "" if response is None else str(response)

    def _execute_action(self, parsed: dict, dry_run: bool) -> dict:
        action_name = str(parsed.get("name") or "").strip().lower()
        if not action_name:
            return {"ok": False, "error": "empty action"}
        if action_name == "finished":
            return {"ok": True, "kind": "finished"}
        if action_name == "wait":
            wait_seconds = max(0.1, float(self.default_wait_seconds))
            time.sleep(wait_seconds)
            return {"ok": True, "kind": "wait", "wait_seconds": wait_seconds}
        if dry_run:
            dry_payload = {"ok": True, "dry_run": True, "kind": action_name}
            point = self._to_point(parsed.get("point"))
            start = self._to_point(parsed.get("start"))
            end = self._to_point(parsed.get("end"))
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

        try:
            import pyautogui  # type: ignore
        except Exception as e:
            return {"ok": False, "error": f"pyautogui unavailable: {str(e)}"}

        try:
            if action_name == "click":
                x, y = parsed.get("point") or (None, None)
                if x is None or y is None:
                    return {"ok": False, "error": "click missing point"}
                pyautogui.click(x=x, y=y)
                return {"ok": True, "kind": action_name, "point": [x, y]}
            if action_name == "left_double":
                x, y = parsed.get("point") or (None, None)
                if x is None or y is None:
                    return {"ok": False, "error": "left_double missing point"}
                pyautogui.doubleClick(x=x, y=y)
                return {"ok": True, "kind": action_name, "point": [x, y]}
            if action_name == "right_single":
                x, y = parsed.get("point") or (None, None)
                if x is None or y is None:
                    return {"ok": False, "error": "right_single missing point"}
                pyautogui.rightClick(x=x, y=y)
                return {"ok": True, "kind": action_name, "point": [x, y]}
            if action_name == "drag":
                start = parsed.get("start")
                end = parsed.get("end")
                if not start or not end:
                    return {"ok": False, "error": "drag missing start/end"}
                pyautogui.moveTo(x=int(start[0]), y=int(start[1]))
                pyautogui.dragTo(x=int(end[0]), y=int(end[1]), duration=0.2, button="left")
                return {"ok": True, "kind": action_name, "start": list(start), "end": list(end)}
            if action_name == "type":
                content = str(parsed.get("content") or "")
                pyautogui.write(content, interval=0.01)
                return {"ok": True, "kind": action_name, "content_len": len(content)}
            if action_name == "scroll":
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
                point_xy = self._to_point(point)
                if point_xy is not None:
                    payload["point"] = [point_xy[0], point_xy[1]]
                return payload
            if action_name == "long_press":
                x, y = parsed.get("point") or (None, None)
                if x is None or y is None:
                    return {"ok": False, "error": "long_press missing point"}
                pyautogui.mouseDown(x=x, y=y, button="left")
                time.sleep(1.0)
                pyautogui.mouseUp(button="left")
                return {"ok": True, "kind": action_name, "point": [x, y]}
            if action_name == "press_back":
                pyautogui.press("esc")
                return {"ok": True, "kind": action_name}
            if action_name == "press_home":
                pyautogui.press("home")
                return {"ok": True, "kind": action_name}
            return {"ok": False, "error": f"unsupported action: {action_name}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _call_planner(
        self,
        planner_agent: object,
        instruction: str,
        step_index: int,
        screenshot_path: str,
        planner_feedback_path: str,
        history: list[dict],
        mode: str,
    ) -> str:
        short_history = history[-6:]
        history_lines = []
        for item in short_history:
            idx = int(item.get("step") or 0)
            action_text = str(item.get("action") or "")
            result_text = str(item.get("result") or "")
            history_lines.append(f"{idx}. action={action_text}; result={result_text}")
        history_text = "\n".join(history_lines) if history_lines else "(none)"
        action_hint = (
            "Allowed Action forms:\n"
            "Action: click(point='<point>x y</point>')\n"
            "Action: left_double(point='<point>x y</point>')\n"
            "Action: right_single(point='<point>x y</point>')\n"
            "Action: drag(start_point='<point>x1 y1</point>', end_point='<point>x2 y2</point>')\n"
            "Action: type(content='text')\n"
            "Action: scroll(direction='down', point='<point>x y</point>')\n"
            "Action: long_press(point='<point>x y</point>')\n"
            "Action: wait\n"
            "Action: finished(content='done')\n"
            "Action: press_back\n"
            "Action: press_home\n"
            "Coordinates must be normalized 0-1000 values relative to screenshot width/height."
        )
        prompt = (
            f"Task: {instruction}\n"
            f"Step: {step_index}\n"
            f"Recent history:\n{history_text}\n"
            f"{action_hint}\n"
            "Rules:\n"
            "- Return exactly two lines.\n"
            "- First line starts with 'Thought:'.\n"
            "- Second line starts with 'Action:'.\n"
            "- Use only one action in function-call style.\n"
            "- Do not return JSON.\n"
            "- If latest result has screen_changed=false, treat it as ineffective and choose a different target/action."
        )
        content = [{"type": "text", "text": prompt}]
        if screenshot_path and os.path.isfile(screenshot_path):
            content.append({"type": "image_url", "image_url": {"url": self._encode_image_data_url(screenshot_path)}})
        if (
            planner_feedback_path
            and planner_feedback_path != screenshot_path
            and os.path.isfile(planner_feedback_path)
        ):
            content.append(
                {
                    "type": "text",
                    "text": (
                        "Previous action feedback image with exact executed coordinate markers. "
                        "Use it to correct coordinate offset in the next action."
                    ),
                }
            )
            content.append(
                {"type": "image_url", "image_url": {"url": self._encode_image_data_url(planner_feedback_path)}}
            )
        planner_agent.Message("user", content, persist=False)
        response = planner_agent.Send(run_tools=False, mode=mode)
        return "" if response is None else str(response)

    def _verify_finished(
        self,
        verifier_agent: object | None,
        verify_prompt: str,
        instruction: str,
        screenshot_path: str,
        planner_response: str,
        mode: str,
    ) -> tuple[bool, str]:
        if verifier_agent is None:
            return True, "verify skipped (no verifier)"
        prompt = (
            f"{verify_prompt}\n"
            f"Task: {instruction}\n"
            f"Planner output:\n{planner_response}\n"
            "JSON only."
        )
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": self._encode_image_data_url(screenshot_path)}},
        ]
        verifier_agent.Message("user", content, persist=False)
        response = verifier_agent.Send(run_tools=False, mode=mode)
        text = "" if response is None else str(response)
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            try:
                payload = json.loads(json_match.group(0))
                if isinstance(payload, dict):
                    if "done" in payload:
                        done = self._to_bool(payload.get("done"), default=False)
                        reason = str(payload.get("reason") or payload.get("content") or "").strip()
                        return done, reason
                    name_text = str(payload.get("name") or "").strip().lower()
                    if name_text == "finished":
                        params = payload.get("parameters")
                        if isinstance(params, dict):
                            reason = str(params.get("content") or payload.get("reason") or "").strip()
                        else:
                            reason = str(payload.get("content") or payload.get("reason") or "").strip()
                        return True, reason[:160]
                    action_text = str(payload.get("action") or "").strip().lower()
                    if action_text == "finished":
                        reason = str(payload.get("reason") or payload.get("content") or "").strip()
                        return True, reason[:160]
                    content_text = str(payload.get("content") or "").strip()
                    content_key = content_text.lower()
                    if content_key in {"done", "completed", "finished", "success", "ok", "完成"}:
                        reason = str(payload.get("reason") or content_text).strip()
                        return True, reason[:160]
            except Exception:
                pass
        return False, text[:160]

    def _mock_plan(self, mock_actions: list, step_index: int) -> str:
        if step_index - 1 < 0 or step_index - 1 >= len(mock_actions):
            return "Thought: mock_actions exhausted\nAction: finished(content='mock_actions exhausted')"
        item = mock_actions[step_index - 1]
        if isinstance(item, str):
            action_text = item.strip()
            if action_text.lower().startswith("action:"):
                return f"Thought: mock\n{action_text}"
            return f"Thought: mock\nAction: {action_text}"
        if isinstance(item, dict):
            thought = str(item.get("thought") or "mock")
            action = str(item.get("action") or "")
            if not action:
                action = "finished(content='mock empty action')"
            return f"Thought: {thought}\nAction: {action}"
        return "Thought: mock invalid item\nAction: finished(content='mock invalid item')"

    def _run_with_timeout(self, fn, timeout_seconds: float):
        timeout = self._to_float(timeout_seconds, default=0.0)
        if timeout <= 0:
            return fn()

        result_queue: queue.Queue = queue.Queue(maxsize=1)

        def _target():
            try:
                result_queue.put(("ok", fn()))
            except Exception as e:
                result_queue.put(("error", e))

        worker = threading.Thread(target=_target, daemon=True, name="gui-agent-call")
        worker.start()
        worker.join(timeout=timeout)
        if worker.is_alive():
            raise TimeoutError(f"call timeout after {timeout:.1f}s")
        if result_queue.empty():
            raise RuntimeError("call finished without result")
        state, payload = result_queue.get()
        if state == "error":
            if isinstance(payload, Exception):
                raise payload
            raise RuntimeError(str(payload))
        return payload

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        envelope = normalize_envelope(message, default_role="user")

        provider_id = str(ctx.get("provider_id") or "").strip()
        planner_mode = self.gui_mode
        verify_mode = self.gui_mode
        instruction = self._extract_instruction(envelope, ctx)
        system_prompt = str(ctx.get("system_prompt") or "").strip()
        verify_prompt = str(ctx.get("verify_prompt") or "").strip()
        verify_on_finish = self._to_bool(ctx.get("verify_on_finish"), default=True)
        dry_run = self._to_bool(ctx.get("dry_run"), default=False)
        planner_timeout_seconds = self._to_float(ctx.get("planner_timeout_seconds"), default=120.0)
        verify_timeout_seconds = self._to_float(ctx.get("verify_timeout_seconds"), default=60.0)
        capture_region = self._parse_capture_region(ctx.get("capture_region"))
        mock_actions = self._parse_json(ctx.get("mock_actions"), [])
        if not isinstance(mock_actions, list):
            mock_actions = []

        if not instruction:
            instruction = "Analyze current GUI and continue."

        run_dir = self._run_dir(ctx)
        self._append_run_log(
            run_dir,
            {
                "event": "run_started",
                "instruction": instruction,
                "provider_id": provider_id,
                "planner_mode": planner_mode,
                "verify_mode": verify_mode,
                "dry_run": dry_run,
                "verify_on_finish": verify_on_finish,
            },
        )
        fallback_images = self._extract_image_fallbacks(envelope)
        fallback_index = 0
        step_logs: list[dict] = []
        screenshot_paths: list[str] = []

        def _append_step_record(record: dict) -> None:
            step_logs.append(record)
            self._append_run_log(
                run_dir,
                {
                    "event": "step",
                    "step": int(record.get("step") or 0),
                    "status": str(record.get("status") or ""),
                    "action_name": str(record.get("action_name") or ""),
                    "action": str(record.get("action") or ""),
                    "execute": record.get("execute"),
                    "observation": record.get("observation"),
                    "error": record.get("error"),
                    "screenshot_before": record.get("screenshot_before") or record.get("screenshot"),
                    "screenshot_after": record.get("screenshot_after"),
                    "screenshot_after_raw": record.get("screenshot_after_raw"),
                    "screenshot_after_marked": record.get("screenshot_after_marked"),
                },
            )

        planner_agent = None
        if not mock_actions:
            if not provider_id:
                raise ValueError("provider_id is required when mock_actions is empty")
            planner_agent = create_agent(
                provider_id,
                memory_file_path=os.path.join(run_dir, "planner.md"),
                system_prompt=system_prompt if system_prompt else None,
            )

        finished = False
        final_reason = ""
        history: list[dict] = []
        step_index = 1
        planner_feedback_path = ""

        while True:
            before_path = os.path.join(run_dir, f"step_{step_index:02d}_before.png")
            capture_info, fallback_index = self._capture_screenshot(
                before_path,
                capture_region,
                fallback_images,
                fallback_index,
            )
            if not self._to_bool(capture_info.get("ok"), default=False):
                final_reason = f"capture_failed: {capture_info.get('error')}"
                _append_step_record(
                    {
                        "step": step_index,
                        "status": "capture_failed",
                        "error": str(capture_info.get("error") or ""),
                    }
                )
                break

            width = int(capture_info.get("width") or 0)
            height = int(capture_info.get("height") or 0)
            screenshot_paths.append(before_path)

            if mock_actions:
                planner_response = self._mock_plan(mock_actions, step_index)
            else:
                try:
                    if planner_agent is None:
                        raise RuntimeError("planner agent not initialized")
                    planner_response = self._run_with_timeout(
                        lambda: self._call_planner(
                            planner_agent=planner_agent,
                            instruction=instruction,
                            step_index=step_index,
                            screenshot_path=before_path,
                            planner_feedback_path=planner_feedback_path,
                            history=history,
                            mode=planner_mode,
                        ),
                        timeout_seconds=planner_timeout_seconds,
                    )
                except Exception as e:
                    final_reason = f"planner_failed: {str(e)}"
                    _append_step_record(
                        {
                            "step": step_index,
                            "status": "planner_failed",
                            "error": str(e),
                            "screenshot": before_path,
                        }
                    )
                    break

            raw_planner_response = planner_response
            repair_record: dict | None = None
            thought, action_text = self._parse_action(planner_response)
            if not action_text:
                repaired_applied = False
                if planner_agent is not None and not mock_actions:
                    try:
                        repaired_response = self._repair_unsupported_action(
                            planner_agent=planner_agent,
                            instruction=instruction,
                            step_index=step_index,
                            screenshot_path=before_path,
                            history=history,
                            bad_response=raw_planner_response,
                            bad_action_text="",
                            bad_action_name="",
                            execution_error="missing Action line",
                            mode=planner_mode,
                        )
                        repaired_thought, repaired_action_text = self._parse_action(repaired_response)
                        if repaired_action_text:
                            thought = repaired_thought or thought
                            action_text = repaired_action_text
                            planner_response = repaired_response
                            repaired_applied = True
                        repair_record = {
                            "triggered": True,
                            "bad_action_text": "",
                            "bad_action_name": "",
                            "repair_response": repaired_response,
                            "repair_action": repaired_action_text,
                            "repair_action_name": "",
                            "applied": repaired_applied,
                        }
                    except Exception as e:
                        repair_record = {
                            "triggered": True,
                            "bad_action_text": "",
                            "bad_action_name": "",
                            "applied": False,
                            "error": str(e),
                        }
                if not action_text:
                    final_reason = "planner_no_action"
                    _append_step_record(
                        {
                            "step": step_index,
                            "status": "planner_no_action",
                            "planner_response": planner_response,
                            "planner_response_raw": raw_planner_response,
                            "screenshot": before_path,
                            **({"repair": repair_record} if isinstance(repair_record, dict) else {}),
                        }
                    )
                    break

            parsed = self._parse_action_args(action_text, width, height)
            action_name = str(parsed.get("name") or "").strip().lower()
            if (not self._is_supported_action_name(action_name)) and (planner_agent is not None) and (not mock_actions):
                try:
                    repaired_response = self._repair_unsupported_action(
                        planner_agent=planner_agent,
                        instruction=instruction,
                        step_index=step_index,
                        screenshot_path=before_path,
                        history=history,
                        bad_response=raw_planner_response,
                        bad_action_text=action_text,
                        bad_action_name=action_name,
                        execution_error="unsupported action name",
                        mode=planner_mode,
                    )
                    repaired_thought, repaired_action_text = self._parse_action(repaired_response)
                    repaired_parsed = self._parse_action_args(
                        repaired_action_text,
                        width,
                        height
                    )
                    repaired_action_name = str(repaired_parsed.get("name") or "").strip().lower()
                    repair_record = {
                        "triggered": True,
                        "bad_action_text": action_text,
                        "bad_action_name": action_name,
                        "repair_response": repaired_response,
                        "repair_action": repaired_action_text,
                        "repair_action_name": repaired_action_name,
                        "applied": False,
                    }
                    if repaired_action_text and self._is_supported_action_name(repaired_action_name):
                        thought = repaired_thought or thought
                        action_text = repaired_action_text
                        parsed = repaired_parsed
                        action_name = repaired_action_name
                        planner_response = repaired_response
                        repair_record["applied"] = True
                except Exception as e:
                    repair_record = {
                        "triggered": True,
                        "bad_action_text": action_text,
                        "bad_action_name": action_name,
                        "applied": False,
                        "error": str(e),
                    }

            validation_error = self._validate_action_args(parsed)
            if validation_error and (planner_agent is not None) and (not mock_actions):
                try:
                    repaired_response = self._repair_unsupported_action(
                        planner_agent=planner_agent,
                        instruction=instruction,
                        step_index=step_index,
                        screenshot_path=before_path,
                        history=history,
                        bad_response=planner_response,
                        bad_action_text=action_text,
                        bad_action_name=action_name,
                        execution_error=validation_error,
                        mode=planner_mode,
                    )
                    repaired_thought, repaired_action_text = self._parse_action(repaired_response)
                    repaired_parsed = self._parse_action_args(
                        repaired_action_text,
                        width,
                        height
                    )
                    repaired_action_name = str(repaired_parsed.get("name") or "").strip().lower()
                    repaired_validation_error = self._validate_action_args(repaired_parsed)
                    if repair_record is None:
                        repair_record = {}
                    repair_record["validation_error"] = validation_error
                    repair_record["validation_repair_response"] = repaired_response
                    repair_record["validation_repair_action"] = repaired_action_text
                    repair_record["validation_repair_action_name"] = repaired_action_name
                    repair_record["validation_repair_applied"] = False
                    repair_record["validation_repair_error"] = repaired_validation_error
                    if (
                        repaired_action_text
                        and self._is_supported_action_name(repaired_action_name)
                        and not repaired_validation_error
                    ):
                        thought = repaired_thought or thought
                        action_text = repaired_action_text
                        parsed = repaired_parsed
                        action_name = repaired_action_name
                        planner_response = repaired_response
                        validation_error = ""
                        repair_record["validation_repair_applied"] = True
                except Exception as e:
                    if repair_record is None:
                        repair_record = {}
                    repair_record["validation_error"] = validation_error
                    repair_record["validation_repair_applied"] = False
                    repair_record["validation_repair_exception"] = str(e)

            if validation_error:
                final_reason = f"invalid_action: {validation_error}"
                _append_step_record(
                    {
                        "step": step_index,
                        "status": "invalid_action",
                        "thought": thought,
                        "action": action_text,
                        "action_name": action_name,
                        "parsed_action": parsed,
                        "planner_response": planner_response,
                        "planner_response_raw": raw_planner_response,
                        "error": validation_error,
                        "screenshot_before": before_path,
                        **({"repair": repair_record} if isinstance(repair_record, dict) else {}),
                    }
                )
                break

            step_record = {
                "step": step_index,
                "thought": thought,
                "action": action_text,
                "action_name": action_name,
                "parsed_action": parsed,
                "screenshot_before": before_path,
                "planner_response": planner_response,
                "planner_response_raw": raw_planner_response,
            }
            if isinstance(repair_record, dict):
                step_record["repair"] = repair_record

            if action_name == "finished":
                verify_done = True
                verify_reason = "verify skipped"
                if verify_on_finish:
                    try:
                        verify_done, verify_reason = self._run_with_timeout(
                            lambda: self._verify_finished(
                                verifier_agent=planner_agent,
                                verify_prompt=verify_prompt,
                                instruction=instruction,
                                screenshot_path=before_path,
                                planner_response=planner_response,
                                mode=verify_mode,
                            ),
                            timeout_seconds=verify_timeout_seconds,
                        )
                    except Exception as e:
                        verify_done = False
                        verify_reason = f"verify_failed: {str(e)}"
                step_record["verify_done"] = verify_done
                step_record["verify_reason"] = verify_reason
                step_record["status"] = "finished_verified" if verify_done else "finished_rejected"
                _append_step_record(step_record)
                if verify_done:
                    finished = True
                    final_reason = verify_reason or "finished"
                    break
                history.append(
                    {
                        "step": step_index,
                        "action": action_text,
                        "result": json.dumps(
                            {"ok": False, "kind": "finished", "screen_changed": None, "reason": "finished rejected"},
                            ensure_ascii=False,
                        ),
                    }
                )
                step_index += 1
                continue

            exec_result = self._execute_action(parsed=parsed, dry_run=dry_run)
            step_record["execute"] = exec_result
            if not self._to_bool(exec_result.get("ok"), default=False):
                exec_result["screen_changed"] = None
                step_record["observation"] = {"screen_changed": None, "note": "execution_failed"}
                step_record["status"] = "execute_failed"
                _append_step_record(step_record)
                final_reason = f"execute_failed: {exec_result.get('error')}"
                break

            after_path = os.path.join(run_dir, f"step_{step_index:02d}_after.png")
            capture_after, fallback_index = self._capture_screenshot(
                after_path,
                capture_region,
                fallback_images,
                fallback_index,
            )
            after_capture_ok = self._to_bool(capture_after.get("ok"), default=False)
            if not after_capture_ok:
                step_record["screenshot_after_error"] = str(capture_after.get("error") or "")
                planner_feedback_path = ""

            screen_changed: bool | None = None
            before_sig = ""
            after_sig = ""
            try:
                before_sig = self._image_signature(before_path)
            except Exception:
                before_sig = ""
            if after_capture_ok:
                try:
                    after_sig = self._image_signature(after_path)
                except Exception:
                    after_sig = ""
            if before_sig and after_sig:
                screen_changed = before_sig != after_sig
                change_ratio = self._image_change_ratio(before_path, after_path)
                if change_ratio >= 0:
                    exec_result["change_ratio"] = round(change_ratio, 6)
                    if change_ratio < float(self.min_screen_change_ratio):
                        screen_changed = False
            exec_result["screen_changed"] = screen_changed
            if screen_changed is False:
                exec_result["effect"] = "no_visible_change"

            if after_capture_ok:
                after_display_path = after_path
                if action_name in {"click", "left_double", "right_single", "long_press", "drag", "scroll"}:
                    try:
                        marked_path = os.path.join(run_dir, f"step_{step_index:02d}_after_marked.png")
                        mark_ok, mark_error, marker_meta = self._draw_action_marker(
                            image_path=after_path,
                            action_name=action_name,
                            parsed=parsed,
                            exec_result=exec_result,
                            save_path=marked_path,
                        )
                        if mark_ok:
                            step_record["screenshot_after_raw"] = after_path
                            step_record["screenshot_after_marked"] = marked_path
                            after_display_path = marked_path
                            exec_result["after_marked"] = True
                            if isinstance(marker_meta, dict) and marker_meta:
                                exec_result["marked_coordinates"] = marker_meta
                        else:
                            step_record["screenshot_after_marked_error"] = str(mark_error or "")
                            exec_result["after_marked"] = False
                    except Exception as e:
                        step_record["screenshot_after_marked_error"] = str(e)
                        exec_result["after_marked"] = False
                step_record["screenshot_after"] = after_display_path
                screenshot_paths.append(after_display_path)
                planner_feedback_path = after_display_path

            step_record["observation"] = {
                "screen_changed": screen_changed,
                "before_signature": before_sig,
                "after_signature": after_sig,
            }

            step_record["status"] = "executed"
            _append_step_record(step_record)
            history.append(
                {
                    "step": step_index,
                    "action": action_text,
                    "result": json.dumps(exec_result, ensure_ascii=False),
                }
            )
            step_index += 1

        status = "done" if finished else "stopped"
        summary_lines = [
            f"GUI loop {status}.",
            f"instruction: {instruction}",
            f"steps: {len(step_logs)}",
            f"reason: {final_reason}",
            f"run_dir: {run_dir}",
        ]
        summary_text = "\n".join(summary_lines)
        self._append_run_log(
            run_dir,
            {
                "event": "run_finished",
                "status": status,
                "finished": finished,
                "reason": final_reason,
                "step_count": len(step_logs),
            },
        )

        parts: list[dict] = [{"type": "text", "text": summary_text}]
        for img_path in screenshot_paths[-6:]:
            parts.append(build_resource_part(uri=img_path, kind="image", source="gui_agent"))
        parts.append(
            {
                "type": "structured",
                "data": {
                    "status": status,
                    "finished": finished,
                    "reason": final_reason,
                    "instruction": instruction,
                    "steps": step_logs,
                    "run_dir": run_dir,
                    "planner_provider_id": provider_id,
                    "mode": planner_mode,
                    "verify_mode": verify_mode,
                    "dry_run": dry_run,
                    "verify_on_finish": verify_on_finish,
                    "planner_timeout_seconds": planner_timeout_seconds,
                    "verify_timeout_seconds": verify_timeout_seconds,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                },
            }
        )

        output = normalize_envelope({"role": "assistant", "parts": parts}, default_role="assistant")
        return {
            "display": summary_text,
            "routes": [{"output_index": 0, "payload": output}],
        }

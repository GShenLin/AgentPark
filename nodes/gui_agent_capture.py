import os
import shutil

from src.value_parsing import parse_int_value, parse_json_value


def parse_capture_region(value: object) -> dict | None:
    region = parse_json_value(value, {})
    if not isinstance(region, dict) or not region:
        return None
    keys = ["left", "top", "width", "height"]
    out: dict[str, int] = {}
    for key in keys:
        if key not in region:
            return None
        num = parse_int_value(region.get(key), default=-1)
        if num < 0 and key in {"left", "top"}:
            num = 0
        if num <= 0 and key in {"width", "height"}:
            return None
        out[key] = num
    return out


def capture_screenshot(
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
            width, height = _image_size(save_path)
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
def _image_size(path: str) -> tuple[int, int]:
    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as img:
            width, height = img.size
            return int(width), int(height)
    except Exception:
        return 1920, 1080

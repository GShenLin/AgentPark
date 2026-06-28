import base64
import io
import json
import time

from src.desktop_screenshot import ScreenshotCaptureError, capture_image
from src.runtime_cancellation import CancellationRequested, cancel_source_from_agent, raise_if_cancel_requested
from src.value_parsing import parse_int_value, parse_optional_int_value


_SUPPORTED_FORMATS = {"png", "bmp", "jpeg", "jpg"}
_SUPPORTED_BACKENDS = {"gdi", "pyautogui", "auto"}


def capture_screenshot(
    capture_region=None,
    image_format="png",
    backend="gdi",
    png_compress_level=1,
    jpeg_quality=92,
    agent=None,
):
    """
    Capture a desktop screenshot and return the encoded image directly to the model.
    """
    started_at = time.perf_counter()
    try:
        cancel_source = cancel_source_from_agent(agent)
        raise_if_cancel_requested(cancel_source)

        normalized_format = _normalize_format(image_format)
        normalized_backend = _normalize_backend(backend)
        region = _parse_capture_region(capture_region)

        image, actual_backend, actual_region = capture_image(region, normalized_backend)
        raise_if_cancel_requested(cancel_source)

        encoded_bytes = _encode_image_bytes(image, normalized_format, png_compress_level, jpeg_quality)

        elapsed_ms = int(round((time.perf_counter() - started_at) * 1000))
        width, height = image.size
        mime_type = _mime_type(normalized_format)
        return json.dumps(
            {
                "status": "success",
                "base64_image": base64.b64encode(encoded_bytes).decode("ascii"),
                "mime_type": mime_type,
                "saved": False,
                "width": int(width),
                "height": int(height),
                "format": normalized_format,
                "backend": actual_backend,
                "capture_region": actual_region,
                "encoded_size_bytes": len(encoded_bytes),
                "elapsed_ms": elapsed_ms,
            },
            ensure_ascii=False,
        )
    except CancellationRequested as exc:
        return json.dumps({"status": "stopped", "error": str(exc)}, ensure_ascii=False)
    except (ScreenshotCaptureError, ValueError) as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {"status": "exception", "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def _normalize_backend(value):
    backend = str(value or "gdi").strip().lower()
    if backend not in _SUPPORTED_BACKENDS:
        raise ValueError(f"backend must be one of: {', '.join(sorted(_SUPPORTED_BACKENDS))}")
    return backend


def _normalize_format(value):
    raw = str(value or "").strip().lower().lstrip(".")
    if raw == "auto":
        raw = "png"
    image_format = raw or "png"
    if image_format not in _SUPPORTED_FORMATS:
        raise ValueError(f"image_format must be one of: {', '.join(sorted(_SUPPORTED_FORMATS | {'auto'}))}")
    return "jpeg" if image_format == "jpg" else image_format


def _parse_capture_region(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception as exc:
            raise ValueError("capture_region must be a JSON object or object.") from exc
    if not isinstance(value, dict):
        raise ValueError("capture_region must be an object with left, top, width, and height.")

    missing = [key for key in ("left", "top", "width", "height") if key not in value]
    if missing:
        raise ValueError(f"capture_region missing required fields: {', '.join(missing)}")

    parsed = {}
    for key in ("left", "top", "width", "height"):
        try:
            parsed_value = parse_optional_int_value(f"capture_region.{key}", value[key])
        except Exception as exc:
            raise ValueError(f"capture_region.{key} must be a number.") from exc
        if parsed_value is None:
            raise ValueError(f"capture_region.{key} must be a number.")
        parsed[key] = parsed_value
    if parsed["width"] == 0 and parsed["height"] == 0:
        return None
    if parsed["width"] <= 0 or parsed["height"] <= 0:
        raise ValueError("capture_region.width and capture_region.height must be positive.")
    return parsed


def _encode_image_bytes(image, image_format, png_compress_level, jpeg_quality):
    save_format = "JPEG" if image_format == "jpeg" else image_format.upper()
    options = {}
    if image_format == "png":
        options["compress_level"] = _clamp_int(png_compress_level, 0, 9, 1)
        options["optimize"] = False
    elif image_format == "jpeg":
        options["quality"] = _clamp_int(jpeg_quality, 1, 100, 92)
        options["optimize"] = False
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format=save_format, **options)
    return buffer.getvalue()


def _mime_type(image_format):
    if image_format == "jpeg":
        return "image/jpeg"
    if image_format == "bmp":
        return "image/bmp"
    return "image/png"


def _clamp_int(value, min_value, max_value, default):
    return parse_int_value(value, default=default, minimum=min_value, maximum=max_value)


capture_screenshot_declaration = {
    "type": "function",
    "function": {
        "name": "capture_screenshot",
        "description": (
            "Capture a local desktop screenshot and return the image directly to the model. "
            "Uses fast Windows GDI by default and does not write image files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "capture_region": {
                    "type": "object",
                    "description": (
                        "Optional screen region object: {left, top, width, height}. Coordinates are desktop pixels. "
                        "Use width=0 and height=0 for full-screen capture."
                    ),
                    "properties": {
                        "left": {"type": "integer"},
                        "top": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                    "required": ["left", "top", "width", "height"],
                },
                "image_format": {
                    "type": "string",
                    "enum": ["png", "bmp", "jpeg", "jpg", "auto"],
                    "description": "Returned image format. auto resolves to png. Use bmp for fastest encoding, png for compact lossless output.",
                    "default": "png",
                },
                "backend": {
                    "type": "string",
                    "enum": ["gdi", "pyautogui", "auto"],
                    "description": "Capture backend. gdi is fastest on Windows; auto tries gdi then pyautogui.",
                    "default": "gdi",
                },
                "png_compress_level": {
                    "type": "integer",
                    "description": "PNG compression level 0-9. Lower is faster. Default 1.",
                    "default": 1,
                },
                "jpeg_quality": {
                    "type": "integer",
                    "description": "JPEG quality 1-100 when image_format is jpeg/jpg. Default 92.",
                    "default": 92,
                },
            },
        },
    },
}

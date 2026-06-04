from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any


@dataclass(frozen=True)
class ToolResultProcessingOutcome:
    cleaned_result: Any
    image_data: dict[str, Any] | None = None
    diagnostics: tuple[str, ...] = ()


def process_tool_result_outcome(tool_result: Any) -> ToolResultProcessingOutcome:
    cleaned_result = tool_result
    image_data = None
    diagnostics: list[str] = []

    try:
        result_data = tool_result
        if isinstance(result_data, str):
            try:
                result_data = json.loads(result_data)
            except json.JSONDecodeError:
                pass

        if isinstance(result_data, dict):
            if "base64_image" in result_data:
                original_base64 = result_data["base64_image"]
                resized = resize_base64_image_result(original_base64)
                optimized_base64 = resized.value
                diagnostics.extend(resized.diagnostics)

                image_data = {
                    "base64": optimized_base64,
                    "path": result_data.get("image_path"),
                    "mime_type": "image/png",
                }

                log_data = result_data.copy()
                del log_data["base64_image"]
                log_data["base64_image"] = "<base64_image_data_truncated>"
                cleaned_result = json.dumps(log_data, ensure_ascii=False)
            elif result_data.get("action") == "inspect_image" and result_data.get("image_path"):
                image_data = {
                    "base64": None,
                    "path": result_data["image_path"],
                    "mime_type": "image/png",
                }
            elif result_data.get("final_image_path"):
                final_image_path = str(result_data.get("final_image_path") or "").strip()
                if final_image_path and os.path.isfile(final_image_path):
                    image_data = {
                        "base64": None,
                        "path": final_image_path,
                        "mime_type": "image/png",
                    }
                elif final_image_path:
                    diagnostics.append(f"final_image_path does not exist: {final_image_path}")
    except Exception as e:
        diagnostics.append(f"Error processing tool result: {type(e).__name__}: {e}")

    return ToolResultProcessingOutcome(
        cleaned_result=cleaned_result,
        image_data=image_data,
        diagnostics=tuple(diagnostics),
    )


def process_tool_result(tool_result: Any) -> tuple[Any, dict[str, Any] | None]:
    outcome = process_tool_result_outcome(tool_result)
    return outcome.cleaned_result, outcome.image_data


@dataclass(frozen=True)
class ResizeBase64ImageResult:
    value: str
    diagnostics: tuple[str, ...] = ()


def resize_base64_image_result(
    base64_string: str,
    max_size: tuple[int, int] = (1024, 1024),
) -> ResizeBase64ImageResult:
    try:
        import base64
        import io

        from PIL import Image

        img_data = base64.b64decode(base64_string)
        img = Image.open(io.BytesIO(img_data))

        if img.width > max_size[0] or img.height > max_size[1]:
            img.thumbnail(max_size, Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            return ResizeBase64ImageResult(base64.b64encode(buffer.getvalue()).decode("utf-8"))

        return ResizeBase64ImageResult(base64_string)
    except ImportError:
        return ResizeBase64ImageResult(base64_string, ("Pillow is not installed; image resize skipped.",))
    except Exception as e:
        return ResizeBase64ImageResult(
            base64_string,
            (f"Failed to resize base64 image: {type(e).__name__}: {e}",),
        )


def resize_base64_image(base64_string: str, max_size: tuple[int, int] = (1024, 1024)) -> str:
    return resize_base64_image_result(base64_string, max_size=max_size).value

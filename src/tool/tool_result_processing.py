from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any


@dataclass(frozen=True)
class ToolResultProcessingOutcome:
    cleaned_result: Any
    images: tuple[dict[str, Any], ...] = ()
    diagnostics: tuple[str, ...] = ()


def process_tool_result_outcome(tool_result: Any) -> ToolResultProcessingOutcome:
    cleaned_result = tool_result
    image_data = None
    images = []
    diagnostics: list[str] = []

    try:
        result_data = tool_result
        if isinstance(result_data, str):
            try:
                result_data = json.loads(result_data)
            except json.JSONDecodeError:
                pass

        if isinstance(result_data, dict):
            if result_data.get('kind') == 'local_image':
                if (result_data.get('status') != 'success'
                        or not isinstance(result_data.get('base64_image'), str)
                        or not result_data['base64_image']
                        or result_data.get('mime_type') not in {'image/png', 'image/jpeg', 'image/webp'}
                        or result_data.get('detail') not in {'high', 'original'}):
                    raise ValueError('Invalid local_image tool result')
                image_data = {
                    'base64': result_data['base64_image'], 'path': result_data['image_path'],
                    'mime_type': result_data['mime_type'], 'detail': result_data['detail'],
                    'placement': 'tool_output',
                }
                cleaned_result = json.dumps(
                    {key: value for key, value in result_data.items() if key != 'base64_image'},
                    ensure_ascii=False,
                )
            elif result_data.get('kind') == 'computer_use_state':
                screenshots = result_data['screenshots']
                if not isinstance(screenshots, list) or len(screenshots) > 4:
                    raise ValueError('Computer Use screenshots must be a list of at most 4 images')
                sanitized = []
                for screenshot in screenshots:
                    encoded = screenshot['base64_image']
                    if not isinstance(encoded, str) or not encoded:
                        raise ValueError('Computer Use screenshot must contain base64 image text')
                    images.append({'base64': encoded, 'path': '', 'mime_type': screenshot['mime_type'],
                                   'label': f"Screenshot {screenshot['image_order']}: window {screenshot['window']['id']}, screenshotId={screenshot['id']}. Coordinates are relative to this image."})
                    if 'action_overlay' in screenshot:
                        images[-1]['label'] += (
                            ' X overlays mark dispatched pointer positions, NOT verified hits. '
                            'Drag: cyan=start, orange=end. Ruler ticks=10 original image pixels. '
                            'Compare the X with the intended target; account for content movement. '
                            'Overlay coordinates are local to THIS image; see action_overlay metadata.')
                    sanitized.append({**screenshot, 'base64_image': '<base64_image_data_truncated>'})
                cleaned_result = json.dumps({**result_data, 'screenshots': sanitized}, ensure_ascii=False)
            elif "base64_image" in result_data:
                original_base64 = result_data["base64_image"]
                mime_type = str(result_data.get("mime_type") or "image/png").strip() or "image/png"
                image_path = str(result_data.get("image_path") or result_data.get("path") or "").strip()

                image_data = {
                    "base64": original_base64,
                    "path": image_path,
                    "mime_type": mime_type,
                }

                log_data = result_data.copy()
                del log_data["base64_image"]
                log_data["base64_image"] = "<base64_image_data_truncated>"
                cleaned_result = json.dumps(log_data, ensure_ascii=False)
            elif result_data.get("action") == "inspect_image" and result_data.get("image_path"):
                image_data = {
                    "base64": None,
                    "path": result_data["image_path"],
                    "mime_type": str(result_data.get("mime_type") or "image/png").strip() or "image/png",
                }
            elif result_data.get("final_image_path"):
                final_image_path = str(result_data.get("final_image_path") or "").strip()
                if final_image_path and os.path.isfile(final_image_path):
                    image_data = {
                        "base64": None,
                        "path": final_image_path,
                        "mime_type": str(result_data.get("mime_type") or "image/png").strip() or "image/png",
                    }
                elif final_image_path:
                    diagnostics.append(f"final_image_path does not exist: {final_image_path}")
    except Exception as e:
        if isinstance(result_data, dict) and result_data.get('kind') == 'local_image':
            raise ValueError(f'Invalid local image result: {e}') from e
        if isinstance(result_data, dict) and result_data.get('kind') == 'computer_use_state':
            raise ValueError(f'Invalid Computer Use image result: {e}') from e
        diagnostics.append(f"Error processing tool result: {type(e).__name__}: {e}")

    return ToolResultProcessingOutcome(
        cleaned_result=cleaned_result,
        images=tuple(images) if images else ((image_data,) if image_data else ()),
        diagnostics=tuple(diagnostics),
    )


def process_tool_result(tool_result: Any) -> tuple[Any, tuple[dict[str, Any], ...]]:
    outcome = process_tool_result_outcome(tool_result)
    return outcome.cleaned_result, outcome.images


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

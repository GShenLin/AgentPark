from __future__ import annotations

from typing import Any

from src.providers.responses_input_items import build_responses_message_input_item
from src.tool.local_image import prepare_local_image


def append_chat_tool_images(runtime: Any, images) -> None:
    for image in images:
        part = build_tool_image_content_item(image)
        if part is None:
            raise ValueError("Image tool output has no image data")
        image_url = {"url": part["image_url"]}
        if "detail" in part:
            image_url["detail"] = part["detail"]
        runtime.Message("user", [
            {"type": "text", "text": image.get("label") or f"Image from tool: {image.get('path', '')}"},
            {"type": "image_url", "image_url": image_url},
        ], persist=False)


def build_tool_image_content_item(image_data: dict[str, Any] | None):
    if not isinstance(image_data, dict):
        return None

    base64_data = image_data.get("base64")
    if base64_data:
        encoded = base64_data.decode("utf-8") if isinstance(base64_data, bytes) else str(base64_data)
        encoded = encoded.strip()
        if not encoded:
            return None
        mime_type = str(image_data.get("mime_type") or "image/png").strip() or "image/png"
        image_url = f"data:{mime_type};base64,{encoded}"
    else:
        path = str(image_data.get("path") or "").strip()
        if not path:
            return None
        if path.startswith(("https://", "http://", "data:image/")):
            image_url = path
        else:
            prepared = prepare_local_image(path, image_data.get("detail", "high"))
            image_url = f"data:{prepared['mime_type']};base64,{prepared['base64_image']}"

    part = {"type": "input_image", "image_url": image_url}
    if "detail" in image_data:
        if image_data["detail"] not in {"high", "original"}:
            raise ValueError("Tool image detail must be high or original")
        part["detail"] = image_data["detail"]
    return part


def build_image_tool_output(call_id: str, text: str, images) -> dict[str, Any]:
    content = [{"type": "input_text", "text": text}]
    for image in images:
        part = build_tool_image_content_item(image)
        if part is None:
            raise ValueError("Image tool output has no image data")
        content.append(part)
    return {"type": "function_call_output", "call_id": call_id, "output": content, "status": "completed"}


def build_tool_image_responses_input_item(image_data: dict[str, Any] | None):
    part = build_tool_image_content_item(image_data)
    if part is None:
        return None

    return build_responses_message_input_item(
        role="user",
        content=[
            {"type": "input_text", "text": image_data.get('label') or "Image captured by tool."},
            part,
        ],
    )

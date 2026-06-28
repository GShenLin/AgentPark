from __future__ import annotations

from typing import Any

from src.providers.responses_input_items import build_responses_message_input_item


def build_tool_image_responses_input_item(image_data: dict[str, Any] | None):
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
        image_url = path

    return build_responses_message_input_item(
        role="user",
        content=[
            {"type": "input_text", "text": "Image captured by tool."},
            {"type": "input_image", "image_url": image_url},
        ],
    )

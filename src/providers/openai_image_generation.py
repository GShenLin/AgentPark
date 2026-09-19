"""Standalone Images API requests for Agent image generation and reference edits."""
from __future__ import annotations

import base64
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname
import uuid

from PIL import Image

from src.provider_auth import resolve_provider_request_credentials
from src.providers.image_generation_input import latest_image_generation_input
from src.runtime_cancellation import raise_if_cancel_requested


MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_EDIT_IMAGES = 5
IMAGE_FORMATS = {"PNG": ("image/png", "png"), "JPEG": ("image/jpeg", "jpg"), "WEBP": ("image/webp", "webp")}


def _image_format(content: bytes) -> tuple[str, str]:
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("Image must be non-empty and no larger than 50 MB")
    with Image.open(BytesIO(content)) as image:
        image_format = image.format
        image.verify()
    if image_format not in IMAGE_FORMATS:
        raise ValueError("Images API supports PNG, JPEG and WebP images")
    return IMAGE_FORMATS[image_format]


def _reference_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    if value.startswith("data:"):
        header, encoded = value.split(",", 1)
        content = base64.b64decode(encoded, validate=True)
        mime, _ = _image_format(content)
        if header != f"data:{mime};base64":
            raise ValueError("Reference image data URL does not match its image format")
        return value
    path = Path(url2pathname(parsed.path) if parsed.scheme == "file" else value)
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("Reference image exceeds 50 MB")
    content = path.read_bytes()
    mime, _ = _image_format(content)
    return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


class OpenAIImageGeneration:
    """Reuse the Agent transport/auth boundary and return persisted image resources."""

    def __init__(self, agent):
        self.agent = agent

    def send(self, options: dict | None) -> dict:
        if options is not None and not isinstance(options, dict):
            raise ValueError("Image mode options must be an object")
        options = options or {}
        agent = self.agent
        prompt, references = latest_image_generation_input(agent.messages, options.get("image_references"))
        if not prompt:
            raise ValueError("A prompt is required for image generation")
        if len(references) > MAX_EDIT_IMAGES:
            raise ValueError(f"Images API accepts at most {MAX_EDIT_IMAGES} reference images")
        model = agent.config.get("model")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("An image model is required")
        prefix = options.get("image_filename_prefix", "generated_image")
        if not isinstance(prefix, str) or not prefix or any(c in prefix for c in '<>:"/\\|?*') or any(ord(c) < 32 for c in prefix):
            raise ValueError("Image filename prefix must be a plain filename")
        memory_path = agent.current_memory_path
        if not memory_path:
            raise ValueError("Image generation requires a node memory path")
        output_dir = Path(memory_path).resolve().parent / "generated_images"
        payload = {"model": model, "prompt": prompt, "background": "auto", "quality": "auto", "size": "auto"}
        endpoint = "images/edits" if references else "images/generations"
        if references:
            payload["images"] = [{"image_url": _reference_url(value)} for value in references]
        raise_if_cancel_requested(agent._cancel_source())
        credentials = resolve_provider_request_credentials(agent.config)
        agent._emit_provider_runtime_notice(message=f"Generating image with {model}.", stage="image_generation_start")
        response = agent._post_json_with_retry(
            endpoint=endpoint,
            url=f"{credentials.base_url.rstrip('/')}/{endpoint}",
            headers={"Content-Type": "application/json", **credentials.headers},
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        items = response.get("data") if isinstance(response, dict) else None
        if not isinstance(items, list) or not items:
            raise ValueError("Images API response must contain a non-empty data array")
        decoded = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("b64_json"), str):
                raise ValueError("Images API data items must contain b64_json")
            content = base64.b64decode(item["b64_json"], validate=True)
            _, extension = _image_format(content)
            decoded.append((content, extension))
        raise_if_cancel_requested(agent._cancel_source())
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for content, extension in decoded:
            path = output_dir / f"{prefix}_{uuid.uuid4().hex}.{extension}"
            path.write_bytes(content)
            paths.append(str(path))
        result = {"response": "Image generation completed.", "image_path": paths[0] if len(paths) == 1 else paths}
        agent.Message("assistant", json.dumps(result, ensure_ascii=False))
        return result

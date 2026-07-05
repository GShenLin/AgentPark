from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
from urllib.parse import quote

from src.media_resource_utils import normalize_public_base_url
from src.message_protocol import MetaPart
from src.message_protocol import ResourcePart
from src.message_protocol import StructuredPart
from src.message_protocol import TextPart
from src.message_protocol import build_resource_part, build_text_envelope, envelope_text, normalize_envelope
from src.message_protocol import normalize_message_envelope
from src.video_generation_content import build_doubao_video_generation_content


_AGENT_IMAGE_MAX_INLINE_BYTES = 512 * 1024
_AGENT_IMAGE_RAW_FALLBACK_MAX_BYTES = 128 * 1024
_AGENT_IMAGE_JPEG_QUALITIES = (82, 72, 62)
_AGENT_IMAGE_RESIZE_DIMENSIONS = (1024, 768, 512)


def build_agent_user_content(
    provider_id: str,
    mode: str,
    message: object,
    public_base_url: object = "",
    *,
    include_images: bool = True,
):
    envelope = normalize_message_envelope(message, default_role="user")
    text_parts: list[str] = []
    image_resources: list[dict] = []
    other_resources: list[dict] = []

    for part in envelope.parts:
        if isinstance(part, TextPart):
            text = part.text.strip()
            if text:
                text_parts.append(text)
            continue
        if isinstance(part, StructuredPart):
            data = part.data
            if data is not None:
                text_parts.append(json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else str(data))
            continue
        if isinstance(part, MetaPart):
            if part.meta:
                text_parts.append(json.dumps({"meta": part.meta}, ensure_ascii=False))
            continue
        if not isinstance(part, ResourcePart):
            continue
        res = part.resource
        uri = str(res.get("uri") or "").strip()
        kind = str(res.get("kind") or "").strip().lower()
        if include_images and kind == "image" and uri:
            image_resources.append(res)
        else:
            other_resources.append(res)

    mode_name = str(mode or "").strip().lower()
    if mode_name == "video_generation" and "doubao" in str(provider_id or "").strip().lower():
        return build_doubao_video_generation_content(
            envelope.to_dict(),
            public_base_url=public_base_url,
        )

    if other_resources:
        text_parts.extend(
            [f"[{str(item.get('kind') or 'file')}] {str(item.get('uri') or '').strip()}" for item in other_resources]
        )
    if image_resources and _should_include_image_reference_text(mode_name, image_resources):
        text_parts.extend(_resource_reference_line(item) for item in image_resources)
    merged_text = "\n".join([item for item in text_parts if item]).strip()
    provider = str(provider_id or "").strip().lower()

    if not image_resources:
        return merged_text

    if "gemini" in provider:
        local_path = _to_local_path(image_resources[0].get("uri"))
        if local_path and os.path.exists(local_path):
            return {"type": "image", "path": local_path, "text": merged_text}
        return merged_text + f"\n[image] {image_resources[0].get('uri')}"

    content_parts = []
    if merged_text:
        content_parts.append({"type": "text", "text": merged_text})
    for resource in image_resources:
        uri = str(resource.get("uri") or "").strip()
        image_url = uri
        local_path = _to_local_path(uri)
        if local_path and os.path.exists(local_path):
            image_url = _local_image_to_agent_url(resource, local_path, public_base_url)
        content_parts.append({"type": "image_url", "image_url": {"url": image_url}})
    return content_parts


def build_agent_output_message(response: object) -> dict:
    if isinstance(response, dict):
        parts: list[dict] = []
        response_text = str(response.get("response") or response.get("text") or "").strip()
        if response_text:
            parts.append({"type": "text", "text": response_text})

        image_path = response.get("image_path")
        if isinstance(image_path, str) and image_path.strip():
            parts.append(build_resource_part(uri=image_path.strip(), kind="image", source="agent"))
        elif isinstance(image_path, list):
            for item in image_path:
                uri = str(item or "").strip()
                if uri:
                    parts.append(build_resource_part(uri=uri, kind="image", source="agent"))

        video_path = response.get("video_path")
        if isinstance(video_path, str) and video_path.strip():
            parts.append(build_resource_part(uri=video_path.strip(), kind="video", source="agent"))
        elif isinstance(video_path, list):
            for item in video_path:
                uri = str(item or "").strip()
                if uri:
                    parts.append(build_resource_part(uri=uri, kind="video", source="agent"))

        if not parts:
            parts.append({"type": "text", "text": json.dumps(response, ensure_ascii=False)})
        return normalize_envelope({"role": "assistant", "parts": parts}, default_role="assistant")

    text = "" if response is None else str(response)
    return build_text_envelope(text, role="assistant")


def extract_channel_meta(message: object) -> list[dict]:
    envelope = normalize_message_envelope(message, default_role="user")
    output: list[dict] = []
    for part in envelope.parts:
        if isinstance(part, MetaPart) and str(part.meta.get("channel") or "").strip():
            output.append({"type": "meta", "meta": dict(part.meta)})
    return output


def append_channel_meta(output_message: dict, meta_parts: list[dict]) -> dict:
    if not meta_parts:
        return output_message
    envelope = normalize_envelope(output_message, default_role="assistant")
    parts = envelope.get("parts")
    if not isinstance(parts, list):
        parts = []
    existing_keys = set()
    for part in parts:
        if not isinstance(part, dict) or str(part.get("type") or "").strip().lower() != "meta":
            continue
        meta = part.get("meta")
        if isinstance(meta, dict):
            existing_keys.add(
                (
                    str(meta.get("channel") or ""),
                    str(meta.get("accountId") or ""),
                    str(meta.get("from") or ""),
                )
            )
    for part in meta_parts:
        meta = part.get("meta") if isinstance(part, dict) else None
        key = (
            str((meta or {}).get("channel") or ""),
            str((meta or {}).get("accountId") or ""),
            str((meta or {}).get("from") or ""),
        )
        if key not in existing_keys:
            parts.append(part)
            existing_keys.add(key)
    envelope["parts"] = parts
    return envelope


def append_input_resources_for_imagechat(output_message: dict, input_message: object, mode: object) -> dict:
    if str(mode or "").strip().lower() != "imagechat":
        return output_message

    output_envelope = normalize_envelope(output_message, default_role="assistant")
    input_envelope = normalize_message_envelope(input_message, default_role="user")
    parts = output_envelope.get("parts")
    if not isinstance(parts, list):
        parts = []

    existing_uris = {
        str(((part or {}).get("resource") or {}).get("uri") or "").strip()
        for part in parts
        if isinstance(part, dict) and str(part.get("type") or "").strip().lower() == "resource"
    }

    for part in input_envelope.parts:
        if not isinstance(part, ResourcePart):
            continue
        resource = dict(part.resource)
        uri = str(resource.get("uri") or "").strip()
        kind = str(resource.get("kind") or "").strip().lower()
        if not uri or uri in existing_uris or kind != "image":
            continue
        parts.append(build_resource_part(
            uri=uri,
            kind=kind,
            mime=resource.get("mime"),
            name=resource.get("name"),
            source=resource.get("source") or "imagechat_input",
            metadata=resource.get("metadata"),
        ))
        existing_uris.add(uri)

    output_envelope["parts"] = parts
    return output_envelope


def history_envelope_to_agent_message(
    envelope: dict,
    provider_id: str,
    public_base_url: object = "",
) -> dict | None:
    role = str((envelope or {}).get("role") or "").strip().lower()
    if role not in {"user", "assistant"}:
        return None
    if role == "user":
        content = build_agent_user_content(provider_id, "chat", envelope, public_base_url, include_images=False)
    else:
        content = envelope_text(envelope).strip()

    if isinstance(content, str) and not content.strip():
        return None
    if isinstance(content, list) and not content:
        return None
    if content is None:
        return None
    return {"role": role, "content": content}


def _to_local_path(uri: object) -> str:
    raw = str(uri or "").strip()
    if not raw:
        return ""
    if raw.startswith("file://"):
        return raw[7:]
    return raw


def _resource_reference_line(resource: dict) -> str:
    kind = str(resource.get("kind") or "file").strip().lower() or "file"
    uri = str(resource.get("uri") or "").strip()
    if not uri:
        return ""
    if uri.startswith("data:"):
        name = str(resource.get("name") or "").strip()
        suffix = f" {name}" if name else ""
        return f"[{kind}] <data-url>{suffix}"
    return f"[{kind}] {uri}"


def _should_include_image_reference_text(mode_name: str, image_resources: list[dict]) -> bool:
    if mode_name == "imagechat":
        return True
    for resource in image_resources:
        source = str(resource.get("source") or "").strip().lower()
        if source == "image_generation":
            return True
    return False


def _local_image_to_agent_url(resource: dict, local_path: str, public_base_url: object) -> str:
    base = normalize_public_base_url(public_base_url)
    if base:
        return f"{base}/api/files/raw?path={quote(os.path.abspath(local_path), safe='')}&download=1"

    try:
        return _compress_local_image_to_data_url(local_path)
    except Exception as exc:
        size = os.path.getsize(local_path)
        if size <= _AGENT_IMAGE_RAW_FALLBACK_MAX_BYTES:
            return _raw_local_image_to_data_url(resource, local_path)
        raise ValueError(
            f"Local image is too large or unreadable for controlled inline upload: {local_path}"
        ) from exc


def _compress_local_image_to_data_url(local_path: str) -> str:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError("Pillow is required to compress local image inputs for agent requests.") from exc

    with Image.open(local_path) as source:
        image = ImageOps.exif_transpose(source)
        if image.mode not in {"RGB", "L"}:
            background = Image.new("RGB", image.size, (255, 255, 255))
            alpha = image.getchannel("A") if "A" in image.getbands() else None
            background.paste(image.convert("RGBA"), mask=alpha)
            image = background
        elif image.mode == "L":
            image = image.convert("RGB")
        else:
            image = image.copy()

    last_bytes = b""
    for max_dimension in _AGENT_IMAGE_RESIZE_DIMENSIONS:
        candidate = image.copy()
        candidate.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        for quality in _AGENT_IMAGE_JPEG_QUALITIES:
            buffer = io.BytesIO()
            candidate.save(buffer, format="JPEG", quality=quality, optimize=True)
            data = buffer.getvalue()
            last_bytes = data
            if len(data) <= _AGENT_IMAGE_MAX_INLINE_BYTES:
                encoded = base64.b64encode(data).decode("ascii")
                return f"data:image/jpeg;base64,{encoded}"

    raise ValueError(
        f"Compressed image still exceeds {_AGENT_IMAGE_MAX_INLINE_BYTES} bytes "
        f"after resizing to {_AGENT_IMAGE_RESIZE_DIMENSIONS[-1]}px: {len(last_bytes)} bytes"
    )


def _raw_local_image_to_data_url(resource: dict, local_path: str) -> str:
    with open(local_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    mime = _image_mime(resource, local_path)
    return f"data:{mime};base64,{encoded}"


def _image_mime(resource: dict, local_path: str) -> str:
    mime = str(resource.get("mime") or "").split(";")[0].strip().lower()
    if mime.startswith("image/"):
        return mime
    guessed = mimetypes.guess_type(local_path)[0]
    if guessed and guessed.startswith("image/"):
        return guessed
    return "image/png"

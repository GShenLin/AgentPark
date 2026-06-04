import base64
import mimetypes
import os
from urllib.parse import quote

from src.message_protocol import normalize_envelope


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv"}
_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}
_IMAGE_ROLES = {"reference_image", "first_frame", "last_frame"}
_VIDEO_ROLES = {"reference_video"}
_AUDIO_ROLES = {"reference_audio"}
_MIME_OVERRIDES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
}


def normalize_public_base_url(value: object) -> str:
    text = str(value or "").strip()
    return text.rstrip("/") if text else ""


def is_remote_generation_uri(uri: object) -> bool:
    value = str(uri or "").strip()
    return (
        value.startswith("http://")
        or value.startswith("https://")
        or value.startswith("asset://")
        or value.startswith("data:")
    )


def _guess_kind_from_uri(uri: object) -> str:
    raw = str(uri or "").strip().lower()
    _, ext = os.path.splitext(raw)
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    return ""


def _resolve_local_path(uri: object) -> str:
    raw = str(uri or "").strip()
    if not raw:
        return ""
    if raw.startswith("file://"):
        raw = raw[7:]
    candidate = os.path.abspath(raw)
    if os.path.isfile(candidate):
        return candidate
    return ""


def _guess_mime_type(path: str) -> str:
    _, ext = os.path.splitext(str(path or "").strip().lower())
    if ext in _MIME_OVERRIDES:
        return _MIME_OVERRIDES[ext]
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _encode_local_file_as_data_uri(local_path: str) -> str:
    mime_type = _guess_mime_type(local_path)
    with open(local_path, "rb") as file_obj:
        encoded = base64.b64encode(file_obj.read()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _normalize_resource_role(resource: dict, kind: str) -> str:
    metadata = resource.get("metadata")
    role = ""
    if isinstance(metadata, dict):
        role = str(metadata.get("role") or metadata.get("position") or "").strip().lower()
    if not role:
        role = str(resource.get("role") or "").strip().lower()

    if kind == "image" and role in _IMAGE_ROLES:
        return role
    if kind == "video" and role in _VIDEO_ROLES:
        return role
    if kind == "audio" and role in _AUDIO_ROLES:
        return role

    if kind == "image":
        return "reference_image"
    if kind == "video":
        return "reference_video"
    return "reference_audio"


def resolve_generation_resource_uri(
    uri: object,
    *,
    kind: str,
    public_base_url: object = "",
) -> str:
    raw = str(uri or "").strip()
    if not raw:
        return ""
    if is_remote_generation_uri(raw):
        return raw

    local_path = _resolve_local_path(raw)
    if not local_path:
        return raw

    if kind in {"image", "audio"}:
        return _encode_local_file_as_data_uri(local_path)

    base = normalize_public_base_url(public_base_url)
    if not base:
        raise ValueError(
            "Local video paths require asset:// or a publicly reachable URL. Configure public_base_url to expose the file, or upload it into Ark as an asset."
        )

    return f"{base}/api/files/raw?path={quote(local_path, safe='')}&download=1"


def build_doubao_video_generation_content(
    message: object,
    *,
    public_base_url: object = "",
    fallback_prompt: object = "",
) -> list[dict]:
    envelope = normalize_envelope(message, default_role="user")
    parts = envelope.get("parts") if isinstance(envelope, dict) else []
    text_parts: list[str] = []
    content_parts: list[dict] = []
    unsupported_kinds: set[str] = set()

    for part in parts if isinstance(parts, list) else []:
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type") or "").strip().lower()
        if part_type == "text":
            text = str(part.get("text") or "").strip()
            if text:
                text_parts.append(text)
            continue
        if part_type != "resource":
            continue

        resource = part.get("resource")
        if not isinstance(resource, dict):
            continue

        raw_kind = str(resource.get("kind") or "").strip().lower()
        raw_uri = str(resource.get("uri") or "").strip()
        if not raw_uri:
            continue

        kind = raw_kind if raw_kind in {"image", "video", "audio"} else _guess_kind_from_uri(raw_uri)
        if kind not in {"image", "video", "audio"}:
            unsupported_kinds.add(raw_kind or "file")
            continue

        role = _normalize_resource_role(resource, kind)
        resolved_uri = resolve_generation_resource_uri(
            raw_uri,
            kind=kind,
            public_base_url=public_base_url,
        )
        if kind == "image":
            content_parts.append({"type": "image_url", "image_url": {"url": resolved_uri}, "role": role})
        elif kind == "video":
            content_parts.append({"type": "video_url", "video_url": {"url": resolved_uri}, "role": role})
        else:
            content_parts.append({"type": "audio_url", "audio_url": {"url": resolved_uri}, "role": role})

    merged_text = "\n".join([item for item in text_parts if item]).strip()
    if not merged_text:
        merged_text = str(fallback_prompt or "").strip()
    if merged_text:
        content_parts.insert(0, {"type": "text", "text": merged_text})

    if unsupported_kinds:
        kinds = ", ".join(sorted(kind for kind in unsupported_kinds if kind))
        raise ValueError(f"Video generation does not support these resource kinds: {kinds}")

    if not content_parts:
        raise ValueError("Video generation requires at least one prompt or reference resource.")

    return content_parts

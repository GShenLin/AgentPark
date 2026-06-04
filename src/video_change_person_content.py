import os
from urllib.parse import quote, urlparse

from src.message_protocol import normalize_envelope


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi"}


def normalize_public_base_url(value: object) -> str:
    text = str(value or "").strip()
    return text.rstrip("/") if text else ""


def _guess_kind_from_uri(uri: object) -> str:
    raw = str(uri or "").strip().lower()
    _, ext = os.path.splitext(raw)
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _VIDEO_EXTS:
        return "video"
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


def _is_http_url(uri: object) -> bool:
    text = str(uri or "").strip()
    if not text:
        return False
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def resolve_public_media_url(uri: object, *, public_base_url: object = "") -> str:
    raw = str(uri or "").strip()
    if not raw:
        return ""
    if _is_http_url(raw):
        return raw
    if raw.startswith("asset://") or raw.startswith("data:"):
        raise ValueError(
            "Wan Animate Mix only accepts public HTTP/HTTPS media URLs. asset:// and data: URIs are not supported here."
        )

    local_path = _resolve_local_path(raw)
    if not local_path:
        raise ValueError(f"Unsupported media URI: {raw}")

    base = normalize_public_base_url(public_base_url)
    if not base:
        raise ValueError(
            "Local image/video paths require public_base_url so the node can expose them as HTTP URLs."
        )
    return f"{base}/api/files/raw?path={quote(local_path, safe='')}&download=1"


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _collect_media_candidates(message: object, *, configured_image_path: object = "", configured_video_path: object = "") -> tuple[list[str], list[str]]:
    envelope = normalize_envelope(message, default_role="user")
    parts = envelope.get("parts") if isinstance(envelope, dict) else []
    image_candidates: list[str] = []
    video_candidates: list[str] = []

    configured_image = str(configured_image_path or "").strip()
    if configured_image:
        image_candidates.append(configured_image)

    configured_video = str(configured_video_path or "").strip()
    if configured_video:
        video_candidates.append(configured_video)

    for part in parts if isinstance(parts, list) else []:
        if not isinstance(part, dict):
            continue
        if str(part.get("type") or "").strip().lower() != "resource":
            continue
        resource = part.get("resource")
        if not isinstance(resource, dict):
            continue
        uri = str(resource.get("uri") or "").strip()
        if not uri:
            continue
        kind = str(resource.get("kind") or "").strip().lower()
        if kind not in {"image", "video"}:
            kind = _guess_kind_from_uri(uri)
        if kind == "image":
            image_candidates.append(uri)
        elif kind == "video":
            video_candidates.append(uri)

    return _dedupe_preserve_order(image_candidates), _dedupe_preserve_order(video_candidates)


def resolve_video_change_person_inputs(
    message: object,
    *,
    image_path: object = "",
    video_path: object = "",
    public_base_url: object = "",
) -> tuple[str, str]:
    image_candidates, video_candidates = _collect_media_candidates(
        message,
        configured_image_path=image_path,
        configured_video_path=video_path,
    )

    if not image_candidates:
        raise ValueError("Video change person requires exactly one image input.")
    if not video_candidates:
        raise ValueError("Video change person requires exactly one video input.")
    if len(image_candidates) != 1:
        raise ValueError("Video change person accepts exactly one image input.")
    if len(video_candidates) != 1:
        raise ValueError("Video change person accepts exactly one video input.")

    return (
        resolve_public_media_url(image_candidates[0], public_base_url=public_base_url),
        resolve_public_media_url(video_candidates[0], public_base_url=public_base_url),
    )

"""Resource construction and identity-preserving normalization for message parts."""
from __future__ import annotations

import os
import uuid
from urllib.parse import urlparse

RESOURCE_KINDS = {"image", "video", "audio", "doc", "file", "url"}


def is_url(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https", "ftp", "file"}:
        return False
    return bool(parsed.netloc or parsed.path)


def _guess_kind_from_ext(path_or_url: str) -> str:
    raw = str(path_or_url or "").strip().lower()
    if not raw:
        return "file"
    ext = os.path.splitext(raw)[1].lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}:
        return "image"
    if ext in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv"}:
        return "video"
    if ext in {".mp3", ".wav", ".ogg", ".flac", ".m4a"}:
        return "audio"
    if ext in {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".md"}:
        return "doc"
    return "url" if is_url(raw) else "file"


def build_resource_part(
    *,
    uri: object,
    kind: object = "",
    mime: object = "",
    name: object = "",
    source: object = "",
    metadata: object = None,
    resource_id: object = "",
) -> dict:
    """Allocate identity for new resources; retain it when normalizing saved resources."""
    uri_text = str(uri or "").strip()
    kind_text = str(kind or "").strip().lower()
    if kind_text not in RESOURCE_KINDS:
        kind_text = _guess_kind_from_ext(uri_text)
    payload = {
        "id": str(resource_id or uuid.uuid4().hex),
        "uri": uri_text,
        "kind": kind_text,
    }
    mime_text = str(mime or "").strip()
    if mime_text:
        payload["mime"] = mime_text
    name_text = str(name or "").strip()
    if name_text:
        payload["name"] = name_text
    source_text = str(source or "").strip()
    if source_text:
        payload["source"] = source_text
    if isinstance(metadata, dict) and metadata:
        payload["metadata"] = metadata
    return {"type": "resource", "resource": payload}

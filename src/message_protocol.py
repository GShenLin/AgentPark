from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from urllib.parse import urlparse


RESOURCE_KINDS = {"image", "video", "audio", "doc", "file", "url"}
PART_TYPES = {"text", "resource", "structured", "tool_call", "meta"}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


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


def build_text_part(text: object) -> dict:
    return {"type": "text", "text": "" if text is None else str(text)}


def build_resource_part(
    *,
    uri: object,
    kind: object = "",
    mime: object = "",
    name: object = "",
    source: object = "",
    metadata: object = None,
) -> dict:
    uri_text = str(uri or "").strip()
    kind_text = str(kind or "").strip().lower()
    if kind_text not in RESOURCE_KINDS:
        kind_text = _guess_kind_from_ext(uri_text)
    payload = {
        "id": uuid.uuid4().hex,
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


def _normalize_part(item: object) -> dict:
    if isinstance(item, str):
        return build_text_part(item)

    if not isinstance(item, dict):
        return build_text_part(item)

    if "type" not in item:
        if "text" in item:
            return build_text_part(item.get("text"))
        if "uri" in item:
            return build_resource_part(
                uri=item.get("uri"),
                kind=item.get("kind"),
                mime=item.get("mime"),
                name=item.get("name"),
                source=item.get("source"),
                metadata=item.get("metadata"),
            )
        if "resource" in item and isinstance(item.get("resource"), dict):
            raw_res = item.get("resource") or {}
            return build_resource_part(
                uri=raw_res.get("uri"),
                kind=raw_res.get("kind"),
                mime=raw_res.get("mime"),
                name=raw_res.get("name"),
                source=raw_res.get("source"),
                metadata=raw_res.get("metadata"),
            )
        return {"type": "structured", "data": item}

    part_type = str(item.get("type") or "").strip().lower()
    if part_type not in PART_TYPES:
        return {"type": "structured", "data": item}

    if part_type == "text":
        return build_text_part(item.get("text"))

    if part_type == "resource":
        raw_res = item.get("resource")
        if isinstance(raw_res, dict):
            return build_resource_part(
                uri=raw_res.get("uri"),
                kind=raw_res.get("kind"),
                mime=raw_res.get("mime"),
                name=raw_res.get("name"),
                source=raw_res.get("source"),
                metadata=raw_res.get("metadata"),
            )
        return build_resource_part(
            uri=item.get("uri"),
            kind=item.get("kind"),
            mime=item.get("mime"),
            name=item.get("name"),
            source=item.get("source"),
            metadata=item.get("metadata"),
        )

    if part_type == "structured":
        return {"type": "structured", "data": item.get("data")}

    if part_type == "tool_call":
        payload = {"type": "tool_call"}
        if item.get("call_id") is not None:
            payload["call_id"] = str(item.get("call_id"))
        if item.get("name") is not None:
            payload["name"] = str(item.get("name"))
        if item.get("provider") is not None:
            payload["provider"] = str(item.get("provider"))
        if item.get("status") is not None:
            payload["status"] = str(item.get("status"))
        if item.get("duration_ms") is not None:
            payload["duration_ms"] = item.get("duration_ms")
        if item.get("error") is not None:
            payload["error"] = str(item.get("error"))
        if item.get("result_preview") is not None:
            payload["result_preview"] = str(item.get("result_preview"))
        diagnostics = item.get("diagnostics")
        if isinstance(diagnostics, list):
            payload["diagnostics"] = [str(entry) for entry in diagnostics]
        if item.get("args") is not None:
            payload["args"] = item.get("args")
        elif item.get("arguments") is not None:
            payload["args"] = item.get("arguments")
        return payload

    payload = {"type": "meta"}
    if item.get("meta") is not None:
        payload["meta"] = item.get("meta")
    elif item.get("data") is not None:
        payload["meta"] = item.get("data")
    else:
        payload["meta"] = {}
    return payload


def normalize_envelope(value: object, default_role: str = "user") -> dict:
    role = str(default_role or "user").strip().lower() or "user"
    if not isinstance(value, dict):
        if isinstance(value, list):
            parts = [_normalize_part(item) for item in value]
        else:
            parts = [build_text_part(value)]
        return {
            "id": uuid.uuid4().hex,
            "role": role,
            "parts": parts,
            "created_at": now_text(),
        }

    parts_raw = value.get("parts")
    if isinstance(parts_raw, list):
        parts = [_normalize_part(item) for item in parts_raw]
    elif "type" in value and "parts" not in value:
        parts = [_normalize_part(value)]
    elif any(key in value for key in ("text", "resource", "uri", "data")):
        parts = [_normalize_part(value)]
    else:
        content = value.get("content")
        if isinstance(content, list):
            parts = [_normalize_part(item) for item in content]
        else:
            parts = [build_text_part(content)]

    envelope = {
        "id": str(value.get("id") or uuid.uuid4().hex),
        "role": str(value.get("role") or role).strip().lower() or role,
        "parts": parts,
        "created_at": str(value.get("created_at") or now_text()),
    }
    trace_id = str(value.get("trace_id") or "").strip()
    if trace_id:
        envelope["trace_id"] = trace_id
    return envelope


def envelope_text(value: object) -> str:
    envelope = normalize_envelope(value, default_role="assistant")
    output: list[str] = []
    for part in envelope.get("parts") or []:
        if not isinstance(part, dict):
            continue
        typ = str(part.get("type") or "").strip().lower()
        if typ == "text":
            text = str(part.get("text") or "")
            if text:
                output.append(text)
            continue
        if typ == "resource":
            res = part.get("resource")
            if not isinstance(res, dict):
                continue
            kind = str(res.get("kind") or "file")
            uri = str(res.get("uri") or "").strip()
            if uri:
                output.append(f"[{kind}] {uri}")
            continue
        if typ == "structured":
            data = part.get("data")
            if data is None:
                continue
            if isinstance(data, (dict, list, tuple)):
                try:
                    output.append(json.dumps(data, ensure_ascii=False))
                except Exception:
                    output.append(str(data))
            else:
                output.append(str(data))
    return "\n".join([line for line in output if line]).strip()


def envelope_preview(value: object, limit: int = 260) -> str:
    text = envelope_text(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def build_text_envelope(text: object, role: str = "assistant") -> dict:
    return normalize_envelope({"role": role, "parts": [build_text_part(text)]}, default_role=role)


def build_resource_envelope(
    *,
    uri: object,
    role: str = "assistant",
    kind: object = "",
    mime: object = "",
    name: object = "",
    source: object = "",
    metadata: object = None,
) -> dict:
    part = build_resource_part(
        uri=uri,
        kind=kind,
        mime=mime,
        name=name,
        source=source,
        metadata=metadata,
    )
    return normalize_envelope({"role": role, "parts": [part]}, default_role=role)


def sanitize_event_key(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    safe = re.sub(r"[^a-zA-Z0-9_:-]", "", raw)
    return safe

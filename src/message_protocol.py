from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse


RESOURCE_KINDS = {"image", "video", "audio", "doc", "file", "url"}
PART_TYPES = {"text", "resource", "structured", "tool_call", "meta"}


@dataclass(frozen=True)
class TextPart:
    text: str

    def to_dict(self) -> dict:
        return {"type": "text", "text": self.text}


@dataclass(frozen=True)
class ResourcePart:
    resource: dict[str, Any]

    def to_dict(self) -> dict:
        return {"type": "resource", "resource": dict(self.resource)}


@dataclass(frozen=True)
class StructuredPart:
    data: Any

    def to_dict(self) -> dict:
        return {"type": "structured", "data": self.data}


@dataclass(frozen=True)
class ToolCallPart:
    payload: dict[str, Any]

    def to_dict(self) -> dict:
        return dict(self.payload)


@dataclass(frozen=True)
class MetaPart:
    meta: dict[str, Any]

    def to_dict(self) -> dict:
        return {"type": "meta", "meta": dict(self.meta)}


MessagePart = TextPart | ResourcePart | StructuredPart | ToolCallPart | MetaPart


@dataclass(frozen=True)
class MessageEnvelope:
    id: str
    role: str
    parts: tuple[MessagePart, ...]
    created_at: str
    trace_id: str = ""

    @classmethod
    def from_value(cls, value: object, default_role: str = "user") -> "MessageEnvelope":
        return cls.from_dict(normalize_envelope(value, default_role=default_role))

    @classmethod
    def from_dict(cls, envelope: dict) -> "MessageEnvelope":
        raw_parts = envelope.get("parts") if isinstance(envelope, dict) else []
        parts = tuple(_message_part_from_dict(part) for part in raw_parts if isinstance(part, dict))
        return cls(
            id=str(envelope.get("id") or uuid.uuid4().hex),
            role=str(envelope.get("role") or "user").strip().lower() or "user",
            parts=parts,
            created_at=str(envelope.get("created_at") or now_text()),
            trace_id=str(envelope.get("trace_id") or "").strip(),
        )

    def to_dict(self) -> dict:
        payload = {
            "id": self.id,
            "role": self.role,
            "parts": [part.to_dict() for part in self.parts],
            "created_at": self.created_at,
        }
        if self.trace_id:
            payload["trace_id"] = self.trace_id
        return payload


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
        if item.get("result_chars") is not None:
            payload["result_chars"] = item.get("result_chars")
        if item.get("result_preview_truncated") is not None:
            payload["result_preview_truncated"] = bool(item.get("result_preview_truncated"))
        if item.get("result_tail_preview") is not None:
            payload["result_tail_preview"] = str(item.get("result_tail_preview"))
        if item.get("result_tail_preview_truncated") is not None:
            payload["result_tail_preview_truncated"] = bool(item.get("result_tail_preview_truncated"))
        diagnostics = item.get("diagnostics")
        if isinstance(diagnostics, list):
            payload["diagnostics"] = [str(entry) for entry in diagnostics]
        sources = item.get("sources")
        if isinstance(sources, list):
            payload["sources"] = [dict(entry) for entry in sources if isinstance(entry, dict)]
        details = item.get("details")
        if isinstance(details, dict) and details:
            payload["details"] = dict(details)
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


def _message_part_from_dict(part: dict) -> MessagePart:
    normalized = _normalize_part(part)
    part_type = str(normalized.get("type") or "").strip().lower()
    if part_type == "text":
        return TextPart(text=str(normalized.get("text") or ""))
    if part_type == "resource":
        resource = normalized.get("resource")
        return ResourcePart(resource=dict(resource) if isinstance(resource, dict) else {})
    if part_type == "structured":
        return StructuredPart(data=normalized.get("data"))
    if part_type == "tool_call":
        return ToolCallPart(payload=dict(normalized))
    meta = normalized.get("meta")
    return MetaPart(meta=dict(meta) if isinstance(meta, dict) else {})


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


def normalize_message_envelope(value: object, default_role: str = "user") -> MessageEnvelope:
    return MessageEnvelope.from_value(value, default_role=default_role)


def envelope_text(value: object) -> str:
    envelope = normalize_message_envelope(value, default_role="assistant")
    output: list[str] = []
    for part in envelope.parts:
        if isinstance(part, TextPart):
            text = part.text
            if text:
                output.append(text)
            continue
        if isinstance(part, ResourcePart):
            kind = str(part.resource.get("kind") or "file")
            uri = str(part.resource.get("uri") or "").strip()
            if uri:
                output.append(f"[{kind}] {uri}")
            continue
        if isinstance(part, StructuredPart):
            data = part.data
            if data is None:
                continue
            if isinstance(data, (dict, list, tuple)):
                try:
                    output.append(json.dumps(data, ensure_ascii=False))
                except Exception:
                    output.append(str(data))
            else:
                output.append(str(data))
            continue
        if isinstance(part, ToolCallPart):
            text = _tool_call_part_text(part.payload)
            if text:
                output.append(text)
    return "\n".join([line for line in output if line]).strip()


def _tool_call_part_text(part: dict) -> str:
    name = str(part.get("name") or "tool").strip() or "tool"
    status = str(part.get("status") or "").strip()
    call_id = str(part.get("call_id") or "").strip()
    preview = str(part.get("result_preview") or "").strip()
    error = str(part.get("error") or "").strip()
    result_chars = part.get("result_chars")
    preview_truncated = bool(part.get("result_preview_truncated"))

    label_parts = [f"Tool {name}"]
    if status:
        label_parts.append(status)
    if call_id:
        label_parts.append(f"call_id={call_id}")
    label = " ".join(label_parts)

    details = []
    if isinstance(result_chars, int):
        details.append(f"result_chars={result_chars}")
    if preview_truncated:
        details.append("result_preview_truncated=true")
    suffix = f" ({', '.join(details)})" if details else ""

    if error:
        body = f"error={error}"
    elif preview_truncated:
        body = "result_preview omitted from markdown; structured history stores only a display preview"
    elif preview:
        body = f"result_preview={preview}"
    else:
        body = "result_preview=(empty)"
    return f"{label}: {body}{suffix}"


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

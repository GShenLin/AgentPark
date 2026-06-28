from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReceiverRouteResult:
    envelope: dict | None
    command_matched: bool = False


def normalize_receiver_name(value: object) -> str:
    return str(value or "").strip().lstrip("/").lower()


def parse_receiver_command(text: object) -> tuple[str, str | None] | None:
    raw = str(text or "")
    stripped = raw.lstrip()
    if not stripped.startswith("/"):
        return None
    body = stripped[1:]
    if not body:
        return None
    for index, char in enumerate(body):
        if char.isspace():
            name = body[:index].strip().lstrip("/").lower()
            remainder = body[index + 1 :].lstrip()
            if not name:
                return None
            return name, remainder if remainder else None
    name = body.strip().lstrip("/").lower()
    return (name, None) if name else None


def replace_text_part(envelope: dict, parts: list, index: int, part: dict, text: str) -> dict:
    updated_parts = [dict(item) if isinstance(item, dict) else item for item in parts]
    updated = dict(part)
    updated["text"] = text
    updated_parts[index] = updated
    matched = dict(envelope)
    matched["parts"] = updated_parts
    return matched


def envelope_receiver_command(envelope: dict) -> tuple[str, str | None] | None:
    parts = envelope.get("parts") if isinstance(envelope, dict) else None
    if not isinstance(parts, list):
        return None
    for part in parts:
        if not isinstance(part, dict):
            continue
        if str(part.get("type") or "").strip().lower() != "text":
            continue
        return parse_receiver_command(part.get("text"))
    return None


def match_receiver_name(envelope: dict, receiver_name: str) -> dict | None:
    name = normalize_receiver_name(receiver_name)
    if not name:
        return envelope
    parts = envelope.get("parts") if isinstance(envelope, dict) else None
    if not isinstance(parts, list):
        return None
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            continue
        if str(part.get("type") or "").strip().lower() != "text":
            continue
        command = parse_receiver_command(part.get("text"))
        if command is None or command[0] != name or command[1] is None:
            return None
        return replace_text_part(envelope, parts, index, part, command[1])
    return None


def route_receiver_envelope(envelope: dict, receiver_name: str, active: bool) -> ReceiverRouteResult:
    name = normalize_receiver_name(receiver_name)
    if not name:
        return ReceiverRouteResult(envelope=envelope)
    parts = envelope.get("parts") if isinstance(envelope, dict) else None
    if not isinstance(parts, list):
        return ReceiverRouteResult(envelope=None)
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            continue
        if str(part.get("type") or "").strip().lower() != "text":
            continue
        command = parse_receiver_command(part.get("text"))
        if command is not None:
            if command[0] != name:
                return ReceiverRouteResult(envelope=None)
            if command[1] is None:
                return ReceiverRouteResult(envelope=None, command_matched=True)
            matched = replace_text_part(envelope, parts, index, part, command[1])
            return ReceiverRouteResult(envelope=matched, command_matched=True)
        text = str(part.get("text") or "")
        if text.lstrip().startswith("/"):
            return ReceiverRouteResult(envelope=None)
        return ReceiverRouteResult(envelope=envelope if active else None)
    return ReceiverRouteResult(envelope=envelope if active else None)

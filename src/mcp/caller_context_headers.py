from __future__ import annotations

import base64
import binascii


CALLER_CONTEXT_ENCODING_PREFIX = "utf8b64:"


def encode_caller_header_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    payload = base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{CALLER_CONTEXT_ENCODING_PREFIX}{payload}"


def decode_caller_header_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.startswith(CALLER_CONTEXT_ENCODING_PREFIX):
        return text
    payload = text[len(CALLER_CONTEXT_ENCODING_PREFIX) :]
    if not payload:
        return ""
    padding = "=" * (-len(payload) % 4)
    try:
        return base64.urlsafe_b64decode(f"{payload}{padding}".encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid AITools caller context header encoding") from exc

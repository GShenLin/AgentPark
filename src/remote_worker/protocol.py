from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit


PROTOCOL_VERSION = 1
DISCOVERY_HOST = "127.0.0.1"
DISCOVERY_PORT = 18766
DISCOVERY_PATH = "/agentpark/discover"


class ProtocolError(ValueError):
    """Raised when a remote protocol payload violates its declared contract."""


@dataclass(frozen=True)
class RemoteTask:
    task_id: str
    tool_name: str
    arguments: dict[str, Any]
    working_path: str
    timeout_seconds: float

    @classmethod
    def from_poll_response(cls, payload: object) -> RemoteTask | None:
        root = require_object(payload, "poll response")
        if root.get("ok") is not True:
            raise ProtocolError("poll response did not report ok=true")
        task_payload = root.get("task")
        if task_payload is None:
            return None
        task = require_object(task_payload, "poll response task")
        task_id = require_non_empty_string(task.get("task_id"), "task.task_id")
        tool_name = require_non_empty_string(task.get("tool_name"), "task.tool_name")
        working_path = require_non_empty_string(task.get("working_path"), "task.working_path")
        arguments = require_object(task.get("arguments"), "task.arguments")
        timeout_seconds = require_positive_number(task.get("timeout_seconds"), "task.timeout_seconds")
        return cls(
            task_id=task_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            working_path=working_path,
            timeout_seconds=timeout_seconds,
        )


def normalize_server_origin(value: object) -> str:
    text = require_non_empty_string(value, "server_url")
    parsed = urlsplit(text)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ProtocolError("server_url must use http:// or https://")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ProtocolError("server_url must contain a valid host and no user credentials")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ProtocolError("server_url contains an invalid port") from exc
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ProtocolError("server_url must be an origin without a path, query, or fragment")
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    default_port = 80 if scheme == "http" else 443
    netloc = hostname if parsed.port in {None, default_port} else f"{hostname}:{parsed.port}"
    return urlunsplit((scheme, netloc, "", "", ""))


def origins_equal(left: object, right: object) -> bool:
    try:
        return normalize_server_origin(left) == normalize_server_origin(right)
    except ProtocolError:
        return False


def require_object(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError(f"{field_name} must be a JSON object")
    return value


def require_non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(f"{field_name} must be a non-empty string")
    return value.strip()


def require_positive_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"{field_name} must be a positive number")
    number = float(value)
    if number <= 0:
        raise ProtocolError(f"{field_name} must be a positive number")
    return number


def decode_json_object(data: bytes | str, field_name: str) -> dict[str, Any]:
    try:
        if isinstance(data, bytes):
            decoded = data.decode("utf-8")
        else:
            decoded = str(data)
        payload = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"{field_name} must be a UTF-8 JSON object") from exc
    return require_object(payload, field_name)

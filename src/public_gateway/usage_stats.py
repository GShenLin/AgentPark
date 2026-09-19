from __future__ import annotations

import json
import os
import threading
from datetime import date
from datetime import datetime
from datetime import timezone
from typing import Any

from src.providers.provider_request_usage import extract_provider_usage
from src.providers.provider_request_usage import sanitize_provider_usage


_WRITE_LOCK = threading.Lock()


class GatewayUsageStoreError(Exception):
    pass


class GatewayUsageAccumulator:
    """Extract provider-reported token usage from one public Gateway response."""

    def __init__(self, protocol: str) -> None:
        self.protocol = str(protocol or "").strip()
        self._usage: dict[str, int] = {}
        self._buffer = bytearray()

    def consume_json(self, payload: object) -> None:
        usage = _usage_from_payload(self.protocol, payload)
        if usage:
            self._usage.update(usage)

    def consume_stream_chunk(self, chunk: bytes) -> None:
        self._buffer.extend(bytes(chunk))
        while True:
            boundary = _next_sse_boundary(self._buffer)
            if boundary is None:
                return
            frame_end, separator_length = boundary
            frame = bytes(self._buffer[:frame_end])
            del self._buffer[: frame_end + separator_length]
            payload = _decode_sse_payload(frame)
            if payload is not None:
                self.consume_json(payload)

    def usage(self) -> dict[str, int]:
        return _complete_usage(self._usage)


class PublicGatewayUsageStore:
    """Append completed requests to date-partitioned JSONL and aggregate them for Settings."""

    def __init__(self, workspace_root: str) -> None:
        self.root = os.path.join(workspace_root, ".runtime", "public-gateway-usage")

    def record_completed(
        self,
        *,
        request_id: str,
        client_ip: str,
        model_id: str,
        protocol: str,
        usage: object,
        source: str = "public_gateway",
        recorded_at: datetime | None = None,
    ) -> None:
        moment = recorded_at or datetime.now().astimezone()
        if moment.tzinfo is None:
            moment = moment.astimezone()
        local_moment = moment.astimezone()
        normalized = _complete_usage(usage)
        entry: dict[str, Any] = {
            "timestamp": moment.astimezone(timezone.utc).isoformat(timespec="milliseconds"),
            "date": local_moment.date().isoformat(),
            "timezoneOffset": local_moment.strftime("%z"),
            "requestId": str(request_id),
            "clientIp": str(client_ip),
            "modelId": str(model_id),
            "protocol": str(protocol),
            "source": str(source),
            "usage": normalized or None,
        }
        path = self._path_for_date(entry["date"])
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        os.makedirs(self.root, exist_ok=True)
        with _WRITE_LOCK:
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
                handle.flush()

    def aggregate(self, date_text: str) -> dict[str, Any]:
        selected_date = _parse_date(date_text).isoformat()
        path = self._path_for_date(selected_date)
        records = self._read_records(path, selected_date)
        by_ip: dict[str, dict[str, Any]] = {}
        totals = _empty_totals()
        timezone_offset = ""
        seen_requests: set[tuple[str, str]] = set()

        for record in records:
            request_key = (
                str(record.get("source") or "public_gateway"),
                str(record.get("requestId") or ""),
            )
            if request_key[1] and request_key in seen_requests:
                continue
            if request_key[1]:
                seen_requests.add(request_key)
            client_ip = str(record.get("clientIp") or "unknown")
            model_id = str(record.get("modelId") or "unknown")
            usage = sanitize_provider_usage(record.get("usage"))
            timezone_offset = timezone_offset or str(record.get("timezoneOffset") or "")
            ip_entry = by_ip.setdefault(
                client_ip,
                {"ip": client_ip, **_empty_totals(), "models": {}},
            )
            model_entry = ip_entry["models"].setdefault(
                model_id,
                {"modelId": model_id, **_empty_totals()},
            )
            _add_request(totals, usage)
            _add_request(ip_entry, usage)
            _add_request(model_entry, usage)

        ips: list[dict[str, Any]] = []
        for ip_entry in by_ip.values():
            models = list(ip_entry.pop("models").values())
            models.sort(key=lambda item: (-item["totalTokens"], item["modelId"].lower()))
            ip_entry["models"] = models
            ips.append(ip_entry)
        ips.sort(key=lambda item: (-item["totalTokens"], item["ip"].lower()))
        return {
            "date": selected_date,
            "timezoneOffset": timezone_offset,
            "totals": totals,
            "ips": ips,
        }

    def _path_for_date(self, date_text: str) -> str:
        safe_date = _parse_date(date_text).isoformat()
        return os.path.join(self.root, f"{safe_date}.jsonl")

    @staticmethod
    def _read_records(path: str, selected_date: str) -> list[dict[str, Any]]:
        if not os.path.exists(path):
            return []
        records: list[dict[str, Any]] = []
        with _WRITE_LOCK:
            with open(path, "r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise GatewayUsageStoreError(
                            f"Invalid Gateway usage record at {path}:{line_number}."
                        ) from exc
                    if isinstance(value, dict) and value.get("date") == selected_date:
                        records.append(value)
        return records


def extract_gateway_usage(protocol: str, payload: object) -> dict[str, int]:
    accumulator = GatewayUsageAccumulator(protocol)
    accumulator.consume_json(payload)
    return accumulator.usage()


def _usage_from_payload(protocol: str, payload: object) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    raw_usage: object = None
    if protocol == "responses":
        response = payload.get("response")
        if str(payload.get("type") or "") == "response.completed" and isinstance(response, dict):
            raw_usage = response.get("usage")
        elif payload.get("object") == "response" or "usage" in payload:
            raw_usage = payload.get("usage")
    elif protocol in {"chat_completions", "images_generations", "images_edits"}:
        raw_usage = payload.get("usage")
    elif protocol == "messages":
        event_type = str(payload.get("type") or "")
        if event_type == "message_start" and isinstance(payload.get("message"), dict):
            raw_usage = payload["message"].get("usage")
        else:
            raw_usage = payload.get("usage")
        usage = _normalize_wire_usage(raw_usage)
        if event_type in {"message_start", "message_delta"}:
            usage.pop("total_tokens", None)
        return usage
    return _normalize_wire_usage(raw_usage)


def _normalize_wire_usage(raw_usage: object) -> dict[str, int]:
    if not isinstance(raw_usage, dict):
        return {}
    return extract_provider_usage({"usage": raw_usage})


def _complete_usage(value: object) -> dict[str, int]:
    usage = sanitize_provider_usage(value)
    if "total_tokens" not in usage and "input_tokens" in usage and "output_tokens" in usage:
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return usage


def _next_sse_boundary(buffer: bytearray) -> tuple[int, int] | None:
    candidates = []
    for separator in (b"\n\n", b"\r\n\r\n"):
        index = buffer.find(separator)
        if index >= 0:
            candidates.append((index, len(separator)))
    return min(candidates, default=None, key=lambda item: item[0])


def _decode_sse_payload(frame: bytes) -> dict[str, Any] | None:
    data_lines = []
    for raw_line in frame.splitlines():
        line = raw_line.strip()
        if line.startswith(b"data:"):
            data_lines.append(line[5:].lstrip())
    raw = b"\n".join(data_lines)
    if not raw or raw == b"[DONE]":
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _empty_totals() -> dict[str, int]:
    return {
        "requestCount": 0,
        "usageRequestCount": 0,
        "missingUsageRequestCount": 0,
        "inputTokens": 0,
        "outputTokens": 0,
        "totalTokens": 0,
        "cachedInputTokens": 0,
        "cacheWriteInputTokens": 0,
        "reasoningOutputTokens": 0,
    }


def _add_request(target: dict[str, Any], usage: dict[str, int]) -> None:
    target["requestCount"] += 1
    if not usage:
        target["missingUsageRequestCount"] += 1
        return
    target["usageRequestCount"] += 1
    for source, destination in (
        ("input_tokens", "inputTokens"),
        ("output_tokens", "outputTokens"),
        ("total_tokens", "totalTokens"),
        ("cached_input_tokens", "cachedInputTokens"),
        ("cache_write_input_tokens", "cacheWriteInputTokens"),
        ("reasoning_output_tokens", "reasoningOutputTokens"),
    ):
        target[destination] += usage.get(source, 0)


def _parse_date(value: str) -> date:
    text = str(value or "").strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("Gateway usage date must use YYYY-MM-DD format.") from exc
    if parsed.isoformat() != text:
        raise ValueError("Gateway usage date must use YYYY-MM-DD format.")
    return parsed


__all__ = [
    "GatewayUsageAccumulator",
    "GatewayUsageStoreError",
    "PublicGatewayUsageStore",
    "extract_gateway_usage",
]

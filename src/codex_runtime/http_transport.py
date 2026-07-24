from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass
from itertools import chain
from typing import Any, BinaryIO, Iterable, Iterator

from src.providers.curl_transport import CurlHttpTransport
from src.providers.curl_transport import CurlResponse
from src.providers.curl_transport import CurlTransportError


class UpstreamHttpError(RuntimeError):
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status = int(status)
        self.body = bytes(body)
        self.headers = dict(headers or {})
        text = self.body.decode("utf-8", errors="replace")
        super().__init__(f"Upstream HTTP {self.status}: {text}")


class UpstreamTransportError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpstreamRequestPolicy:
    timeout_seconds: float
    max_retries: int
    retry_delay_seconds: float


@dataclass
class UpstreamResponse:
    status: int
    headers: dict[str, str]
    body: BinaryIO

    def close(self) -> None:
        self.body.close()


class _StreamingBody:
    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._chunks = iter(chunks)
        self._buffer = bytearray()
        self._closed = False

    def readline(self) -> bytes:
        if self._closed:
            return b""
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                end = newline + 1
                line = bytes(self._buffer[:end])
                del self._buffer[:end]
                return line
            try:
                self._buffer.extend(next(self._chunks))
            except StopIteration:
                if not self._buffer:
                    return b""
                line = bytes(self._buffer)
                self._buffer.clear()
                return line

    def read(self) -> bytes:
        if self._closed:
            return b""
        output = bytearray(self._buffer)
        self._buffer.clear()
        for chunk in self._chunks:
            output.extend(chunk)
        return bytes(output)

    def close(self) -> None:
        self._closed = True
        self._buffer.clear()
        closer = getattr(self._chunks, "close", None)
        if callable(closer):
            closer()


_CURL = CurlHttpTransport()


def resolve_upstream_request_policy(config: dict[str, Any]) -> UpstreamRequestPolicy:
    try:
        timeout_seconds = float(config.get("timeoutMs", 60000)) / 1000.0
    except (TypeError, ValueError):
        timeout_seconds = 60.0
    try:
        max_retries = int(config.get("maxRetries", 3))
    except (TypeError, ValueError):
        max_retries = 3
    try:
        retry_delay_seconds = float(config.get("retryDelaySec", 1))
    except (TypeError, ValueError):
        retry_delay_seconds = 1.0
    return UpstreamRequestPolicy(
        timeout_seconds=max(1.0, timeout_seconds),
        max_retries=max(0, max_retries),
        retry_delay_seconds=max(0.0, retry_delay_seconds),
    )


def open_json_request(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    policy: UpstreamRequestPolicy,
    stream: bool,
) -> UpstreamResponse:
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    request_headers = {"Content-Type": "application/json", "Accept": "text/event-stream, application/json"}
    request_headers.update(headers)
    if stream:
        chunks = iter(_stream_with_retry(
            url=url,
            headers=request_headers,
            payload_json=payload_json,
            policy=policy,
        ))
        try:
            first_chunk = next(chunks)
        except StopIteration:
            framed_chunks: Iterable[bytes] = ()
        else:
            framed_chunks = chain((first_chunk,), chunks)
        body = _StreamingBody(framed_chunks)
        return UpstreamResponse(status=200, headers={"content-type": "text/event-stream"}, body=body)  # type: ignore[arg-type]
    response = _post_with_retry(
        url=url,
        headers=request_headers,
        payload_json=payload_json,
        policy=policy,
    )
    return UpstreamResponse(
        status=response.status_code,
        headers=dict(response.headers),
        body=io.BytesIO(response.body.encode("utf-8")),
    )


def _post_with_retry(
    *,
    url: str,
    headers: dict[str, str],
    payload_json: str,
    policy: UpstreamRequestPolicy,
) -> CurlResponse:
    retry_attempt = 0
    while True:
        try:
            response = _CURL.post_json_response(
                url=url,
                headers=headers,
                payload_json=payload_json,
                timeout_sec=policy.timeout_seconds,
            )
        except CurlTransportError as exc:
            if retry_attempt < policy.max_retries:
                retry_attempt += 1
                _retry_delay(policy.retry_delay_seconds)
                continue
            raise _transport_error(exc, retry_attempt + 1) from exc
        if _http_status_retryable(response.status_code) and retry_attempt < policy.max_retries:
            retry_attempt += 1
            _retry_delay(policy.retry_delay_seconds)
            continue
        if response.status_code < 200 or response.status_code >= 300:
            raise UpstreamHttpError(
                response.status_code,
                response.body.encode("utf-8"),
                response.headers,
            )
        return response


def _stream_with_retry(
    *,
    url: str,
    headers: dict[str, str],
    payload_json: str,
    policy: UpstreamRequestPolicy,
) -> Iterator[bytes]:
    retry_attempt = 0
    while True:
        emitted = False
        try:
            for item in _CURL.stream_sse_data(
                url=url,
                headers=headers,
                payload_json=payload_json,
                timeout_sec=policy.timeout_seconds,
            ):
                if isinstance(item, CurlResponse):
                    if item.status_code < 200 or item.status_code >= 300:
                        raise UpstreamHttpError(
                            item.status_code,
                            item.body.encode("utf-8"),
                            item.headers,
                        )
                    return
                emitted = True
                yield _sse_frame(item)
            return
        except UpstreamHttpError as exc:
            if not emitted and _http_status_retryable(exc.status) and retry_attempt < policy.max_retries:
                retry_attempt += 1
                _retry_delay(policy.retry_delay_seconds)
                continue
            raise
        except CurlTransportError as exc:
            if not emitted and retry_attempt < policy.max_retries:
                retry_attempt += 1
                _retry_delay(policy.retry_delay_seconds)
                continue
            raise _transport_error(exc, retry_attempt + 1) from exc


def _sse_frame(data: str) -> bytes:
    event_type = ""
    try:
        payload = json.loads(data)
        if isinstance(payload, dict):
            event_type = str(payload.get("type") or "").strip()
    except json.JSONDecodeError:
        pass
    event_line = f"event: {event_type}\n" if event_type else ""
    return f"{event_line}data: {data}\n\n".encode("utf-8")


def _http_status_retryable(status: int) -> bool:
    code = int(status or 0)
    return code == 429 or code >= 500


def _retry_delay(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _transport_error(error: Exception, attempts: int) -> UpstreamTransportError:
    suffix = "s" if attempts != 1 else ""
    return UpstreamTransportError(f"Upstream curl request failed after {attempts} attempt{suffix}: {error}")


def read_json_response(response: UpstreamResponse) -> dict[str, Any]:
    try:
        raw = response.body.read()
    finally:
        response.close()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Upstream response is not valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Upstream JSON response must be an object.")
    return value


def iter_sse_data(response: UpstreamResponse):
    try:
        data_lines: list[str] = []
        while True:
            raw = response.body.readline()
            if not raw:
                if data_lines:
                    yield "\n".join(data_lines)
                return
            line = raw.decode("utf-8", errors="strict").rstrip("\r\n")
            if not line:
                if data_lines:
                    yield "\n".join(data_lines)
                    data_lines.clear()
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
    finally:
        response.close()


def copy_response_lines(response: UpstreamResponse):
    try:
        while True:
            line = response.body.readline()
            if not line:
                return
            yield line
    finally:
        response.close()

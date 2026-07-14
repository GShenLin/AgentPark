from __future__ import annotations

import json
from typing import Any

from src.provider_limit_schema import ProbeResult
from src.providers.curl_transport import CurlHttpTransport, CurlTransportError


class _ProviderLimitCurl(CurlHttpTransport):
    pass


_CURL = _ProviderLimitCurl()


def post_json_probe(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
) -> ProbeResult:
    payload_json = json.dumps(payload, ensure_ascii=False)
    try:
        response = _CURL._curl_post_once_raw(
            url=url,
            headers=headers,
            payload_json=payload_json,
            timeout_sec=timeout_seconds,
            marker="__PROVIDER_LIMIT_HTTP_CODE__:",
        )
        if response.status_code < 200 or response.status_code >= 300:
            return ProbeResult(
                False,
                sanitize_probe_error(f"HTTP {response.status_code}: {response.body}", headers=headers),
                status_code=response.status_code,
                outcome=_http_error_outcome(response.status_code),
            )
        try:
            _ = json.loads(response.body) if response.body.strip() else {}
        except Exception as exc:
            if payload.get("stream") is True and _looks_like_sse_response(response.body):
                return ProbeResult(True, status_code=response.status_code)
            return ProbeResult(
                False,
                sanitize_probe_error(f"Invalid JSON response: {exc}; body={response.body[:500]}", headers=headers),
                status_code=response.status_code,
                outcome="invalid_response",
            )
        return ProbeResult(True, status_code=response.status_code)
    except CurlTransportError as exc:
        return ProbeResult(
            False,
            sanitize_probe_error(f"curl: {exc}", headers=headers),
            outcome="unreachable",
        )
    except Exception as exc:
        return ProbeResult(
            False,
            sanitize_probe_error(f"{type(exc).__name__}: {exc}", headers=headers),
            outcome="error",
        )


def _http_error_outcome(status_code: int) -> str:
    if status_code == 400 or status_code == 404 or status_code == 405 or status_code == 422:
        return "unsupported"
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "provider_error"
    return "error"


def _looks_like_sse_response(body: str) -> bool:
    text = str(body or "").lstrip()
    return text.startswith("event:") or text.startswith("data:")


def sanitize_probe_error(text: str, *, headers: dict[str, str]) -> str:
    output = str(text or "").strip()
    auth = str((headers or {}).get("Authorization") or "")
    if auth.startswith("Bearer "):
        token = auth.removeprefix("Bearer ").strip()
        if token:
            output = output.replace(token, "<redacted>")
    for header_name in ("x-goog-api-key", "x-api-key"):
        api_key = str((headers or {}).get(header_name) or "")
        if api_key:
            output = output.replace(api_key, "<redacted>")
    return output[:1200]

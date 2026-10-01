"""Resolve the user-selected host using the explicit runtime-first contract."""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.providers.curl_transport import CurlHttpTransport, CurlTransportError, CurlHttpError

from .protocol import normalize_server_origin


@dataclass(frozen=True)
class RegistrationEndpoint:
    kind: str
    origin: str


def resolve_endpoint(address: str, transport=None) -> RegistrationEndpoint:
    address = address.strip()
    if not address:
        raise ValueError("请填写服务器地址。")
    explicit = "://" in address
    normalize_server_origin(address if explicit else "http://" + address)
    parsed = urlsplit(address if explicit else "http://" + address)
    if not parsed.hostname:
        raise ValueError("服务器地址缺少主机名或 IP。")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    # A complete URL explicitly selects the runtime port; a host/IP uses 8788.
    runtime = normalize_server_origin(address if explicit else f"http://{host}:{parsed.port or 8788}")
    coordinator = normalize_server_origin(f"https://{host}")
    client = transport or CurlHttpTransport()

    def probe(origin):
        response = client.request(url=origin + "/api/remote-workers/service", timeout_sec=4,
                                  connect_timeout=3, follow_redirects=False, max_response_bytes=8192,
                                  revocation_best_effort=True)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = json.loads(response.content)
        if not isinstance(payload, dict) or set(payload) != {"service", "remote_protocol"}:
            raise ValueError(f"{origin} 返回了无效的 Remote 服务声明。")
        if payload["remote_protocol"] != 2:
            raise ValueError(f"{origin} 的 Remote 协议版本不受支持。")
        return payload["service"]

    try:
        service = probe(runtime)
    except CurlHttpError:
        raise
    except CurlTransportError:
        # The configured policy explicitly falls back when 8788 is unreachable.
        # HTTP authorization errors and malformed protocol replies are not retried
        # against another service.
        service = None
    if service == "agentpark-runtime":
        return RegistrationEndpoint("runtime", runtime)
    if service == "agentpark-coordinator":
        return RegistrationEndpoint("coordinator", runtime)
    if service is not None:
        raise ValueError(f"{runtime} 不是受支持的 AgentPark 服务。")
    if probe(coordinator) != "agentpark-coordinator":
        raise ValueError("8788 未提供 Remote 登记服务，鉴权中心也未提供 Remote 设备目录；请更新目标服务。")
    return RegistrationEndpoint("coordinator", coordinator)

from __future__ import annotations

import ipaddress

from fastapi import Request


def is_local_request(request: Request | None = None) -> bool:
    if request is None:
        return True
    client = getattr(request, "client", None)
    host = str(getattr(client, "host", "") or "").strip()
    if host.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    return bool(address.version == 6 and address.ipv4_mapped is not None and address.ipv4_mapped.is_loopback)


__all__ = ["is_local_request"]

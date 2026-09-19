from __future__ import annotations

import ipaddress

from fastapi import Request
from src.peer_network.principal import CloudBoardAdministrator


def is_cloud_board_administrator(request: Request | None) -> bool:
    return isinstance(getattr(getattr(request, "state", None), "peer_principal", None), CloudBoardAdministrator)


def has_owner_access(request: Request | None = None) -> bool:
    """Owner privileges are separate from the physical origin of a request."""
    return is_cloud_board_administrator(request) or is_local_request(request)


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


__all__ = ["is_local_request", "has_owner_access", "is_cloud_board_administrator"]

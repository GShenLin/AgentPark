import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.peer_network.connections import Link, PeerConnections
from src.peer_network.identity import DeviceIdentity, verify_signal
from src.peer_network.portal_ice import PORTAL_SIGNAL, PortalIceCandidate, PortalIceOrder


def identity():
    return DeviceIdentity(Ed25519PrivateKey.generate())


def candidate(sender, target, sequence=0, value="candidate:1 1 UDP 1 192.0.2.1 5000 typ host", session="a" * 32):
    body = dict(kind="ice_candidate", session_id=session, target=target, public_key=sender.public_key,
                expires_at=int(time.time()) + 60, sequence=sequence, candidate=value,
                sdp_mid="0" if value else None, sdp_mline_index=0 if value else None)
    return {**body, "signature": sender.sign(body)}


def test_candidate_signature_covers_address_session_and_sequence():
    browser, device = identity(), identity()
    payload = candidate(browser, device.peer_id)
    parsed = PORTAL_SIGNAL.validate_python(payload)
    assert verify_signal(parsed, device.peer_id) == browser.peer_id
    from cryptography.exceptions import InvalidSignature
    for key, value in {"sequence": 1, "candidate": "candidate:1 1 UDP 1 192.0.2.2 5000 typ host", "session_id": "b" * 32}.items():
        with pytest.raises(InvalidSignature):
            verify_signal(PORTAL_SIGNAL.validate_python({**payload, key: value}), device.peer_id)


def test_order_requires_offer_same_session_and_exactly_once_completion():
    browser, device = identity(), identity()
    order = PortalIceOrder()
    first = PORTAL_SIGNAL.validate_python(candidate(browser, device.peer_id))
    with pytest.raises(ValueError, match="session"):
        order.accept(first)
    order.accept(PORTAL_SIGNAL.validate_python(browser.signal("offer", device.peer_id, "a" * 32, "offer")))
    with pytest.raises(ValueError, match="session"):
        order.accept(PORTAL_SIGNAL.validate_python(candidate(browser, device.peer_id, session="b" * 32)))
    order.accept(first)
    with pytest.raises(ValueError, match="order"):
        order.accept(first)
    order.accept(PORTAL_SIGNAL.validate_python(candidate(browser, device.peer_id, 1, None)))
    with pytest.raises(ValueError, match="order"):
        order.accept(PORTAL_SIGNAL.validate_python(candidate(browser, device.peer_id, 2)))


@pytest.mark.parametrize("changes", [
    {"candidate": "bad"}, {"candidate": "candidate:a\r\nb"}, {"sdp_mid": None, "sdp_mline_index": None},
    {"sequence": 129}, {"sequence": True}, {"candidate": None}, {"unexpected": 1},
])
def test_candidate_contract_rejects_invalid_payload(changes):
    with pytest.raises(ValueError):
        PortalIceCandidate.model_validate({**candidate(identity(), "b" * 64), **changes})


def test_device_applies_late_candidates_only_to_admitted_portal_connection():
    async def scenario():
        browser, device = identity(), identity()
        connections = PeerConnections(SimpleNamespace(identity=device))
        payload = candidate(browser, device.peer_id)
        with pytest.raises(ValueError, match="admitted"):
            await connections.accept(payload, portal=True)
        pc = SimpleNamespace(addIceCandidate=AsyncMock())
        order = PortalIceOrder()
        order.accept(PORTAL_SIGNAL.validate_python(browser.signal("offer", device.peer_id, "a" * 32, "offer")))
        connections.links[browser.peer_id] = Link("a" * 32, pc, time.monotonic(), portal=True, portal_ice=order)
        await connections.accept(payload, portal=True)
        c = pc.addIceCandidate.call_args.args[0]
        assert (c.ip, c.sdpMid, c.sdpMLineIndex) == ("192.0.2.1", "0", 0)
        await connections.accept(candidate(browser, device.peer_id, 1, None), portal=True)
        assert pc.addIceCandidate.call_args.args == (None,)
        with pytest.raises(ValueError, match="order"):
            await connections.accept(payload, portal=True)
    asyncio.run(scenario())

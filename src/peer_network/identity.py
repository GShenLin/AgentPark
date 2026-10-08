from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from src.file_transaction import atomic_write_text

from .contracts import Signal
from .portal_ice import PortalIceCandidate


SIGNAL_TTL_SECONDS = 120
# Only the future bound permits clock skew. Expired signals remain invalid.
SIGNAL_CLOCK_SKEW_SECONDS = 5


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def peer_id(public_key: str) -> str:
    raw = base64.b64decode(public_key, validate=True)
    if len(raw) != 32:
        raise ValueError("Invalid device public key.")
    return hashlib.sha256(raw).hexdigest()


def verify(public_key: str, signature: str, payload: dict) -> None:
    Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True)).verify(
        base64.b64decode(signature, validate=True), canonical(payload)
    )


class DeviceIdentity:
    def __init__(self, key: Ed25519PrivateKey):
        self.key = key
        self.public_key = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode("ascii")
        self.peer_id = peer_id(self.public_key)

    @classmethod
    def load(cls, path: Path) -> DeviceIdentity:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if set(data) != {"private_key"}:
                raise ValueError("Invalid device identity file.")
            return cls(Ed25519PrivateKey.from_private_bytes(base64.b64decode(data["private_key"], validate=True)))
        identity = cls(Ed25519PrivateKey.generate())
        private = identity.key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        atomic_write_text(str(path), json.dumps({"private_key": base64.b64encode(private).decode("ascii")}))
        path.chmod(0o600)
        return identity

    def sign(self, payload: dict) -> str:
        return base64.b64encode(self.key.sign(canonical(payload))).decode("ascii")

    def signal(self, kind: str, target: str, session_id: str, sdp: str = "") -> dict:
        body = dict(kind=kind, target=target, session_id=session_id, sdp=sdp,
                    public_key=self.public_key, expires_at=int(time.time()) + SIGNAL_TTL_SECONDS)
        return Signal(**body, signature=self.sign(body)).model_dump()


def verify_signal(signal: Signal | PortalIceCandidate, target: str) -> str:
    if signal.target != target or not 0 < signal.expires_at - time.time() <= SIGNAL_TTL_SECONDS + SIGNAL_CLOCK_SKEW_SECONDS:
        raise ValueError("Signal target or expiry is invalid.")
    verify(signal.public_key, signal.signature, signal.model_dump(exclude={"signature"}))
    return peer_id(signal.public_key)

"""Run the coordination-only service: python -m src.peer_network.signaling.

The service never receives data-channel frames or implements TURN/HTTP proxying.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from cryptography.exceptions import InvalidSignature
from pydantic import ValidationError

from .contracts import NetworkSettings, Signal
from .identity import DeviceIdentity, peer_id, verify, verify_signal
from .coordinator_registry import CoordinatorRegistry, DeviceConnection
from .portal_routes import register_portal_routes
from .enrollment import DeviceAdmissions, register_enrollment_routes
from .ice import TurnIssuer
from .remote_contracts import validate_descriptors


def create_signaling_app(*, max_devices: int = 100, portal_password: str = "",
                         web_root: Path | None = None, signing_identity: DeviceIdentity | None = None,
                         admissions: DeviceAdmissions | None = None, turn: TurnIssuer | None = None) -> FastAPI:
    admissions = admissions or DeviceAdmissions()
    registry = CoordinatorRegistry()
    turn = turn or TurnIssuer()
    devices = registry.devices
    signing_identity = signing_identity or DeviceIdentity(Ed25519PrivateKey.generate())

    @asynccontextmanager
    async def lifespan(app):
        yield
        for device in list(devices.values()):
            await device.socket.close(code=1001)
        for socket in list(registry.browsers.values()):
            await socket.close(code=1001)

    app = FastAPI(title="AgentPark connection coordinator", lifespan=lifespan, docs_url=None, redoc_url=None)
    auth = register_portal_routes(app, registry, signing_identity, portal_password, web_root, turn)
    register_enrollment_routes(app, auth, admissions)
    send = registry.send_device
    handshakes = set()

    @app.get("/api/remote-workers/service")
    def remote_service():
        return {"service": "agentpark-coordinator", "remote_protocol": 2}

    @app.websocket("/connect")
    async def connect(socket: WebSocket):
        if socket.headers.get("origin") or len(handshakes) >= 100 or len(devices) >= max_devices:
            await socket.close(code=1008)
            return
        handshakes.add(socket)
        device = None
        try:
            await socket.accept()
            challenge = secrets.token_hex(32)
            await socket.send_json({"kind": "challenge", "challenge": challenge})
            raw = await asyncio.wait_for(socket.receive_text(), 10)
            if len(raw) > 2048:
                raise ValueError("Identity proof is too large.")
            proof = json.loads(raw)
            if set(proof) != {"public_key", "signature", "display_name", "portal_board", "stun_urls"}:
                raise ValueError("Invalid identity proof.")
            if not isinstance(proof["display_name"], str) or not 1 <= len(proof["display_name"]) <= 100 or not isinstance(proof["portal_board"], bool):
                raise ValueError("Invalid device metadata.")
            verify(proof["public_key"], proof["signature"], {"challenge": challenge,
                   "display_name": proof["display_name"], "portal_board": proof["portal_board"], "stun_urls": proof["stun_urls"]})
            NetworkSettings(stun_urls=proof["stun_urls"])
            device = peer_id(proof["public_key"])
            state = admissions.request(device, proof["display_name"], socket.client.host)
            if state != "approved":
                await socket.send_json({"kind": "enrollment", "state": state, "peer_id": device})
                await socket.close(code=1000)
                return
            if device in devices or len(devices) >= max_devices:
                raise ValueError("Device is already connected or server is full.")
            devices[device] = DeviceConnection(socket, proof["display_name"], proof["portal_board"], proof["stun_urls"])
            await send(device, {"kind": "ready", "peer_id": device, "coordinator_public_key": signing_identity.public_key,
                                "ice": turn.issue(device).model_dump()})
            handshakes.discard(socket)
            window, count = time.monotonic(), 0
            while True:
                raw = await socket.receive_text()
                if len(raw.encode("utf-8")) > 70000:
                    raise ValueError("Signal is too large.")
                if time.monotonic() - window > 60:
                    window, count = time.monotonic(), 0
                count += 1
                if count > 120:
                    raise ValueError("Signaling rate limit exceeded.")
                packet = json.loads(raw)
                if packet.get("kind") == "remote_publish":
                    if set(packet) != {"kind", "remote_workers"}:
                        raise ValueError("Invalid remote publication.")
                    devices[device].remote_workers = validate_descriptors(packet["remote_workers"])
                    devices[device].remote_directory_enabled = True
                    await registry.publish_remote_directory()
                    continue
                if packet == {"kind": "ice_refresh"}:
                    await send(device, {"kind": "ice", "ice": turn.issue(device).model_dump()})
                    continue
                signal = Signal.model_validate(packet)
                sender = verify_signal(signal, signal.target)
                if sender != device or signal.target == device:
                    raise ValueError("Signal sender does not match registered identity.")
                if signal.target in registry.browsers:
                    if signal.kind != "answer" or registry.browser_targets.get(signal.target) != device:
                        raise ValueError("Device is not serving this browser Board.")
                    await registry.send_browser(signal.target, {"kind": "signal", "signal": signal.model_dump()})
                elif signal.target not in devices:
                    await send(device, {"kind": "unavailable", "peer_id": signal.target})
                else:
                    await send(signal.target, {"kind": "signal", "signal": signal.model_dump()})
        except WebSocketDisconnect:
            pass
        except (ValueError, TypeError, KeyError, InvalidSignature, ValidationError, asyncio.TimeoutError):
            await socket.close(code=1008)
        finally:
            handshakes.discard(socket)
            if device is not None and device in devices and devices[device].socket is socket:
                devices.pop(device)
                await registry.publish_remote_directory()

    return app


def main() -> None:
    import uvicorn
    identity_root = Path(os.environ.get("AGENTPARK_SIGNALING_STATE", ".auth/coordinator"))
    app = create_signaling_app(portal_password=os.environ.get("AGENTPARK_PORTAL_PASSWORD", ""),
                              admissions=DeviceAdmissions(identity_root / "devices.json"),
                              web_root=Path(os.environ.get("AGENTPARK_PORTAL_WEB_ROOT", "webui/dist")),
                              signing_identity=DeviceIdentity.load(identity_root / "identity.json"),
                              turn=TurnIssuer.from_environment())
    # Terminate WSS at the deployment's HTTPS server; bind locally by default.
    uvicorn.run(app, host=os.environ.get("AGENTPARK_SIGNALING_HOST", "127.0.0.1"),
                port=int(os.environ.get("AGENTPARK_SIGNALING_PORT", "8790")), ws_max_size=70000)


if __name__ == "__main__":
    main()

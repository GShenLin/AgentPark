"""Read-only live Board probe, including forced TURN with real encrypted RPC.

Run from the repository with the device runtime dependencies installed. Secrets
are prompted for, held in memory, and never included in the report.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import tempfile
import json
from pathlib import Path
import ssl
import sys
import uuid
from contextlib import nullcontext
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from websockets.asyncio.client import connect

from src.providers.curl_transport import CurlHttpTransport
from src.peer_network.channel import PeerChannel
from src.peer_network.contracts import BoardHttpRequest, PeerCall, Signal
from src.peer_network.ice import IceLease
from src.peer_network.identity import DeviceIdentity, verify_signal


class PortalProbe:
    def __init__(self, origin: str, password: str):
        self.origin = origin.rstrip("/")
        self.cookie_dir = tempfile.TemporaryDirectory(prefix="agentpark-probe-")
        self.cookie_file = str(Path(self.cookie_dir.name) / "cookies")
        self.request("/portal/api/login", {"password": password})

    def request(self, path: str, body=None):
        response = CurlHttpTransport().request(url=self.origin + path,
            method="POST" if body is not None else "GET",
            body=json.dumps(body).encode() if body is not None else None,
            headers={"Origin": self.origin, "Content-Type": "application/json"},
            timeout_sec=20, cookie_file=self.cookie_file).raise_for_status()
        return response.json() if response.content else None

    async def board(self, device: dict, transport: str | None = None) -> dict:
        identity = DeviceIdentity(Ed25519PrivateKey.generate())
        cookie = CurlHttpTransport.cookie_header(self.cookie_file, self.origin + "/portal/connect")
        async with connect(self.origin.replace("https://", "wss://") + "/portal/connect",
                           origin=self.origin, additional_headers={"Cookie": cookie}, max_size=100000) as ws:
            challenge = json.loads(await ws.recv())
            await ws.send(json.dumps({"public_key": identity.public_key,
                                     "signature": identity.sign({"challenge": challenge["challenge"]})}))
            ready = json.loads(await ws.recv())
            assert ready["kind"] == "ready" and ready["peer_id"] == identity.peer_id
            lease = IceLease.model_validate(ready["ice"])
            lease.require_fresh()
            servers = [] if transport else [RTCIceServer(urls=url) for url in device["stun_urls"]]
            for server in lease.ice_servers:
                urls = [url for url in server.urls if not transport or url.endswith("transport=" + transport)]
                if urls:
                    servers.append(RTCIceServer(urls=urls, username=server.username, credential=server.credential))
            if transport and not servers:
                raise RuntimeError("The coordinator did not issue the requested TURN transport.")
            pc = RTCPeerConnection(RTCConfiguration(iceServers=servers))
            async def deny(call):
                raise PermissionError("Probe does not expose any operations.")
            rpc = PeerChannel(pc.createDataChannel("agentpark.v1", ordered=True), deny)
            ice = pc.sctp.transport.transport._connection
            # Diagnostic isolation only: aiortc does not expose relay-only policy.
            # Gather with no host interfaces, so no direct sockets are created.
            # Closing host sockets after gathering incorrectly terminates DTLS.
            try:
                async with asyncio.timeout(45):
                    with patch("aioice.ice.get_host_addresses", return_value=[]) if transport else nullcontext():
                        await pc.setLocalDescription(await pc.createOffer())
                    if transport:
                        assert ice.local_candidates and all(c.type == "relay" for c in ice.local_candidates), "No TURN allocation obtained."
                    session = uuid.uuid4().hex
                    await ws.send(json.dumps(identity.signal("offer", device["peer_id"], session, pc.localDescription.sdp)))
                    packet = json.loads(await ws.recv())
                    assert packet["kind"] == "signal", "Coordinator rejected the Board offer."
                    answer = Signal.model_validate(packet["signal"])
                    assert verify_signal(answer, identity.peer_id) == device["peer_id"] and answer.session_id == session
                    sdp = answer.sdp
                    if transport:
                        sdp = "\r\n".join(line for line in sdp.splitlines() if not line.startswith("a=candidate:") or " typ relay " in line) + "\r\n"
                        assert " typ relay " in sdp, "The target device has no TURN candidate."
                    await pc.setRemoteDescription(RTCSessionDescription(type="answer", sdp=sdp))
                    await rpc.ready.wait()
                    pairs = list(ice._nominated.values())
                    assert pairs
                    relayed = any(p.local_candidate.type == "relay" or p.remote_candidate.type == "relay" for p in pairs)
                    if transport:
                        assert all(p.local_candidate.type == p.remote_candidate.type == "relay" for p in pairs)
                    results = {}
                    for path in ("/api/system/status", "/api/access/status", "/api/graphs"):
                        reply = await rpc.call(PeerCall(operation="board_http", http=BoardHttpRequest(method="GET", path=path)))
                        assert reply["status"] == 200, f"Board HTTP request failed: {path}"
                        body = base64.b64decode(reply["body"])
                        results[path] = len(body)
                        if path == "/api/access/status":
                            assert json.loads(body)["is_developer"] is True
                    return {"requested": transport or "automatic", "selected": "relay" if relayed else "direct",
                            "local_candidate": pairs[0].local_candidate.type, "remote_candidate": pairs[0].remote_candidate.type,
                            "board_http_bytes": results, "administrator_access": True}
            finally:
                rpc.close()
                await pc.close()

    def close(self):
        self.request("/portal/api/logout", {})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--portal-url", required=True)
    parser.add_argument("--device-name", required=True)
    args = parser.parse_args()
    probe = PortalProbe(args.portal_url, getpass.getpass("Portal administrator password: "))
    try:
        devices = probe.request("/portal/api/devices")["devices"]
        matches = [device for device in devices if device["name"] == args.device_name]
        if len(matches) != 1:
            raise ValueError("Expected exactly one online device with this name.")
        for transport in (None, "tcp", "udp"):
            print(json.dumps(asyncio.run(probe.board(matches[0], transport))), flush=True)
    finally:
        probe.close()


if __name__ == "__main__":
    main()

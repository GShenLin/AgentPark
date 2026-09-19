"""Run on ECS as root. Restart signaling after the probe to reload cleaned state."""
import asyncio
import http.cookiejar
import json
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from websockets.asyncio.client import connect

from src.file_transaction import atomic_write_text
from src.peer_network.identity import DeviceIdentity


async def main():
    env = dict(line.split("=", 1) for line in Path("/etc/agentpark/signaling.env").read_text().splitlines() if "=" in line)
    base = "http://127.0.0.1:8790"
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(path, body=None, method=None):
        return opener.open(urllib.request.Request(base + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Origin": base, "Content-Type": "application/json"}), timeout=5)

    try:
        request("/portal/api/enrollments")
        raise AssertionError("Anonymous enrollment listing was accepted")
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
    assert request("/portal/api/login", {"password": env["AGENTPARK_PORTAL_PASSWORD"]}).status == 204
    initial = json.load(request("/portal/api/devices"))["devices"]
    identity = DeviceIdentity(Ed25519PrivateKey.generate())

    async def identify(ws):
        challenge = json.loads(await ws.recv())["challenge"]
        metadata = {"display_name": "Deployment enrollment probe", "portal_board": False, "stun_urls": ["stun:203.0.113.10:3478"]}
        await ws.send(json.dumps({"public_key": identity.public_key, **metadata,
            "signature": identity.sign({"challenge": challenge, **metadata})}))
        return json.loads(await ws.recv())

    try:
        async with connect("ws://127.0.0.1:8790/connect") as ws:
            assert (await identify(ws))["state"] == "pending"
        assert not any(row["peer_id"] == identity.peer_id for row in json.load(request("/portal/api/devices"))["devices"])
        rows = json.load(request("/portal/api/enrollments"))["devices"]
        assert any(row["peer_id"] == identity.peer_id and row["state"] == "pending" for row in rows)
        assert request("/portal/api/enrollments/" + identity.peer_id, {"state": "approved"}, "PUT").status == 200
        async with connect("ws://127.0.0.1:8790/connect") as ws:
            assert (await identify(ws))["kind"] == "ready"
            assert any(row["peer_id"] == identity.peer_id for row in json.load(request("/portal/api/devices"))["devices"])
        await asyncio.sleep(.1)
        assert not any(row["peer_id"] == identity.peer_id for row in json.load(request("/portal/api/devices"))["devices"])
        print(json.dumps({"anonymous_denied": True, "pending_is_not_online": True, "admin_approval": True,
                          "signed_device_registration": True, "disconnect_removed": True, "real_online_devices": len(initial)}))
    finally:
        # Remove only this ephemeral probe identity. Service restart reloads the file.
        path = Path("/var/lib/agentpark-signaling/devices.json")
        if path.exists():
            records = json.loads(path.read_text())
            filtered = [row for row in records if row["peer_id"] != identity.peer_id]
            atomic_write_text(str(path), json.dumps(filtered, ensure_ascii=False))
            path.chmod(0o600)


asyncio.run(main())

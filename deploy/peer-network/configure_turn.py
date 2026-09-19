"""Run on the server as root. Keep the TURN shared secret on the server only."""
from __future__ import annotations

import argparse
import grp
import ipaddress
import json
import os
from pathlib import Path
import secrets
import tempfile


def write_private(path: Path, text: str, group: int, mode: int) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, 0, group)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-ip", required=True)
    parser.add_argument("--private-ip", required=True)
    args = parser.parse_args()
    public = ipaddress.IPv4Address(args.public_ip)
    private = ipaddress.IPv4Address(args.private_ip)
    if not public.is_global or private.is_loopback or private.is_unspecified:
        raise ValueError("Provide the public IPv4 and the server's relay interface IPv4.")
    environment = Path("/etc/agentpark/signaling.env")
    lines = environment.read_text(encoding="utf-8").splitlines()
    existing = [line.partition("=")[2] for line in lines if line.startswith("AGENTPARK_TURN_SECRET=")]
    if len(existing) > 1:
        raise ValueError("Duplicate TURN shared secret configuration.")
    secret = existing[0] if existing else secrets.token_hex(32)
    if len(secret) < 32 or not all(c.isalnum() or c in "-_" for c in secret):
        raise ValueError("Invalid TURN shared secret format.")
    # aiortc currently uses the first TURN URL only. TCP also works on networks
    # blocking outbound UDP; browsers may gather both alternatives.
    urls = [f"turn:{public}:3478?transport=tcp", f"turn:{public}:3478?transport=udp"]
    lines = [line for line in lines if not line.startswith(("AGENTPARK_TURN_SECRET=", "AGENTPARK_TURN_URLS="))]
    lines += ["AGENTPARK_TURN_SECRET=" + secret, "AGENTPARK_TURN_URLS='" + json.dumps(urls) + "'"]
    template = Path(__file__).with_name("turnserver.conf").read_text(encoding="utf-8")
    config = template.replace("@PUBLIC_IP@", str(public)).replace("@PRIVATE_IP@", str(private)).replace("@AUTH_SECRET@", secret)
    group = grp.getgrnam("agentpark").gr_gid
    write_private(Path("/etc/agentpark/turnserver.conf"), config, group, 0o640)
    write_private(environment, "\n".join(lines) + "\n", group, 0o600)
    print("TURN configured with authenticated TCP/UDP and UDP relay ports 49160-49259.")


if __name__ == "__main__":
    main()

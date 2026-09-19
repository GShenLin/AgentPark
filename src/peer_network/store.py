from __future__ import annotations

import json
from pathlib import Path

from src.file_transaction import atomic_write_text
from .contracts import DeviceSetup, NetworkSettings, PeerGrant


class PeerStore:
    """Owned by the backend event loop; private config is never returned verbatim."""

    def __init__(self, root: Path):
        self.root = root
        self.settings = DeviceSetup().connection_settings()
        self.grants: dict[str, PeerGrant] = {}
        path = root / "network.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if set(data) != {"settings", "grants"}:
                raise ValueError("Invalid peer network configuration.")
            self.settings = NetworkSettings.model_validate(data["settings"])
            grants = [PeerGrant.model_validate(item) for item in data["grants"]]
            self.grants = {item.peer_id: item for item in grants}
            if len(grants) != len(self.grants):
                raise ValueError("Duplicate peer grants.")

    def save(self) -> None:
        path = self.root / "network.json"
        data = {"settings": self.settings.model_dump(), "grants": [g.model_dump() for g in self.grants.values()]}
        atomic_write_text(str(path), json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        path.chmod(0o600)

    def public_settings(self) -> dict:
        return {"enabled": self.settings.enabled, "server_ip": self.settings.server_ip,
                "display_name": self.settings.display_name}

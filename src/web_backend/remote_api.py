from __future__ import annotations

from urllib.parse import urlparse

from src.file_transaction import atomic_write_text

from .domain_base import DomainBase
from .shared import *


DEFAULT_REMOTE = {
    "id": "default",
    "name": "Default",
    "host": "127.0.0.1",
    "port": 8788,
}


class RemoteApiDomain(DomainBase):
    def _remote_config_path(self) -> str:
        return os.path.join(_get_runtime_root(), "config", "remote.json")

    def _load_remote_config(self) -> dict:
        path = self._remote_config_path()
        if not os.path.exists(path):
            return {"remotes": [dict(DEFAULT_REMOTE)]}
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail=f"remote config is invalid: {exc}") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=500, detail="remote config must be an object")
        return self._normalize_config(payload)

    def _write_remote_config(self, payload: dict) -> None:
        path = self._remote_config_path()
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    def _normalize_config(self, payload: dict) -> dict:
        remotes = payload.get("remotes")
        if not isinstance(remotes, list):
            remotes = []
        normalized = [dict(DEFAULT_REMOTE)]
        seen = {"default"}
        for item in remotes:
            if not isinstance(item, dict):
                continue
            remote = self._normalize_remote(item, allow_default=True)
            remote_id = str(remote.get("id") or "").strip()
            if not remote_id or remote_id in seen or remote_id == "default":
                continue
            seen.add(remote_id)
            normalized.append(remote)
        return {"remotes": normalized}

    def _normalize_remote(self, payload: dict, *, allow_default: bool = False) -> dict:
        raw_host = str(payload.get("host") or payload.get("ip") or "").strip()
        raw_port = payload.get("port")
        raw_address = str(payload.get("address") or "").strip()
        if raw_address and (not raw_host or raw_port in (None, "")):
            parsed_host, parsed_port = self._parse_address(raw_address)
            raw_host = raw_host or parsed_host
            raw_port = raw_port if raw_port not in (None, "") else parsed_port

        host = self._normalize_host(raw_host)
        port = self._normalize_port(raw_port)
        name = str(payload.get("name") or "").strip()
        if not name:
            name = "Default" if allow_default and host == "127.0.0.1" and port == 8788 else f"{host}:{port}"
        remote_id = str(payload.get("id") or "").strip() or self._build_remote_id(host, port)
        if remote_id == "default" and not allow_default:
            remote_id = self._build_remote_id(host, port)
        return {"id": remote_id, "name": name, "host": host, "port": port}

    def _parse_address(self, address: str) -> tuple[str, object]:
        value = address.strip()
        if not value:
            return "", ""
        parsed = urlparse(value if "://" in value else f"http://{value}")
        return str(parsed.hostname or ""), parsed.port or ""

    def _normalize_host(self, value: object) -> str:
        host = str(value or "").strip()
        if not host:
            raise HTTPException(status_code=400, detail="host is required")
        if "://" in host or "/" in host or "?" in host or "#" in host:
            raise HTTPException(status_code=400, detail="host must be an IP or hostname")
        if any(ch.isspace() for ch in host):
            raise HTTPException(status_code=400, detail="host must not contain whitespace")
        return host

    def _normalize_port(self, value: object) -> int:
        try:
            port = int(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="port must be a number") from exc
        if port < 1 or port > 65535:
            raise HTTPException(status_code=400, detail="port must be between 1 and 65535")
        return port

    def _build_remote_id(self, host: str, port: int) -> str:
        safe_host = re.sub(r"[^A-Za-z0-9_.-]+", "-", host).strip("-._") or "remote"
        return f"{safe_host}-{port}"

    def list_remotes(self):
        config = self._load_remote_config()
        if not os.path.exists(self._remote_config_path()):
            self._write_remote_config(config)
        return config

    def add_remote(self, payload: dict):
        remote = self._normalize_remote(payload or {})
        config = self._load_remote_config()
        remotes = config.get("remotes", [])
        if any(item.get("id") == remote["id"] for item in remotes if isinstance(item, dict)):
            raise HTTPException(status_code=409, detail="remote already exists")
        if any(item.get("host") == remote["host"] and item.get("port") == remote["port"] for item in remotes if isinstance(item, dict)):
            raise HTTPException(status_code=409, detail="remote address already exists")
        remotes.append(remote)
        config = {"remotes": remotes}
        self._write_remote_config(config)
        return {"ok": True, "remote": remote, "remotes": remotes}

    def delete_remote(self, remote_id: str):
        safe_id = str(remote_id or "").strip()
        if safe_id == "default":
            raise HTTPException(status_code=400, detail="default remote cannot be deleted")
        config = self._load_remote_config()
        remotes = [item for item in config.get("remotes", []) if isinstance(item, dict)]
        next_remotes = [item for item in remotes if item.get("id") != safe_id]
        if len(next_remotes) == len(remotes):
            raise HTTPException(status_code=404, detail="remote not found")
        config = {"remotes": next_remotes}
        self._write_remote_config(config)
        return {"ok": True, "remotes": next_remotes}


__all__ = ["RemoteApiDomain"]

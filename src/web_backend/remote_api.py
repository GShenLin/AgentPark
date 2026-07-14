from __future__ import annotations

from fastapi import Request

from src.file_transaction import atomic_write_text

from .domain_base import DomainBase
from .request_access import is_local_request
from .shared import *


DEFAULT_REMOTE = {
    "id": "default",
    "name": "Default",
    "host": "127.0.0.1",
    "port": 8788,
    "private": False,
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
        return self._validate_config(payload)

    def _write_remote_config(self, payload: dict) -> None:
        path = self._remote_config_path()
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    def _validate_config(self, payload: dict) -> dict:
        remotes = payload.get("remotes")
        if not isinstance(remotes, list):
            raise HTTPException(status_code=500, detail="remote config field 'remotes' must be a list")
        validated = [dict(DEFAULT_REMOTE)]
        seen = {"default"}
        for index, item in enumerate(remotes):
            if not isinstance(item, dict):
                raise HTTPException(status_code=500, detail=f"remote config remotes[{index}] must be an object")
            remote = self._validate_remote(item, allow_default=True)
            remote_id = str(remote.get("id") or "").strip()
            if remote_id == "default":
                continue
            if not remote_id or remote_id in seen:
                raise HTTPException(status_code=500, detail=f"duplicate remote id: {remote_id}")
            seen.add(remote_id)
            validated.append(remote)
        return {"remotes": validated}

    def _validate_remote(self, payload: dict, *, allow_default: bool = False) -> dict:
        raw_host = str(payload.get("host") or "").strip()
        raw_port = payload.get("port")

        host = self._validate_host(raw_host)
        port = self._validate_port(raw_port)
        name = str(payload.get("name") or "").strip()
        if not name:
            name = "Default" if allow_default and host == "127.0.0.1" and port == 8788 else f"{host}:{port}"
        remote_id = str(payload.get("id") or "").strip() or self._build_remote_id(host, port)
        if remote_id == "default" and not allow_default:
            remote_id = self._build_remote_id(host, port)
        return {
            "id": remote_id,
            "name": name,
            "host": host,
            "port": port,
            "private": self._validate_private(payload),
        }

    def _validate_private(self, payload: dict) -> bool:
        if "private" not in payload:
            return False
        value = payload.get("private")
        if not isinstance(value, bool):
            raise HTTPException(status_code=400, detail="private must be a boolean")
        return value

    def _validate_host(self, value: object) -> str:
        host = str(value or "").strip()
        if not host:
            raise HTTPException(status_code=400, detail="host is required")
        if "://" in host or "/" in host or "?" in host or "#" in host:
            raise HTTPException(status_code=400, detail="host must be an IP or hostname")
        if any(ch.isspace() for ch in host):
            raise HTTPException(status_code=400, detail="host must not contain whitespace")
        return host

    def _validate_port(self, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise HTTPException(status_code=400, detail="port must be an integer")
        port = value
        if port < 1 or port > 65535:
            raise HTTPException(status_code=400, detail="port must be between 1 and 65535")
        return port

    def _build_remote_id(self, host: str, port: int) -> str:
        safe_host = re.sub(r"[^A-Za-z0-9_.-]+", "-", host).strip("-._") or "remote"
        return f"{safe_host}-{port}"

    def _is_local_request(self, request: Request = None) -> bool:
        return is_local_request(request)

    def _filter_remotes_for_request(self, config: dict, request: Request = None) -> dict:
        if self._is_local_request(request):
            return config
        remotes = [item for item in config.get("remotes", []) if isinstance(item, dict) and not item.get("private")]
        return {"remotes": remotes}

    def list_remotes(self, request: Request = None):
        config = self._load_remote_config()
        if not os.path.exists(self._remote_config_path()):
            self._write_remote_config(config)
        return self._filter_remotes_for_request(config, request)

    def get_remote_status(self, request: Request = None):
        return {"is_local_client": self._is_local_request(request)}

    def add_remote(self, payload: dict, request: Request = None):
        remote = self._validate_remote(payload or {})
        if remote.get("private") and not self._is_local_request(request):
            raise HTTPException(status_code=403, detail="private remotes can only be created from a local client")
        config = self._load_remote_config()
        remotes = config.get("remotes", [])
        if any(item.get("id") == remote["id"] for item in remotes if isinstance(item, dict)):
            raise HTTPException(status_code=409, detail="remote already exists")
        if any(item.get("host") == remote["host"] and item.get("port") == remote["port"] for item in remotes if isinstance(item, dict)):
            raise HTTPException(status_code=409, detail="remote address already exists")
        remotes.append(remote)
        config = {"remotes": remotes}
        self._write_remote_config(config)
        visible_config = self._filter_remotes_for_request(config, request)
        return {"ok": True, "remote": remote, "remotes": visible_config["remotes"]}

    def delete_remote(self, remote_id: str, request: Request = None):
        safe_id = str(remote_id or "").strip()
        if safe_id == "default":
            raise HTTPException(status_code=400, detail="default remote cannot be deleted")
        config = self._load_remote_config()
        remotes = [item for item in config.get("remotes", []) if isinstance(item, dict)]
        target = next((item for item in remotes if item.get("id") == safe_id), None)
        if target and target.get("private") and not self._is_local_request(request):
            raise HTTPException(status_code=404, detail="remote not found")
        next_remotes = [item for item in remotes if item.get("id") != safe_id]
        if len(next_remotes) == len(remotes):
            raise HTTPException(status_code=404, detail="remote not found")
        config = {"remotes": next_remotes}
        self._write_remote_config(config)
        visible_config = self._filter_remotes_for_request(config, request)
        return {"ok": True, "remotes": visible_config["remotes"]}


__all__ = ["RemoteApiDomain"]

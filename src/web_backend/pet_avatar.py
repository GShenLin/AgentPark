from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi.responses import FileResponse

from src.file_transaction import atomic_write_text

from .domain_base import DomainBase
from .pet_avatar_schema import validate_sequence_tracks
from .runtime_paths import _get_runtime_root
from .shared import HTTPException


AVATAR_SCHEMA_VERSION = 1
SUPPORTED_ASSET_EXTENSIONS = {".gif", ".png", ".webp"}
SEQUENCE_ASSET_EXTENSIONS = {".png", ".webp"}
GIF_ASSET_EXTENSIONS = {".gif"}
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
SAFE_STATE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class PetAvatarDomain(DomainBase):
    def __init__(self, core: object, *dependencies: object) -> None:
        super().__init__(core, *dependencies)
        self._summary_cache: dict[str, tuple[int, int, dict[str, Any]]] = {}

    def _avatar_root(self) -> Path:
        return Path(_get_runtime_root()) / "petAvatars"

    def _require_avatar_id(self, value: object) -> str:
        avatar_id = str(value or "").strip()
        if not SAFE_ID_RE.match(avatar_id):
            raise HTTPException(
                status_code=400,
                detail="avatar_id must start with a letter or number and contain only letters, numbers, hyphen, or underscore",
            )
        return avatar_id

    def _require_state_id(self, value: object) -> str:
        state_id = str(value or "").strip()
        if not SAFE_STATE_RE.match(state_id):
            raise HTTPException(
                status_code=400,
                detail="state must start with a letter or number and contain only letters, numbers, hyphen, or underscore",
            )
        return state_id

    def _avatar_dir(self, avatar_id: str) -> Path:
        safe_avatar_id = self._require_avatar_id(avatar_id)
        root = self._avatar_root().resolve()
        path = (root / safe_avatar_id).resolve()
        if root != path and root not in path.parents:
            raise HTTPException(status_code=400, detail="avatar path escapes petAvatars")
        return path

    def _frame_path(self, avatar_id: str) -> Path:
        return self._avatar_dir(avatar_id) / "frame.json"

    def _safe_asset_rel_path(self, value: object) -> str:
        text = str(value or "").replace("\\", "/").strip()
        if not text or text.startswith("/") or ":" in text:
            raise HTTPException(status_code=400, detail="asset path must be a relative path")
        normalized = os.path.normpath(text).replace("\\", "/")
        if normalized == "." or normalized.startswith("../") or normalized == "..":
            raise HTTPException(status_code=400, detail="asset path must stay inside the avatar folder")
        if Path(normalized).suffix.lower() not in SUPPORTED_ASSET_EXTENSIONS:
            raise HTTPException(status_code=400, detail="asset path must end with .gif, .png, or .webp")
        return normalized

    def _asset_path(self, avatar_id: str, rel_path: str) -> Path:
        avatar_dir = self._avatar_dir(avatar_id).resolve()
        safe_rel = self._safe_asset_rel_path(rel_path)
        path = (avatar_dir / safe_rel).resolve()
        if avatar_dir != path and avatar_dir not in path.parents:
            raise HTTPException(status_code=400, detail="asset path escapes avatar folder")
        return path

    def _read_frame(self, avatar_id: str, *, require_assets: bool = True) -> dict[str, Any]:
        path = self._frame_path(avatar_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"frame.json not found for avatar '{avatar_id}'")
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"avatar '{avatar_id}' frame.json is invalid JSON: line {exc.lineno} column {exc.colno}: {exc.msg}",
            ) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to read avatar '{avatar_id}' frame.json: {exc}") from exc
        return self._validate_frame(avatar_id, payload, require_assets=require_assets)

    def _validate_frame(self, avatar_id: str, payload: object, require_assets: bool) -> dict[str, Any]:
        safe_avatar_id = self._require_avatar_id(avatar_id)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="frame.json must be an object")
        if payload.get("version") != AVATAR_SCHEMA_VERSION:
            raise HTTPException(status_code=400, detail=f"frame.json version must be {AVATAR_SCHEMA_VERSION}")
        if str(payload.get("id") or "").strip() != safe_avatar_id:
            raise HTTPException(status_code=400, detail="frame.json id must match avatar_id")
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="frame.json name is required")
        if payload.get("renderer") != "sprite2d":
            raise HTTPException(status_code=400, detail="frame.json renderer must be 'sprite2d'")
        fps = payload.get("fps")
        if not isinstance(fps, int) or fps < 1 or fps > 60:
            raise HTTPException(status_code=400, detail="frame.json fps must be an integer between 1 and 60")
        states = payload.get("states")
        if not isinstance(states, dict):
            raise HTTPException(status_code=400, detail="frame.json states must be an object")
        normalized_states: dict[str, Any] = {}
        for state_id, state in states.items():
            safe_state_id = self._require_state_id(state_id)
            if not isinstance(state, dict):
                raise HTTPException(status_code=400, detail=f"state '{safe_state_id}' must be an object")
            animation_type = str(state.get("type") or "").strip()
            if animation_type == "gif":
                normalized_states[safe_state_id] = self._validate_gif_state(safe_avatar_id, safe_state_id, state, require_assets)
            elif animation_type == "sequence":
                normalized_states[safe_state_id] = self._validate_sequence_state(safe_avatar_id, safe_state_id, state, require_assets)
            else:
                raise HTTPException(status_code=400, detail=f"state '{safe_state_id}' type must be 'gif' or 'sequence'")
        normalized = dict(payload)
        normalized["id"] = safe_avatar_id
        normalized["name"] = name
        normalized["renderer"] = "sprite2d"
        normalized["fps"] = fps
        normalized["states"] = normalized_states
        return normalized

    def _validate_gif_state(self, avatar_id: str, state_id: str, state: dict[str, Any], require_assets: bool) -> dict[str, Any]:
        src = self._safe_asset_rel_path(state.get("src"))
        if Path(src).suffix.lower() not in GIF_ASSET_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"state '{state_id}' gif src must end with .gif")
        if require_assets and not self._asset_path(avatar_id, src).is_file():
            raise HTTPException(status_code=400, detail=f"state '{state_id}' references missing asset: {src}")
        loop = state.get("loop", True)
        if not isinstance(loop, bool):
            raise HTTPException(status_code=400, detail=f"state '{state_id}' loop must be boolean")
        return {"type": "gif", "src": src, "loop": loop}

    def _validate_sequence_state(self, avatar_id: str, state_id: str, state: dict[str, Any], require_assets: bool) -> dict[str, Any]:
        loop = state.get("loop", True)
        if not isinstance(loop, bool):
            raise HTTPException(status_code=400, detail=f"state '{state_id}' loop must be boolean")
        frames = state.get("frames")
        if not isinstance(frames, list) or not frames:
            raise HTTPException(status_code=400, detail=f"state '{state_id}' sequence frames must be a non-empty list")
        normalized_frames: list[dict[str, Any]] = []
        for index, frame in enumerate(frames):
            if not isinstance(frame, dict):
                raise HTTPException(status_code=400, detail=f"state '{state_id}' frame {index} must be an object")
            src = self._safe_asset_rel_path(frame.get("src"))
            if Path(src).suffix.lower() not in SEQUENCE_ASSET_EXTENSIONS:
                raise HTTPException(status_code=400, detail=f"state '{state_id}' sequence frame {index} must use .png or .webp")
            hold_frames = frame.get("holdFrames")
            if not isinstance(hold_frames, int) or hold_frames < 1 or hold_frames > 600:
                raise HTTPException(status_code=400, detail=f"state '{state_id}' frame {index} holdFrames must be an integer between 1 and 600")
            if require_assets and not self._asset_path(avatar_id, src).is_file():
                raise HTTPException(status_code=400, detail=f"state '{state_id}' references missing asset: {src}")
            normalized_frames.append({"src": src, "holdFrames": hold_frames})
        normalized = {"type": "sequence", "loop": loop, "frames": normalized_frames}
        normalized_tracks = validate_sequence_tracks(
            state_id,
            state.get("tracks"),
            sum(item["holdFrames"] for item in normalized_frames),
        )
        if normalized_tracks:
            normalized["tracks"] = normalized_tracks
        return normalized

    def _frame_with_asset_urls(self, frame: dict[str, Any], revision: str = "") -> dict[str, Any]:
        avatar_id = str(frame.get("id") or "")
        result = dict(frame)
        states: dict[str, Any] = {}
        for state_id, state in (frame.get("states") or {}).items():
            if not isinstance(state, dict):
                continue
            next_state = dict(state)
            if next_state.get("type") == "gif":
                src = str(next_state.get("src") or "")
                next_state["url"] = self._asset_url(avatar_id, src, revision)
            elif next_state.get("type") == "sequence":
                next_frames = []
                for frame_item in next_state.get("frames") or []:
                    if isinstance(frame_item, dict):
                        item = dict(frame_item)
                        item["url"] = self._asset_url(avatar_id, str(item.get("src") or ""), revision)
                        next_frames.append(item)
                next_state["frames"] = next_frames
            states[str(state_id)] = next_state
        result["states"] = states
        return result

    def _asset_url(self, avatar_id: str, rel_path: str, revision: str = "") -> str:
        path = f"/api/pet-avatars/{quote(avatar_id)}/assets/{quote(rel_path)}"
        return f"{path}?v={quote(revision)}" if revision else path

    def _avatar_revision(self, avatar_id: str) -> str:
        try:
            return str(self._frame_path(avatar_id).stat().st_mtime_ns)
        except OSError:
            return ""

    def _pack_summary(self, avatar_dir: Path) -> dict[str, Any]:
        avatar_id = avatar_dir.name
        frame_path = avatar_dir / "frame.json"
        try:
            stat = frame_path.stat()
        except OSError:
            stat = None
        if stat is not None:
            cached = self._summary_cache.get(avatar_id)
            if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
                return dict(cached[2])
        try:
            frame = self._read_frame(avatar_id, require_assets=False)
            summary = {
                "id": avatar_id,
                "name": frame.get("name"),
                "renderer": frame.get("renderer"),
                "fps": frame.get("fps"),
                "states": list((frame.get("states") or {}).keys()),
                "path": str(avatar_dir),
                "valid": True,
                "asset_validation": "deferred",
            }
        except HTTPException as exc:
            summary = {
                "id": avatar_id,
                "name": avatar_id,
                "renderer": "sprite2d",
                "fps": 12,
                "states": [],
                "path": str(avatar_dir),
                "valid": False,
                "error": str(exc.detail),
            }
        if stat is not None:
            self._summary_cache[avatar_id] = (stat.st_mtime_ns, stat.st_size, dict(summary))
        return summary

    def list_pet_avatars(self):
        root = self._avatar_root()
        root.mkdir(parents=True, exist_ok=True)
        avatars = []
        for item in sorted(root.iterdir(), key=lambda path: path.name.lower()):
            if item.is_dir() and SAFE_ID_RE.match(item.name):
                avatars.append(self._pack_summary(item))
        return {"schema_version": AVATAR_SCHEMA_VERSION, "root": str(root), "avatars": avatars}

    def get_pet_avatar(self, avatar_id: str):
        frame = self._read_frame(avatar_id)
        return {"avatar": self._frame_with_asset_urls(frame, self._avatar_revision(avatar_id)), "path": str(self._avatar_dir(avatar_id))}

    def _publish_avatar_updated(self, avatar_id: str, reason: str) -> None:
        desktop_views = getattr(self.core, "node_desktop_views", None)
        graph_runtime = getattr(self.core, "graph_runtime", None)
        if desktop_views is None or graph_runtime is None or not hasattr(desktop_views, "list_visible_desktop_pet_refs"):
            return
        refs = desktop_views.list_visible_desktop_pet_refs()
        graph_ids = sorted({str(item.get("graph_id") or "").strip() for item in refs if str(item.get("graph_id") or "").strip()})
        for graph_id in graph_ids:
            graph_runtime._log_graph_event(graph_id, "pet_avatar_updated", avatar_id=avatar_id, reason=reason)

    def create_pet_avatar(self, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        avatar_id = self._require_avatar_id(payload.get("id"))
        name = str(payload.get("name") or avatar_id).strip()
        avatar_dir = self._avatar_dir(avatar_id)
        frame_path = self._frame_path(avatar_id)
        if avatar_dir.exists() and frame_path.exists():
            raise HTTPException(status_code=409, detail=f"avatar '{avatar_id}' already exists")
        avatar_dir.mkdir(parents=True, exist_ok=True)
        frame = {
            "version": AVATAR_SCHEMA_VERSION,
            "id": avatar_id,
            "name": name,
            "renderer": "sprite2d",
            "fps": 12,
            "states": {},
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        atomic_write_text(str(frame_path), json.dumps(frame, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "avatar": frame, "path": str(avatar_dir)}

    def update_pet_avatar_frame(self, avatar_id: str, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        frame_payload = payload.get("frame")
        frame = self._validate_frame(avatar_id, frame_payload, require_assets=True)
        frame["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        frame_path = self._frame_path(avatar_id)
        frame_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(str(frame_path), json.dumps(frame, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._publish_avatar_updated(self._require_avatar_id(avatar_id), "frame")
        return {"ok": True, "avatar": self._frame_with_asset_urls(frame, self._avatar_revision(avatar_id)), "path": str(frame_path.parent)}

    def upload_pet_avatar_asset(self, avatar_id: str, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        state_id = self._require_state_id(payload.get("state"))
        filename = str(payload.get("filename") or "").strip().replace("\\", "/").split("/")[-1]
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_ASSET_EXTENSIONS:
            raise HTTPException(status_code=400, detail="filename must end with .gif, .png, or .webp")
        content_base64 = str(payload.get("content_base64") or "").strip()
        if not content_base64:
            raise HTTPException(status_code=400, detail="content_base64 is required")
        if "," in content_base64:
            content_base64 = content_base64.split(",", 1)[1]
        try:
            content = base64.b64decode(content_base64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="content_base64 is not valid base64") from exc
        if not content:
            raise HTTPException(status_code=400, detail="uploaded asset is empty")
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="uploaded asset exceeds 10 MB")
        avatar_dir = self._avatar_dir(avatar_id)
        if not self._frame_path(avatar_id).is_file():
            raise HTTPException(status_code=404, detail=f"avatar '{avatar_id}' does not exist")
        target_dir = avatar_dir / state_id
        target_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(filename).stem or "asset"
        target = target_dir / f"{stem}{suffix}"
        counter = 2
        while target.exists():
            target = target_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        try:
            with target.open("xb") as handle:
                handle.write(content)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to write avatar asset: {exc}") from exc
        rel_path = target.relative_to(avatar_dir).as_posix()
        return {"ok": True, "src": rel_path, "url": self._asset_url(self._require_avatar_id(avatar_id), rel_path), "extension": suffix}

    def get_pet_avatar_asset(self, avatar_id: str, asset_path: str):
        path = self._asset_path(avatar_id, asset_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="avatar asset not found")
        suffix = path.suffix.lower()
        media_type = {
            ".gif": "image/gif",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(suffix, "application/octet-stream")
        return FileResponse(str(path), media_type=media_type)


__all__ = ["PetAvatarDomain"]

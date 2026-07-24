from __future__ import annotations

import json
import mimetypes
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from src.file_transaction import run_with_interprocess_lock
from src.workspace_settings import get_workspace_root

from .service_host import HostBoundService
from .shared import HTTPException


class InputBundleLibrary(HostBoundService):
    _MANIFEST_FILENAME = "manifest.json"
    _TEXT_FILENAME = "text.txt"
    _ATTACHMENTS_DIRNAME = "attachments"

    def _library_dir(self) -> Path:
        return Path(get_workspace_root()) / "input"

    def list_input_bundles(self):
        root = self._library_dir()
        if not root.exists():
            return {"bundles": []}
        bundles = [
            item.name
            for item in root.iterdir()
            if item.is_dir() and (item / self._MANIFEST_FILENAME).is_file()
        ]
        return {"bundles": sorted(bundles, key=str.casefold)}

    def get_input_bundle(self, name: str):
        bundle_dir = self._resolve_bundle_dir(name)
        manifest_path = bundle_dir / self._MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise HTTPException(status_code=404, detail="Input bundle not found")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"Invalid input bundle manifest: {exc}") from exc
        if not isinstance(manifest, dict) or manifest.get("version") != 1:
            raise HTTPException(status_code=500, detail="Unsupported input bundle manifest")

        text_path = self._resolve_member(bundle_dir, manifest.get("text_file"), self._TEXT_FILENAME)
        try:
            text = text_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Unable to read input text: {exc}") from exc

        attachments = []
        raw_attachments = manifest.get("attachments", [])
        if not isinstance(raw_attachments, list):
            raise HTTPException(status_code=500, detail="Invalid input bundle attachments")
        for raw in raw_attachments:
            if not isinstance(raw, dict):
                raise HTTPException(status_code=500, detail="Invalid input bundle attachment entry")
            stored_path = self._resolve_member(bundle_dir, raw.get("file"), "")
            if not stored_path.is_file():
                raise HTTPException(status_code=500, detail=f"Missing input attachment: {stored_path.name}")
            mime = str(raw.get("mime") or mimetypes.guess_type(stored_path.name)[0] or "application/octet-stream")
            attachments.append(
                {
                    "name": str(raw.get("name") or stored_path.name),
                    "path": str(stored_path),
                    "kind": str(raw.get("kind") or self._resource_kind(mime)),
                    "mime": mime,
                    "size": stored_path.stat().st_size,
                    "source": "input_bundle",
                }
            )
        return {"name": bundle_dir.name, "text": text, "attachments": attachments}

    def save_input_bundle(self, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Input bundle payload must be an object")
        bundle_dir = self._resolve_bundle_dir(payload.get("name"))
        text = str(payload.get("text") or "")
        raw_attachments = payload.get("attachments", [])
        if not isinstance(raw_attachments, list):
            raise HTTPException(status_code=400, detail="attachments must be an array")
        if not text.strip() and not raw_attachments:
            raise HTTPException(status_code=400, detail="Input bundle is empty")

        root = self._library_dir()
        root.mkdir(parents=True, exist_ok=True)
        lock_path = root / f".{bundle_dir.name}.lock"
        try:
            run_with_interprocess_lock(
                str(lock_path),
                lambda: self._replace_input_bundle(bundle_dir, text, raw_attachments),
            )
        except HTTPException:
            raise
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Unable to save input bundle: {exc}") from exc
        return {"ok": True, "name": bundle_dir.name}

    def _replace_input_bundle(self, bundle_dir: Path, text: str, raw_attachments: list[object]) -> None:
        root = bundle_dir.parent
        staging = Path(tempfile.mkdtemp(prefix=f".{bundle_dir.name}-", dir=str(root)))
        backup = root / f".{bundle_dir.name}.backup-{uuid.uuid4().hex}"
        try:
            (staging / self._TEXT_FILENAME).write_text(text, encoding="utf-8")
            manifest_attachments = self._copy_attachments(staging, raw_attachments)
            manifest = {
                "version": 1,
                "text_file": self._TEXT_FILENAME,
                "attachments": manifest_attachments,
            }
            (staging / self._MANIFEST_FILENAME).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if bundle_dir.exists():
                os.replace(bundle_dir, backup)
            try:
                os.replace(staging, bundle_dir)
            except Exception:
                if backup.exists() and not bundle_dir.exists():
                    os.replace(backup, bundle_dir)
                raise
            if backup.exists():
                shutil.rmtree(backup)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            if backup.exists() and bundle_dir.exists():
                shutil.rmtree(backup, ignore_errors=True)

    def _copy_attachments(self, staging: Path, raw_attachments: list[object]) -> list[dict]:
        if not raw_attachments:
            return []
        attachments_dir = staging / self._ATTACHMENTS_DIRNAME
        attachments_dir.mkdir(parents=True, exist_ok=True)
        manifest_entries: list[dict] = []
        used_names: set[str] = set()
        for index, raw in enumerate(raw_attachments, start=1):
            if not isinstance(raw, dict):
                raise HTTPException(status_code=400, detail="Each attachment must be an object")
            source = self._resolve_source_file(raw.get("path"))
            display_name = str(raw.get("name") or source.name).strip() or source.name
            stored_name = self._unique_attachment_name(display_name, index, used_names)
            target = attachments_dir / stored_name
            try:
                shutil.copy2(source, target)
            except OSError as exc:
                raise HTTPException(status_code=500, detail=f"Unable to copy attachment {display_name}: {exc}") from exc
            mime = str(raw.get("mime") or mimetypes.guess_type(stored_name)[0] or "application/octet-stream")
            manifest_entries.append(
                {
                    "name": display_name,
                    "file": f"{self._ATTACHMENTS_DIRNAME}/{stored_name}",
                    "kind": str(raw.get("kind") or self._resource_kind(mime)),
                    "mime": mime,
                }
            )
        return manifest_entries

    def _resolve_source_file(self, value: object) -> Path:
        raw = str(value or "").strip()
        if not raw or "://" in raw or raw.lower().startswith(("data:", "blob:")):
            raise HTTPException(status_code=400, detail="Input attachments must be local files")
        source = Path(raw)
        if not source.is_absolute():
            source = self._library_dir().parent / source
        source = source.resolve()
        if not source.is_file():
            raise HTTPException(status_code=400, detail=f"Attachment file not found: {raw}")
        return source

    def _resolve_bundle_dir(self, value: object) -> Path:
        name = str(value or "").strip()
        if not name or name in {".", ".."} or Path(name).name != name:
            raise HTTPException(status_code=400, detail="Invalid input bundle name")
        if any(char in name for char in '<>:"/\\|?*'):
            raise HTTPException(status_code=400, detail="Invalid input bundle name")
        return self._library_dir() / name

    def _resolve_member(self, bundle_dir: Path, value: object, default: str) -> Path:
        relative = str(value or default).strip()
        if not relative:
            raise HTTPException(status_code=500, detail="Invalid input bundle member")
        candidate = (bundle_dir / relative).resolve()
        try:
            candidate.relative_to(bundle_dir.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="Input bundle member escapes its directory") from exc
        return candidate

    def _unique_attachment_name(self, value: str, index: int, used_names: set[str]) -> str:
        raw_name = Path(value).name
        stem = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in Path(raw_name).stem)
        stem = stem.strip("._") or f"attachment-{index}"
        suffix = "".join(char for char in Path(raw_name).suffix if char.isalnum() or char == ".")[:16]
        candidate = f"{stem}{suffix}"
        sequence = 2
        while candidate.casefold() in used_names:
            candidate = f"{stem}-{sequence}{suffix}"
            sequence += 1
        used_names.add(candidate.casefold())
        return candidate

    def _resource_kind(self, mime: str) -> str:
        top_level = mime.split("/", 1)[0].lower()
        if top_level in {"image", "video", "audio"}:
            return top_level
        return "doc"


__all__ = ["InputBundleLibrary"]

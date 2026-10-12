from __future__ import annotations

import copy
import json
import os
import re
import shutil
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from src import workspace_settings
from src.file_transaction import atomic_write_text
from src.web_backend.theme_defaults import DEFAULT_THEME_CONFIG, DEFAULT_THEME_PRESET_ID


THEME_PRESET_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
THEME_ASSET_EXTENSIONS = {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
MAX_THEME_ASSET_BYTES = 50 * 1024 * 1024


def theme_config_path() -> str:
    return str(theme_preset_config_path(active_theme_preset_id()))


def theme_root() -> str:
    return os.path.join(workspace_settings.get_workspace_root(), "theme")


def legacy_theme_config_path() -> str:
    return os.path.join(workspace_settings.get_workspace_root(), "config", "theme.json")


def legacy_active_theme_state_path() -> str:
    return os.path.join(theme_root(), "active.json")


def active_theme_state_path() -> str:
    return os.path.join(workspace_settings.get_workspace_cache_dir(), "theme", "active.json")


def theme_preset_dir(preset_id: str) -> Path:
    safe_id = validate_theme_preset_id(preset_id)
    return Path(theme_root(), safe_id)


def theme_preset_config_path(preset_id: str) -> Path:
    return theme_preset_dir(preset_id) / "theme.json"


def active_theme_preset_id() -> str:
    _migrate_legacy_active_theme_state()
    path = active_theme_state_path()
    if not os.path.isfile(path):
        return DEFAULT_THEME_PRESET_ID
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return DEFAULT_THEME_PRESET_ID
    try:
        return validate_theme_preset_id(str(payload.get("active_preset_id") or DEFAULT_THEME_PRESET_ID))
    except ValueError:
        return DEFAULT_THEME_PRESET_ID


def set_active_theme_preset(preset_id: str) -> None:
    safe_id = validate_theme_preset_id(preset_id)
    path = active_theme_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write_text(
        path,
        json.dumps({"active_preset_id": safe_id}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def validate_theme_preset_id(preset_id: str) -> str:
    safe_id = str(preset_id or "").strip()
    if not safe_id:
        raise ValueError("theme preset id is required.")
    if not THEME_PRESET_ID_RE.match(safe_id):
        raise ValueError("theme preset id may only contain letters, numbers, '_' and '-'.")
    return safe_id


def load_or_create_theme_config() -> dict:
    _migrate_legacy_theme_config()
    preset_id = active_theme_preset_id()
    path = theme_preset_config_path(preset_id)
    if not path.is_file():
        payload = copy.deepcopy(DEFAULT_THEME_CONFIG)
        os.makedirs(path.parent, exist_ok=True)
        atomic_write_text(str(path), json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        set_active_theme_preset(preset_id)
        return payload
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    validate_theme_config(payload)
    changed = _merge_missing_theme_defaults(payload, DEFAULT_THEME_CONFIG)
    if changed:
        atomic_write_text(str(path), json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    set_active_theme_preset(preset_id)
    return payload


def list_theme_presets() -> dict:
    _migrate_legacy_theme_config()
    load_or_create_theme_config()
    root = Path(theme_root())
    presets = []
    if root.is_dir():
        for item in sorted(root.iterdir(), key=lambda path: path.name.lower()):
            if not item.is_dir():
                continue
            try:
                preset_id = validate_theme_preset_id(item.name)
            except ValueError:
                continue
            config_path = item / "theme.json"
            if config_path.is_file():
                presets.append(
                    {
                        "id": preset_id,
                        "path": str(config_path),
                    }
                )
    active_id = active_theme_preset_id()
    return {"active_preset_id": active_id, "presets": presets}


def load_theme_preset(preset_id: str) -> dict:
    safe_id = validate_theme_preset_id(preset_id)
    path = theme_preset_config_path(safe_id)
    if not path.is_file():
        raise FileNotFoundError(f"theme preset not found: {safe_id}")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    validate_theme_config(payload)
    changed = _merge_missing_theme_defaults(payload, DEFAULT_THEME_CONFIG)
    if changed:
        atomic_write_text(str(path), json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    set_active_theme_preset(safe_id)
    return payload


def save_theme_preset(preset_id: str, payload: object) -> dict:
    safe_id = validate_theme_preset_id(preset_id)
    validate_theme_config(payload)
    if not isinstance(payload, dict):
        raise ValueError("theme preset payload must be an object.")
    next_payload = copy.deepcopy(payload)
    _merge_missing_theme_defaults(next_payload, DEFAULT_THEME_CONFIG)
    path = theme_preset_config_path(safe_id)
    os.makedirs(path.parent, exist_ok=True)
    source_preset_id = active_theme_preset_id()
    if source_preset_id != safe_id:
        _copy_referenced_theme_assets(next_payload, source_preset_id, safe_id)
    atomic_write_text(str(path), json.dumps(next_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    set_active_theme_preset(safe_id)
    return next_payload


def save_theme_asset(upload: object, preset_id: str | None = None) -> dict:
    safe_id = validate_theme_preset_id(str(preset_id or "").strip() or active_theme_preset_id())
    config_path = theme_preset_config_path(safe_id)
    if not config_path.is_file():
        raise FileNotFoundError(f"theme preset not found: {safe_id}")

    filename = _sanitize_theme_asset_filename(getattr(upload, "filename", ""))
    target_dir = theme_preset_dir(safe_id)
    os.makedirs(target_dir, exist_ok=True)
    target_path = _next_theme_asset_path(target_dir, filename)

    total_bytes = 0
    try:
        source = getattr(upload, "file")
        with open(target_path, "wb") as out:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_THEME_ASSET_BYTES:
                    raise ValueError(f"theme image exceeds {MAX_THEME_ASSET_BYTES // (1024 * 1024)}MB limit")
                out.write(chunk)
    except Exception:
        if target_path.exists():
            try:
                target_path.unlink()
            except OSError:
                pass
        raise
    finally:
        close = getattr(getattr(upload, "file", None), "close", None)
        if callable(close):
            close()

    return {
        "ok": True,
        "preset_id": safe_id,
        "asset_path": target_path.name,
        "path": str(target_path),
        "size": total_bytes,
    }


def validate_theme_config(payload: object) -> None:
    if not isinstance(payload, dict):
        raise ValueError("theme.json must contain a top-level object.")
    schema_version = payload.get("schema_version")
    if schema_version is not None and not isinstance(schema_version, int):
        raise ValueError("theme.json field 'schema_version' must be an integer.")
    panels = payload.get("panels")
    if panels is None:
        return
    if not isinstance(panels, dict):
        raise ValueError("theme.json field 'panels' must be an object.")
    for panel_id, panel in panels.items():
        if not str(panel_id or "").strip():
            raise ValueError("theme.json panel id must be non-empty.")
        if not isinstance(panel, dict):
            raise ValueError(f"theme.json panel '{panel_id}' must be an object.")
        for group_id, group in panel.items():
            if not str(group_id or "").strip():
                raise ValueError(f"theme.json panel '{panel_id}' group id must be non-empty.")
            if not isinstance(group, dict):
                raise ValueError(f"theme.json panel '{panel_id}.{group_id}' must be an object.")
            _validate_group(panel_id, group_id, group)


def theme_image_response(asset_path: str, preset: str | None = None):
    raw_path = str(asset_path or "").replace("\\", "/").strip("/")
    if not raw_path:
        raise HTTPException(status_code=400, detail="theme image path is required")
    try:
        preset_id = validate_theme_preset_id(str(preset or "").strip() or active_theme_preset_id())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    root = theme_preset_dir(preset_id).resolve()
    target = (root / raw_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="theme image path must stay inside the theme preset") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="theme image not found")
    return FileResponse(str(target))


def _validate_group(panel_id: object, group_id: object, group: dict) -> None:
    for key, value in group.items():
        if not str(key or "").strip():
            raise ValueError(f"theme.json panel '{panel_id}.{group_id}' field id must be non-empty.")
        if value is not None and not isinstance(value, str):
            raise ValueError(f"theme.json panel '{panel_id}.{group_id}.{key}' must be a string.")
        if str(key) == "image":
            _validate_image_path(panel_id, group_id, key, value)


def _merge_missing_theme_defaults(target: dict, defaults: dict) -> bool:
    changed = False
    for key, default_value in defaults.items():
        if key not in target:
            target[key] = copy.deepcopy(default_value)
            changed = True
            continue
        current_value = target[key]
        if isinstance(current_value, dict) and isinstance(default_value, dict):
            if _merge_missing_theme_defaults(current_value, default_value):
                changed = True
    return changed


def _validate_image_path(panel_id: object, group_id: object, key: object, value: object) -> None:
    image = str(value or "").strip()
    if not image:
        return
    if os.path.isabs(image) or "://" in image:
        raise ValueError(f"theme.json panel '{panel_id}.{group_id}.{key}' must be relative to the preset folder.")
    image_path = Path(image.replace("\\", "/"))
    if any(part in {"", ".", ".."} for part in image_path.parts):
        raise ValueError(f"theme.json panel '{panel_id}.{group_id}.{key}' must be a safe relative path.")


def _sanitize_theme_asset_filename(value: object) -> str:
    raw_name = os.path.basename(str(value or "").strip())
    stem, ext = os.path.splitext(raw_name)
    safe_ext = ext.lower()
    if safe_ext not in THEME_ASSET_EXTENSIONS:
        raise ValueError(f"theme image must use one of: {', '.join(sorted(THEME_ASSET_EXTENSIONS))}")
    safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in stem).strip("._")
    return f"{safe_stem or 'theme-image'}{safe_ext}"


def _next_theme_asset_path(root: Path, filename: str) -> Path:
    stem, ext = os.path.splitext(filename)
    candidate = root / filename
    index = 1
    while candidate.exists():
        candidate = root / f"{stem}_{index}{ext}"
        index += 1
    return candidate


def _copy_referenced_theme_assets(payload: dict, source_preset_id: str, target_preset_id: str) -> None:
    source_root = theme_preset_dir(source_preset_id).resolve()
    target_root = theme_preset_dir(target_preset_id).resolve()
    for image_path in _iter_theme_image_paths(payload):
        source = (source_root / image_path).resolve()
        target = (target_root / image_path).resolve()
        try:
            source.relative_to(source_root)
            target.relative_to(target_root)
        except ValueError as exc:
            raise ValueError(f"theme image path must stay inside the preset folder: {image_path}") from exc
        if not source.is_file() or target.exists():
            continue
        os.makedirs(target.parent, exist_ok=True)
        shutil.copy2(source, target)


def _iter_theme_image_paths(payload: dict):
    panels = payload.get("panels")
    if not isinstance(panels, dict):
        return
    for panel in panels.values():
        if not isinstance(panel, dict):
            continue
        for group in panel.values():
            if not isinstance(group, dict):
                continue
            image = str(group.get("image") or "").strip().replace("\\", "/")
            if image:
                yield image


def _migrate_legacy_theme_config() -> None:
    legacy_path = legacy_theme_config_path()
    default_path = theme_preset_config_path("default")
    if not os.path.isfile(legacy_path):
        return
    if default_path.is_file():
        os.remove(legacy_path)
        return
    with open(legacy_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    validate_theme_config(payload)
    _merge_missing_theme_defaults(payload, DEFAULT_THEME_CONFIG)
    os.makedirs(default_path.parent, exist_ok=True)
    legacy_image_root = Path(workspace_settings.get_workspace_root(), "config", "img")
    if legacy_image_root.is_dir():
        shutil.copytree(legacy_image_root, default_path.parent, dirs_exist_ok=True)
    atomic_write_text(str(default_path), json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    set_active_theme_preset("default")
    os.remove(legacy_path)


def _migrate_legacy_active_theme_state() -> None:
    legacy_path = legacy_active_theme_state_path()
    active_path = active_theme_state_path()
    if not os.path.isfile(legacy_path):
        return
    if os.path.isfile(active_path):
        os.remove(legacy_path)
        return
    with open(legacy_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    preset_id = validate_theme_preset_id(str(payload.get("active_preset_id") or DEFAULT_THEME_PRESET_ID))
    os.makedirs(os.path.dirname(active_path), exist_ok=True)
    atomic_write_text(
        active_path,
        json.dumps({"active_preset_id": preset_id}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.remove(legacy_path)

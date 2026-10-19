"""Official manifest/binary distribution, with workspace-owned installation only.

Manifest contract and SHA512 verification follow Google's cli/install.ps1.
External installations retain their native updater and ownership.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import tempfile
from urllib.parse import urlparse

from src.providers.curl_transport import CurlHttpTransport
from .process import run_process
from .updates import HarnessUpdate, version_key

RELEASE_BASE = "https://antigravity-cli-auto-updater-974169037036.us-central1.run.app"


def release_platform() -> str:
    arch = {"amd64": "amd64", "x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
    system = {"Windows": "windows", "Darwin": "darwin"}.get(platform.system())
    if not arch or not system:
        raise ValueError("Managed Antigravity installation supports Windows and macOS. On other systems install the official CLI and add agy to PATH.")
    return f"{system}_{arch}"


def release() -> dict:
    response = CurlHttpTransport().request(url=f"{RELEASE_BASE}/manifests/{release_platform()}.json",
                                           timeout_sec=20, max_response_bytes=65536)
    data = response.raise_for_status().json()
    if not isinstance(data, dict):
        raise ValueError("Invalid Antigravity release manifest.")
    version_key(data.get("version"))
    url, digest = data.get("url"), data.get("sha512")
    parsed = urlparse(url) if isinstance(url, str) else None
    if (not parsed or parsed.scheme != "https" or parsed.netloc != "storage.googleapis.com"
            or not parsed.path.startswith("/antigravity-public/antigravity-cli/")
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{128}", digest)):
        raise ValueError("Invalid Antigravity release URL or SHA512 digest.")
    return data


def binary(root: Path) -> Path:
    path = root / ("agy.exe" if os.name == "nt" else "agy")
    if path.resolve() != path.absolute():
        raise ValueError("Managed Antigravity binary must not follow a symlink or junction.")
    return path


def command(root: Path) -> list[str]:
    target = binary(root)
    if target.is_file():
        return [str(target)]
    external = shutil.which("agy")
    if not external:
        raise RuntimeError("Antigravity CLI is not installed. Install it in Settings → Harness.")
    return [external]


def version(argv: list[str], cwd: Path) -> str:
    value = run_process([*argv, "--version"], cwd=str(cwd), timeout=20).strip()
    version_key(value)
    return value


def check(root: Path, *, include_updates: bool) -> dict:
    result = {"status": "missing", "version": "", "source": "none", "executable_path": "", "error": "",
              "can_uninstall": False, "can_upgrade": False, "upgrade_error": "", **asdict(HarnessUpdate())}
    try:
        managed = binary(root).is_file()
        if not managed and not shutil.which("agy"):
            return result
        result.update(source="managed" if managed else "external", can_uninstall=managed)
        argv = command(root)
        current = version(argv, Path(argv[0]).parent)
        result.update(status="ready", version=current, installed_version=current,
                      executable_path=argv[0], can_upgrade=True)
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        return {**result, "status": "error", "error": str(exc)}
    if include_updates:
        try:
            latest = release()["version"]
            result.update(latest_version=latest, update_status="available" if version_key(latest) > version_key(current) else "current")
        except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
            result.update(update_status="error", update_error=str(exc))
    return result


def mutate(root: Path, action: str) -> str:
    target = binary(root)
    if action == "uninstall":
        if not target.is_file():
            raise ValueError("Only installations owned by AgentPark can be uninstalled here.")
        target.unlink()
        return "Removed the workspace Antigravity executable. Native credentials and conversations were preserved."
    if action not in {"install", "upgrade"}:
        raise ValueError(f"Unknown Antigravity operation: {action}")
    if not target.is_file() and shutil.which("agy"):
        if action != "upgrade":
            raise ValueError("Antigravity is already installed externally; use Upgrade to run its official updater.")
        argv = command(root)
        before = version(argv, Path(argv[0]).parent)
        output = run_process([*argv, "update"], cwd=str(Path(argv[0]).parent), timeout=300)
        after = version(argv, Path(argv[0]).parent)
        if version_key(after) <= version_key(before):
            raise RuntimeError(f"Antigravity updater did not install a newer version (before {before}, after {after}). {output}")
        return output
    info = release()
    root.mkdir(parents=True, exist_ok=True)
    if action == "upgrade" and version_key(info["version"]) <= version_key(version(command(root), root)):
        raise ValueError("No newer Antigravity release is available.")
    data = CurlHttpTransport().request(url=info["url"], timeout_sec=300,
                                      max_response_bytes=512 * 1024 * 1024).raise_for_status().content
    if hashlib.sha512(data).hexdigest() != info["sha512"].lower():
        raise ValueError("Antigravity download failed SHA512 verification.")
    with tempfile.TemporaryDirectory(prefix="staging-", dir=root) as staging:
        candidate = Path(staging) / target.name
        candidate.write_bytes(data)
        candidate.chmod(0o755)
        actual = version([str(candidate)], root)
        if actual != info["version"]:
            raise ValueError(f"Antigravity binary version mismatch: expected {info['version']}, found {actual}.")
        os.replace(candidate, target)
    return f"Installed official Antigravity CLI {info['version']}; SHA512 verified."

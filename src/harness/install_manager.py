"""Workspace installation management and in-place upgrades of detected npm installations."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import threading
from contextlib import contextmanager
from dataclasses import asdict

from src.workspace_settings import get_workspace_root
from .process import run_process
from .file_lock import file_lease
from .registry import descriptor
from .npm import npm_argv
from .installation import NpmInstallation, external_npm_installation, package_entry, upgrade_installation
from .updates import HarnessUpdate, check_updates, installed_version, latest_version, version_key

_LOCK = threading.RLock()
_ACTIVE: dict[str, int] = {}
_MUTATING: set[str] = set()


def install_root(harness_id: str) -> Path:
    descriptor(harness_id)
    return Path(get_workspace_root()) / ".runtime" / "harnesses" / harness_id


def managed_argv(harness_id: str) -> list[str] | None:
    spec = descriptor(harness_id)
    root = install_root(harness_id)
    package_root = root / "node_modules" / spec.package
    manifest = package_root / "package.json"
    if not manifest.exists():
        return None
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("name") != spec.package:
        raise ValueError(f"Unexpected package in managed Harness directory: {manifest}")
    binaries = data.get("bin")
    entry = binaries.get(spec.executable) if isinstance(binaries, dict) else binaries
    if not isinstance(entry, str) or not entry:
        raise ValueError(f"Package {spec.package} does not declare {spec.executable}.")
    target = (package_root / entry).resolve()
    if not target.is_relative_to(package_root.resolve()) or not target.is_file():
        raise ValueError(f"Invalid Harness executable: {target}")
    if target.suffix in {".js", ".mjs", ".cjs"}:
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Node.js is required to run this Harness.")
        return [node, str(target)]
    return [str(target)]


def resolve_command(harness_id: str, command: str = "") -> str:
    """Existing SDK/app-server consumers accept an executable, not argv."""
    spec = descriptor(harness_id)
    if command and command != spec.executable:
        return command
    if managed_argv(harness_id):
        root = install_root(harness_id) / "node_modules" / ".bin"
        path = root / (spec.executable + (".cmd" if os.name == "nt" else ""))
        if not path.is_file():
            raise RuntimeError(f"Managed Harness launcher is missing: {path}")
        return str(path)
    return spec.executable


def command_argv(harness_id: str) -> list[str]:
    if descriptor(harness_id).installation == "hermes-python":
        from .hermes_installation import command
        return command(install_root(harness_id))
    managed = managed_argv(harness_id)
    if managed:
        return managed
    spec = descriptor(harness_id)
    executable = shutil.which(spec.executable)
    if not executable:
        raise RuntimeError(f"{spec.name} is not installed. Install it in Settings → Harness.")
    if Path(executable).suffix.lower() in {".cmd", ".bat", ".ps1"}:
        target = package_entry(harness_id, external_npm_installation(harness_id, executable))
        if target.suffix in {".js", ".mjs", ".cjs"}:
            node = shutil.which("node")
            if not node:
                raise RuntimeError("Node.js is required.")
            return [node, str(target)]
        return [str(target)]
    return [executable]


def check_installation(harness_id: str, *, include_updates: bool = False) -> dict:
    spec = descriptor(harness_id)
    result = {**asdict(spec), "status": "missing", "version": "", "source": "none",
              "executable_path": "", "error": "", "can_uninstall": False,
              "can_upgrade": False, "upgrade_error": "", **asdict(HarnessUpdate())}
    with _LOCK:
        if harness_id in _MUTATING:
            return {**result, "status": "busy"}
    try:
        with runtime_lease(harness_id):
            if spec.installation == "hermes-python":
                from .hermes_installation import check
                return {**asdict(spec), **check(install_root(harness_id), include_updates=include_updates)}
            managed = (install_root(harness_id) / "node_modules" / spec.package / "package.json").exists()
            external = shutil.which(spec.executable)
            if not managed and not external:
                return result
            result.update(source="managed" if managed else "external", can_uninstall=managed)
            argv = command_argv(harness_id)
            result["executable_path"] = argv[-1]
            version = run_process([*argv, "--version"], cwd=get_workspace_root(), timeout=20).strip()
            if not version:
                raise ValueError("Harness --version returned no version.")
            result.update(status="ready", version=version[:300])
            update_root = install_root(harness_id)
            try:
                installation = upgrade_installation(harness_id, update_root)
                update_root = installation.package_base
                result["package"] = installation.package
                result["can_upgrade"] = True
            except (OSError, ValueError, RuntimeError) as exc:
                result["upgrade_error"] = str(exc)
            if include_updates and result["can_upgrade"]:
                result.update(check_updates(harness_id, update_root, result, cwd=get_workspace_root()))
            elif include_updates:
                # Without a verified distribution, an upstream release is not
                # evidence of an update for this external executable.
                result.update(update_status="error", update_error=result["upgrade_error"])
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        result.update(status="error", error=str(exc))
    return result


@contextmanager
def runtime_lease(harness_id: str):
    descriptor(harness_id)
    with _LOCK:
        if harness_id in _MUTATING:
            raise RuntimeError(f"Harness {harness_id} installation is being changed.")
        _ACTIVE[harness_id] = _ACTIVE.get(harness_id, 0) + 1
    try:
        with file_lease(install_root(harness_id).parent / f"{harness_id}.lock", exclusive=False):
            yield
    finally:
        with _LOCK:
            _ACTIVE[harness_id] -= 1


def mutate_installation(harness_id: str, action: str) -> dict:
    with file_lease(install_root(harness_id).parent / f"{harness_id}.lock", exclusive=True):
        output = _mutate_installation(harness_id, action)
    status = check_installation(harness_id)
    if action in {"install", "upgrade"} and status["status"] != "ready":
        raise RuntimeError(f"Installation verification failed: {status['error'] or status['status']}")
    return {"harness": status, "output": output[-12000:]}


def _mutate_installation(harness_id: str, action: str) -> str:
    spec = descriptor(harness_id)
    if action not in {"install", "upgrade", "uninstall"}:
        raise ValueError(f"Unknown Harness operation: {action}")
    with _LOCK:
        if harness_id in _MUTATING or _ACTIVE.get(harness_id, 0):
            raise RuntimeError(f"Harness {harness_id} is busy; stop its nodes before changing its installation.")
        _MUTATING.add(harness_id)
    try:
        if spec.installation == "hermes-python":
            from .hermes_installation import mutate
            return mutate(install_root(harness_id), action)
        root = install_root(harness_id)
        installation = NpmInstallation(root, root, False, spec.package)
        target = "latest"
        if action == "upgrade":
            installation = upgrade_installation(harness_id, root)
            # Recheck under the exclusive lease: another client may have updated since the UI check.
            argv = command_argv(harness_id)
            version = run_process([*argv, "--version"], cwd=get_workspace_root(), timeout=20).strip()
            current = installed_version(harness_id, installation.package_base, version,
                                        package=installation.package)
            target = latest_version(installation.package, str(installation.prefix))
            if version_key(target) <= version_key(current):
                raise ValueError(f"No newer release is available (installed {current}, latest {target}).")
        # Persistent native clients must release executable handles before npm replaces files.
        if harness_id == "codex":
            from nodes.codex_node.runtime.session_manager import CodexSessionManager
            if CodexSessionManager._instance is not None:
                CodexSessionManager._instance.close_all()
        if harness_id == "claude":
            from nodes.claude_node.runtime.session_manager import ClaudeSessionManager
            if ClaudeSessionManager._instance is not None:
                ClaudeSessionManager._instance.close_all()
                ClaudeSessionManager._instance = None
        if action == "uninstall" and not (root / "node_modules" / spec.package / "package.json").exists():
            raise ValueError("Only installations owned by AgentPark can be uninstalled here.")
        installation.prefix.mkdir(parents=True, exist_ok=True)
        args = [*npm_argv(), "uninstall" if action == "uninstall" else "install",
                *installation.scope_args(), "--no-audit", "--no-fund"]
        if action in {"install", "upgrade"}:
            args += ["--save-exact", "--engine-strict", installation.package + "@" + target]
        else:
            args += [spec.package]
        output = run_process(args, cwd=str(installation.prefix), timeout=900)
        if action == "upgrade":
            actual = installed_version(harness_id, installation.package_base, "", package=installation.package)
            if actual != target:
                raise RuntimeError(f"Upgrade verification failed: expected {target}, found {actual}.")
    finally:
        with _LOCK:
            _MUTATING.remove(harness_id)
    return output

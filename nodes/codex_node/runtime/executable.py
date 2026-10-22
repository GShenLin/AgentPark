"""Resolve the selected Codex installation to its native executable."""
from __future__ import annotations

import json
import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path

from src.harness.installation import external_npm_installation


@dataclass(frozen=True)
class CodexExecutable:
    path: str
    package_root: str = ""

    def environment(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.package_root:
            for name in ("NPM", "BUN", "PNPM", "VITE_PLUS"):
                env.pop(f"CODEX_MANAGED_BY_{name}", None)
            env.update(CODEX_MANAGED_PACKAGE_ROOT=self.package_root, CODEX_MANAGED_BY_NPM="1")
        return env


def resolve_executable(command: str) -> CodexExecutable:
    raw = str(command or "codex").strip() or "codex"
    explicit = any(separator in raw for separator in ("/", "\\"))
    if explicit:
        selected = os.path.abspath(os.path.expanduser(raw))
        if not os.path.isfile(selected):
            raise ValueError(f"Codex command does not exist: {selected}")
    else:
        selected = shutil.which(raw)
        if not selected or _windows_apps(selected):
            raise ValueError("Cannot find a launchable Codex command; configure a standalone executable or install the Codex CLI.")
    if _windows_apps(selected):
        raise ValueError("Codex command is a WindowsApps package executable; configure a standalone Codex CLI executable.")
    if os.name != "nt" or Path(selected).suffix.lower() == ".exe":
        return CodexExecutable(selected)
    if Path(selected).name.lower() != "codex.cmd":
        raise ValueError("Codex requires a native executable or the official npm codex.cmd entry point.")
    return _npm_executable(Path(selected))


def _npm_executable(shim: Path) -> CodexExecutable:
    installation = external_npm_installation("codex", str(shim))
    modules_root = installation.package_base / "node_modules"
    root = modules_root / "@openai" / "codex"
    manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
    if manifest.get("name") != "@openai/codex" or manifest.get("bin", {}).get("codex") != "bin/codex.js":
        raise ValueError(f"Not an official Codex npm installation: {root}")
    architecture = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
    if architecture is None:
        raise ValueError(f"Unsupported Codex Windows architecture: {platform.machine()}")
    package = f"codex-win32-{architecture}"
    triple = "x86_64-pc-windows-msvc" if architecture == "x64" else "aarch64-pc-windows-msvc"
    # The two Node package resolution locations supported by the npm layout.
    for modules in (root / "node_modules", modules_root):
        dependency = modules / "@openai" / package
        if (dependency / "package.json").is_file():
            executable = dependency / "vendor" / triple / "bin" / "codex.exe"
            if not executable.is_file():
                raise ValueError(f"Codex platform package is missing its executable: {executable}")
            return CodexExecutable(str(executable), str(root.resolve()))
    raise ValueError(f"Codex npm installation is missing @openai/{package}; reinstall the CLI.")


def _windows_apps(path: str) -> bool:
    return os.name == "nt" and "\\windowsapps\\" in os.path.abspath(path).replace("/", "\\").casefold()

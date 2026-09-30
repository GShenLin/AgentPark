"""Registry update checks and strict SemVer precedence, independent of runtime health."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Literal

from .npm import npm_argv
from .process import run_process
from .registry import descriptor

_NUMBER = r"(?:0|[1-9][0-9]*)"
_PRE = rf"(?:{_NUMBER}|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
_SEMVER = rf"({_NUMBER})\.({_NUMBER})\.({_NUMBER})(?:-({_PRE}(?:\.{_PRE})*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
_CLI_FORMATS = {
    "codex": rf"codex-cli (?P<version>{_SEMVER})",
    "claude": rf"(?P<version>{_SEMVER}) \(Claude Code\)",
    "openclaw": rf"OpenClaw (?P<version>{_SEMVER})(?: \([0-9a-f]+\))?",
    "deepseek_harness": rf"(?P<version>{_SEMVER})",
    "minimax_code": rf"(?P<version>{_SEMVER})",
    "pi": rf"(?P<version>{_SEMVER})",
}


@dataclass(frozen=True)
class HarnessUpdate:
    installed_version: str = ""
    latest_version: str = ""
    update_status: Literal["unchecked", "available", "current", "error"] = "unchecked"
    update_error: str = ""


def version_key(version: str) -> tuple:
    """SemVer 2.0 precedence: numeric components, prerelease identifiers, no build metadata."""
    match = re.fullmatch(_SEMVER, version) if isinstance(version, str) else None
    if not match:
        raise ValueError(f"Invalid package semantic version: {version!r}")
    major, minor, patch, prerelease, _ = match.groups()
    identifiers = tuple((0, int(item)) if item.isascii() and item.isdigit() else (1, item)
                        for item in prerelease.split(".")) if prerelease else ()
    return (int(major), int(minor), int(patch), 0 if prerelease else 1, identifiers)


def installed_version(harness_id: str, root: Path, cli_version: str, *, package: str) -> str:
    spec = descriptor(harness_id)
    manifest = root / "node_modules" / package / "package.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("name") != package:
            raise ValueError(f"Unexpected Harness package manifest: {manifest}")
        version = data.get("version")
        version_key(version)
        return version
    match = re.fullmatch(_CLI_FORMATS[harness_id], cli_version.strip())
    if not match:
        raise ValueError(f"Unrecognized {spec.name} version output: {cli_version!r}")
    return match.group("version")


def latest_version(package: str, cwd: str) -> str:
    output = run_process(
        [*npm_argv(), "view", package + "@latest", "version", "--json",
         "--prefer-online", "--fetch-retries=0", "--fetch-timeout=15000"],
        cwd=cwd, timeout=20,
    )
    version = json.loads(output)
    version_key(version)
    return version


def check_updates(harness_id: str, root: Path, info: dict, *, cwd: str) -> dict:
    current = latest = ""
    try:
        current = installed_version(harness_id, root, info["version"], package=info["package"])
        latest = latest_version(info["package"], str(root) if root.exists() else cwd)
        state = "available" if version_key(latest) > version_key(current) else "current"
        return asdict(HarnessUpdate(current, latest, state))
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        return asdict(HarnessUpdate(current, latest, "error", str(exc)))

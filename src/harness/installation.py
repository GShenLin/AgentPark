"""Identify the active npm installation from its launcher, never npm's default prefix."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil

from .registry import descriptor


@dataclass(frozen=True)
class NpmInstallation:
    prefix: Path
    package_base: Path
    global_install: bool

    def scope_args(self) -> list[str]:
        return ["--global" if self.global_install else "--global=false", "--prefix", str(self.prefix)]


def package_entry(harness_id: str, installation: NpmInstallation) -> Path:
    spec = descriptor(harness_id)
    root = installation.package_base / "node_modules" / spec.package
    # npm link and pnpm's linked stores are not owned by the inferred prefix.
    if root.resolve() != installation.package_base.resolve() / "node_modules" / spec.package:
        raise ValueError(f"Cannot upgrade linked Harness package in place: {root}")
    manifest = root / "package.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("name") != spec.package:
        raise ValueError(f"Unexpected Harness package manifest: {manifest}")
    binaries = data.get("bin")
    entry = binaries.get(spec.executable) if isinstance(binaries, dict) else binaries
    if not isinstance(entry, str) or not entry:
        raise ValueError(f"Package {spec.package} does not declare {spec.executable}.")
    target = (root / entry).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError(f"Invalid Harness executable: {target}")
    return target


def external_npm_installation(harness_id: str, executable: str, *, windows: bool | None = None) -> NpmInstallation:
    """Accept documented npm local/global layouts and validate their declared executable."""
    windows = os.name == "nt" if windows is None else windows
    launcher = Path(executable).absolute()
    parent = launcher.parent
    if parent.name == ".bin" and parent.parent.name == "node_modules":
        prefix = parent.parent.parent
        result = NpmInstallation(prefix, prefix, False)
    elif windows and launcher.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        result = NpmInstallation(parent, parent, True)
    elif not windows and parent.name == "bin" and launcher.is_symlink():
        prefix = parent.parent
        result = NpmInstallation(prefix, prefix / "lib", True)
    else:
        raise ValueError("This external installation is not an identifiable npm installation. "
                         "Update it with its original installer.")
    entry = package_entry(harness_id, result)
    if not windows and launcher.resolve() != entry:
        raise ValueError(f"External Harness launcher does not target its declared npm entry: {launcher}")
    return result


def upgrade_installation(harness_id: str, managed_root: Path) -> NpmInstallation:
    spec = descriptor(harness_id)
    if (managed_root / "node_modules" / spec.package / "package.json").exists():
        return NpmInstallation(managed_root, managed_root, False)
    executable = shutil.which(spec.executable)
    if not executable:
        raise ValueError(f"{spec.name} is not installed.")
    return external_npm_installation(harness_id, executable)

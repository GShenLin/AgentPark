"""Identify the active npm installation from its launcher, never npm's default prefix."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil

from .registry import descriptor

# Explicit distributions sharing the Codex runtime contract. Never infer a package
# to install merely from a command name or the host's platform.
_EXTERNAL_PACKAGES = {"codex": ("@mmmbuto/codex-cli-termux",)}


@dataclass(frozen=True)
class NpmInstallation:
    prefix: Path
    package_base: Path
    global_install: bool
    package: str

    def scope_args(self) -> list[str]:
        return ["--global" if self.global_install else "--global=false", "--prefix", str(self.prefix)]


def package_entry(harness_id: str, installation: NpmInstallation) -> Path:
    spec = descriptor(harness_id)
    root = installation.package_base / "node_modules" / installation.package
    # npm link and pnpm's linked stores are not owned by the inferred prefix.
    if root.resolve() != installation.package_base.resolve() / "node_modules" / installation.package:
        raise ValueError(f"Cannot upgrade linked Harness package in place: {root}")
    manifest = root / "package.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Harness package manifest is missing: {manifest}. "
                         "Repair this installation with its original installer.") from exc
    if not isinstance(data, dict) or data.get("name") != installation.package:
        raise ValueError(f"Unexpected Harness package manifest: {manifest}")
    binaries = data.get("bin")
    entry = binaries.get(spec.executable) if isinstance(binaries, dict) else binaries
    if not isinstance(entry, str) or not entry:
        raise ValueError(f"Package {installation.package} does not declare {spec.executable}.")
    target = (root / entry).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError(f"Invalid Harness executable: {target}")
    return target


def external_npm_installation(harness_id: str, executable: str, *, windows: bool | None = None) -> NpmInstallation:
    """Accept documented npm local/global layouts and validate their declared executable."""
    windows = os.name == "nt" if windows is None else windows
    spec = descriptor(harness_id)
    launcher = Path(executable).absolute()
    parent = launcher.parent
    if parent.name == ".bin" and parent.parent.name == "node_modules":
        prefix = parent.parent.parent
        result = NpmInstallation(prefix, prefix, False, spec.package)
    elif windows and launcher.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        result = NpmInstallation(parent, parent, True, spec.package)
    elif not windows and parent.name == "bin" and launcher.is_symlink():
        prefix = parent.parent
        result = NpmInstallation(prefix, prefix / "lib", True, spec.package)
    else:
        raise ValueError("This external installation is not an identifiable npm installation. "
                         "Update it with its original installer.")
    if not windows:
        # The actual launcher selects the distribution, even when multiple
        # packages declaring the same command coexist in this prefix.
        target = launcher.resolve()
        modules = result.package_base.resolve() / "node_modules"
        packages = (spec.package, *_EXTERNAL_PACKAGES.get(harness_id, ()))
        selected = next((name for name in packages if target.is_relative_to(modules / name)), None)
        if selected is None:
            raise ValueError(f"External Harness launcher does not target a supported npm package: "
                             f"{launcher} -> {target}. Update it with its original installer.")
        result = NpmInstallation(result.prefix, result.package_base, result.global_install, selected)
    entry = package_entry(harness_id, result)
    if not windows and launcher.resolve() != entry:
        raise ValueError(f"External Harness launcher does not target its declared npm entry: {launcher}")
    return result


def upgrade_installation(harness_id: str, managed_root: Path) -> NpmInstallation:
    spec = descriptor(harness_id)
    if (managed_root / "node_modules" / spec.package / "package.json").exists():
        return NpmInstallation(managed_root, managed_root, False, spec.package)
    executable = shutil.which(spec.executable)
    if not executable:
        raise ValueError(f"{spec.name} is not installed.")
    return external_npm_installation(harness_id, executable)

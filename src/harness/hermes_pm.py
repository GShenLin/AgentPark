"""PM-backed Hermes generations: build in isolation, publish only after verification."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

from .hermes_release import HermesRelease, REPOSITORY
from .process import run_process
from .updates import version_key


def environment() -> dict[str, str]:
    # Neither the user's active Hermes profile nor another Python environment
    # may redirect installation identity, dependencies or build provenance.
    return {**{key: value for key, value in os.environ.items()
               if not key.startswith("HERMES_")
               and key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "GITHUB_SHA", "GITHUB_REF_NAME", "GITHUB_HEAD_REF"}},
            "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def generation_paths(root: Path, generation: str) -> tuple[Path, Path]:
    if not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{32}", generation):
        raise ValueError("Invalid managed Hermes generation.")
    directory = root / "versions" / generation
    if directory.resolve() != root.resolve() / "versions" / generation:
        raise ValueError("Managed Hermes generation is redirected outside its owned directory.")
    source, venv = directory / "source", directory / ".venv"
    if source.resolve() != directory.resolve() / "source" or venv.resolve() != directory.resolve() / ".venv":
        raise ValueError("Managed Hermes generation contains redirected paths.")
    return source, venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def selected(root: Path) -> tuple[Path, Path] | None:
    path = root / "current.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"schema", "generation", "version"} or data["schema"] != 1:
        raise ValueError("Invalid managed Hermes installation selection.")
    version_key(data["version"])
    source, python = generation_paths(root, data["generation"])
    if not source.is_dir() or not python.is_file():
        raise ValueError("The selected Hermes generation is incomplete; reinstall Hermes in Settings → Harness.")
    stamp = json.loads((source / "install-stamp.json").read_text(encoding="utf-8"))
    if not isinstance(stamp, dict) or stamp.get("baseVersion") != data["version"]:
        raise ValueError("Selected Hermes version does not match its installation stamp.")
    return source, python


def prepare(root: Path, release: HermesRelease, output: list[str]) -> tuple[str, Path, Path]:
    """Use the release's locked PM build API, with no mutation of the live tree."""
    from .hermes_python import is_android
    if is_android():
        raise ValueError("Hermes PM source installations are not supported on Android/Termux by upstream. "
                         "Use the official hermes-agent APT package; the existing installation is unchanged.")
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git is required to install or upgrade Hermes Agent.")
    generation = uuid.uuid4().hex
    source, python = generation_paths(root, generation)
    source.parent.mkdir(parents=True, exist_ok=False)
    env = environment()
    # One private, hash-verified PM tool store per AgentPark Hermes installation.
    # The upstream stamp records it, so node-specific homes reuse those tools.
    tools = root.resolve() / "tools"
    env.update(HERMES_HOME=str(source.parent / "build-home"), HERMES_RUNTIME_DIR=str(tools))
    output.append(run_process([git, "clone", "-c", "core.longpaths=true", "--depth", "1", "--branch",
                               release.tag, REPOSITORY, str(source)], cwd=str(root), env=env, timeout=600))
    for name in ("pm/build_env.py", "pm/lock.json", "uv.lock", "scripts/write_install_stamp.py"):
        if not (source / name).is_file():
            raise ValueError(f"Hermes {release.tag} is missing its official PM installation contract: {name}")
    output.append(run_process([
        sys.executable, "-X", "utf8", "scripts/write_install_stamp.py", "--output", "install-stamp.json",
        "--base-version", release.version, "--distance", "0", "--update-mechanism", "external",
        "--source", "agentpark", "--runtime-dir", str(tools),
    ], cwd=str(source), env=env, timeout=60))
    output.append(run_process([
        sys.executable, "-X", "utf8", "-m", "pm.build_env", "--source", str(source),
        "--out", str(python.parent.parent),
    ], cwd=str(source), env=env, timeout=1800))
    return generation, source, python


def publish(root: Path, generation: str, version: str) -> None:
    """The pointer is the sole activation boundary; previous generations stay usable."""
    source, python = generation_paths(root, generation)
    if not source.is_dir() or not python.is_file():
        raise ValueError("Cannot activate an incomplete Hermes generation.")
    version_key(version)
    data = {"schema": 1, "generation": generation, "version": version}
    temporary = root / f".current-{uuid.uuid4().hex}.json"
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, root / "current.json")
    finally:
        temporary.unlink(missing_ok=True)

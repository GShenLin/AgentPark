"""Native Android Python installation, without downloading a desktop interpreter."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tomllib

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from .process import run_process


def is_android() -> bool:
    return sys.platform == "android" or hasattr(sys, "getandroidapilevel") or "TERMUX_VERSION" in os.environ


def compatible_python(python: Path, source: Path, requirement: str) -> str:
    candidates = [str(python)] if python.is_file() else [sys.executable]
    if not python.is_file():
        for name in ("python3.13", "python3.12", "python3.11"):
            candidate = shutil.which(name)
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    versions = []
    for interpreter in candidates:
        version = run_process([interpreter, "-c", "import platform; print(platform.python_version())"],
                              cwd=str(source), timeout=20).strip()
        if Version(version) in SpecifierSet(requirement):
            return interpreter
        versions.append(version)
    raise ValueError(f"Hermes requires Python {requirement}, but Android/Termux Python is {', '.join(versions)}. "
                     "Install a compatible native interpreter (TUR provides python3.13), or use a supported Linux environment. "
                     "An existing incompatible virtual environment must be recreated.")


def install_android(python: Path, source: Path, output: list[str]) -> None:
    project = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    requirement = project.get("requires-python")
    if not isinstance(requirement, str) or not requirement:
        raise ValueError("Hermes package does not declare requires-python.")
    interpreter = compatible_python(python, source, requirement)
    constraints = source / "constraints-termux.txt"
    if not constraints.is_file():
        raise ValueError("This Hermes release does not provide constraints-termux.txt for Android installation.")
    if not python.is_file():
        output.append(run_process([interpreter, "-m", "venv", str(python.parent.parent)],
                                  cwd=str(source), timeout=180))
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    env["VIRTUAL_ENV"] = str(python.parent.parent)
    if hasattr(sys, "getandroidapilevel"):
        env["ANDROID_API_LEVEL"] = str(sys.getandroidapilevel())
    output.append(run_process([str(python), "-m", "pip", "install", "setuptools", "wheel"],
                              cwd=str(source), env=env, timeout=300))
    # Use the release's own native dependency preparation, retaining its pinned versions.
    prepare = source / "scripts" / "install_psutil_android.py"
    if sys.platform == "android" and prepare.is_file():
        import shlex
        output.append(run_process([str(python), str(prepare), "--pip", shlex.join([str(python), "-m", "pip"])],
                                  cwd=str(source), env=env, timeout=900))
    output.append(run_process([str(python), "-m", "pip", "install", "-e", str(source), "-c", str(constraints)],
                              cwd=str(source), env=env, timeout=3600))

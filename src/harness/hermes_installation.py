"""Hermes Git/Python lifecycle, isolated from AgentPark's Python dependencies."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tomllib

from .hermes_release import REPOSITORY, latest_release
from .process import run_process
from .updates import HarnessUpdate, version_key

_PROBE = (
    "import json,pathlib,sys; import hermes_cli; "
    "print(json.dumps({'source':str(pathlib.Path(hermes_cli.__file__).resolve().parent.parent),"
    "'version':hermes_cli.__version__,'prefix':sys.prefix}))"
)


def python_path(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _probe(python: Path, cwd: Path) -> dict:
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    data = json.loads(run_process([str(python), "-c", _PROBE], cwd=str(cwd), env=env, timeout=20))
    if not isinstance(data, dict) or not all(isinstance(data.get(key), str) and data[key] for key in ("source", "prefix", "version")):
        raise ValueError("Invalid Hermes environment probe.")
    version_key(data["version"])
    return data


@dataclass(frozen=True)
class HermesInstallation:
    python: Path
    source: Path
    managed: bool


def locate(root: Path) -> HermesInstallation | None:
    if (root / "source").exists() or (root / ".venv").exists():
        return HermesInstallation(python_path(root / ".venv"), root / "source", True)
    executable = shutil.which("hermes")
    if not executable:
        return None
    launcher = Path(executable)
    interpreter = launcher.resolve().parent / ("python.exe" if os.name == "nt" else "python")
    if not interpreter.is_file() and launcher.suffix.lower() == ".cmd":
        # Official relocatable Windows launcher: an exact delegator, not an arbitrary shell script.
        match = re.fullmatch(r'@echo off\s+"([^"\r\n]+[\\/]hermes\.exe)" %\*\s*',
                             launcher.read_text(encoding="utf-8"))
        if match:
            interpreter = Path(match[1]).parent / "python.exe"
    if os.name == "nt" and not interpreter.is_file() and launcher.parent.name == "bin":
        # Official Windows installer stages copied launchers in <HermesHome>/bin.
        interpreter = python_path(launcher.parent.parent / "hermes-agent" / "venv")
    if not interpreter.is_file() and launcher.name == "hermes" and not launcher.is_symlink():
        # Official POSIX installer writes a literal Python+entrypoint wrapper.
        match = re.fullmatch(r'#!/usr/bin/env bash\nunset PYTHONPATH\nunset PYTHONHOME\n'
                             r'exec "([^"\n]+)" "([^"\n]+)" "\$@"\s*',
                             launcher.read_text(encoding="utf-8"))
        if match:
            interpreter = Path(match[1])
            entry = Path(match[2])
            if not interpreter.is_absolute() or not entry.is_absolute() or entry.name != "hermes":
                raise ValueError("Invalid Hermes launcher paths.")
    # Official source installs keep .venv next to hermes; console-script installs keep it beside the launcher.
    if not interpreter.is_file() and launcher.name == "hermes":
        interpreter = python_path(launcher.resolve().parent / ".venv")
    if not interpreter.is_file():
        raise ValueError("Cannot locate the Python environment for external Hermes. Use its original installer.")
    probe = _probe(interpreter, launcher.parent)
    if not (interpreter.parent.parent / "pyvenv.cfg").is_file() or Path(probe["prefix"]).resolve() != interpreter.parent.parent.resolve():
        raise ValueError("External Hermes must use its own virtual environment.")
    return HermesInstallation(interpreter, Path(probe["source"]), False)


def command(root: Path) -> list[str]:
    found = locate(root)
    if not found or not found.python.is_file():
        raise RuntimeError("Hermes Agent is not installed. Install it in Settings → Harness.")
    return [str(found.python)]


def _git(source: Path, *args: str) -> str:
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git is required to install or upgrade Hermes Agent.")
    return run_process([git, "-c", "core.longpaths=true", "-C", str(source), *args], cwd=str(source), timeout=180)


def validate_source(source: Path) -> str:
    if not (source / ".git").is_dir():
        raise ValueError("Hermes upgrades require an official Git checkout; use the original installer for this installation.")
    origin = _git(source, "remote", "get-url", "origin").strip()
    if origin not in {REPOSITORY, REPOSITORY.removesuffix(".git"), "git@github.com:NousResearch/hermes-agent.git"}:
        raise ValueError("Hermes installation does not use the official NousResearch repository.")
    data = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8")).get("project")
    if not isinstance(data, dict) or data.get("name") != "hermes-agent":
        raise ValueError("Unexpected package in Hermes installation.")
    version_key(data.get("version"))
    return data["version"]


def check(root: Path, *, include_updates: bool) -> dict:
    result = {"status": "missing", "source": "none", "version": "", "executable_path": "", "error": "",
              "can_uninstall": root.exists(), "can_upgrade": False, "upgrade_error": "", **asdict(HarnessUpdate())}
    try:
        found = locate(root)
        if found is None:
            return result
        result.update(source="managed" if found.managed else "external", can_uninstall=found.managed,
                      executable_path=str(found.python))
        if not found.python.is_file():
            raise ValueError("Hermes installation is incomplete: its Python environment is missing. "
                             "Reinstall Hermes in Settings → Harness and check the installation output.")
        probe = _probe(found.python, found.source)
        version = probe["version"]
        version_key(version)
        if Path(probe["source"]).resolve() != found.source.resolve():
            raise ValueError("Hermes Python environment points to a different installation.")
        result.update(status="ready", version=version, installed_version=version)
        try:
            validate_source(found.source)
            result["can_upgrade"] = True
        except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
            result["upgrade_error"] = str(exc)
        if include_updates and result["can_upgrade"]:
            try:
                release = latest_release()
                result.update(latest_version=release.version,
                              update_status="available" if version_key(release.version) > version_key(version) else "current")
            except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
                result.update(update_status="error", update_error=str(exc))
        elif include_updates:
            result.update(update_status="error", update_error=result["upgrade_error"])
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        result.update(status="error", error=str(exc))
    return result


def _uv(root: Path, output: list[str]) -> list[str]:
    uv = shutil.which("uv")
    if uv:
        return [uv]
    # Bootstrap only into a dedicated environment; never pip-install into the host application.
    bootstrap = root / ".bootstrap"
    python = python_path(bootstrap)
    if not python.is_file():
        output.append(run_process([sys.executable, "-m", "venv", str(bootstrap)], cwd=str(root), timeout=180))
    uv_binary = python.parent / ("uv.exe" if os.name == "nt" else "uv")
    if not uv_binary.is_file():
        output.append(run_process([str(python), "-m", "pip", "install", "--disable-pip-version-check", "uv"],
                                  cwd=str(root), timeout=300))
    return [str(uv_binary)]


def mutate(root: Path, action: str) -> str:
    if action == "uninstall":
        if not root.exists():
            raise ValueError("Only AgentPark-managed Hermes installations can be uninstalled here.")
        # Never follow an installation-root link outside the owned runtime directory.
        if root.is_symlink() or root.resolve().parent != root.parent.resolve():
            raise ValueError("Refusing to remove a redirected Hermes installation directory.")
        def remove_readonly(function, path, error):
            if not isinstance(error, PermissionError) or not Path(path).resolve().is_relative_to(root.resolve()):
                raise error
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            function(path)
        shutil.rmtree(root, onexc=remove_readonly)
        return "Removed managed Hermes installation. Node sessions and Hermes homes were preserved."
    found = locate(root)
    if action == "upgrade" and found is None:
        raise ValueError("Hermes Agent is not installed.")
    if action == "install" and found and not found.managed:
        raise ValueError("Hermes is already installed externally; use Upgrade to update it in place.")
    output: list[str] = []
    if found:
        current = validate_source(found.source)
    release = latest_release()
    if found:
        if action == "upgrade" and version_key(release.version) <= version_key(current):
            raise ValueError("No newer Hermes release is available.")
        if _git(found.source, "status", "--porcelain").strip():
            raise ValueError("Hermes source has local changes; commit or stash them before upgrading.")
        # Refuse to abandon local commits when moving an external checkout to a release.
        if not found.managed:
            branch = _git(found.source, "branch", "--show-current").strip()
            if branch and _git(found.source, "rev-list", "@{upstream}..HEAD").strip():
                raise ValueError("Hermes has local commits; update it with its original workflow.")
    else:
        root.mkdir(parents=True, exist_ok=True)
        git = shutil.which("git")
        if not git:
            raise RuntimeError("Git is required to install Hermes Agent.")
        output.append(run_process([git, "clone", "-c", "core.longpaths=true", "--depth", "1", "--branch", release.tag, REPOSITORY, str(root / "source")],
                                  cwd=str(root), timeout=600))
        found = HermesInstallation(python_path(root / ".venv"), root / "source", True)
    tooling_root = root if found.managed else root.parent / "hermes-tooling"
    tooling_root.mkdir(parents=True, exist_ok=True)
    output.append(_git(found.source, "fetch", "--depth", "1", "origin", "tag", release.tag))
    output.append(_git(found.source, "checkout", "--detach", release.tag))
    from .hermes_python import is_android, install_android
    if is_android():
        install_android(found.python, found.source, output)
    else:
        uv = _uv(tooling_root, output)
        if not found.python.is_file():
            output.append(run_process([*uv, "venv", "--python", "3.12", str(found.python.parent.parent)],
                                      cwd=str(tooling_root), timeout=600))
        output.append(run_process([*uv, "pip", "install", "--python", str(found.python), "-e", str(found.source)],
                                  cwd=str(found.source), timeout=900))
    probe = _probe(found.python, found.source)
    if probe["version"] != release.version:
        raise RuntimeError(f"Hermes version verification failed: expected {release.version}, got {probe['version']}.")
    # Import the runtime, not just package metadata: catch missing/broken dependencies before reporting success.
    output.append(run_process([str(found.python), "-c", "from run_agent import AIAgent; print('Hermes runtime verified')"],
                              cwd=str(found.source), timeout=90,
                              env={**os.environ, "HERMES_HOME": str(tooling_root / "verify-home"), "PYTHONUTF8": "1"}))
    return "\n".join(output)

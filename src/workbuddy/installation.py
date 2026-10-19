"""Install pinned, separately licensed protocol dependencies outside application source."""
import os
import json
from pathlib import Path
import shutil
import subprocess
from src.file_transaction import atomic_write_text

DSH_REVISION = "736d15e5ef4a3f54a715d646529a447d715da59e"
PROXY_REVISION = "1cc32c9a98abb53796d8d4e8d477736fe1f0c4cc"
DEPENDENCIES = (
    ("dsh-workbuddy", "https://github.com/a2d2-dev/dsh-workbuddy.git", DSH_REVISION),
    ("workbuddy2api", "https://github.com/Zhengyuuuui/workbuddy2api.git", PROXY_REVISION),
)


def python_path(directory: Path) -> Path:
    return directory / "workbuddy2api" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def installed(directory: Path) -> bool:
    marker = directory / "installed.json"
    if not marker.exists() or not python_path(directory).is_file():
        return False
    return json.loads(marker.read_text(encoding="utf-8")) == {name: revision for name, _, revision in DEPENDENCIES}


def install(directory: Path, log_path: Path, run) -> None:
    git, uv = shutil.which("git"), shutil.which("uv")
    if not git or not uv:
        raise RuntimeError("安装 WorkBuddy 服务需要 Git 和 uv，请先安装这两个工具。")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "installed.json").unlink(missing_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        for name, url, revision in DEPENDENCIES:
            checkout = directory / name
            existed = checkout.exists()
            if not existed:
                run([git, "clone", "--no-checkout", "--filter=blob:none", url, str(checkout)], log)
            run([git, "-C", str(checkout), "fetch", "--depth", "1", "origin", revision], log)
            # Refuse to overwrite local edits in an existing dependency checkout.
            changes = subprocess.check_output([git, "-C", str(checkout), "status", "--porcelain"],
                                              text=True, creationflags=_flags(), timeout=10)
            if existed and changes.strip():
                raise RuntimeError(f"依赖目录 {name} 存在本地修改，未覆盖。")
            run([git, "-C", str(checkout), "checkout", "--detach", revision], log)
        run([uv, "sync", "--project", str(directory / "workbuddy2api"), "--no-dev"], log)
    atomic_write_text(str(directory / "installed.json"),
                      json.dumps({name: revision for name, _, revision in DEPENDENCIES}), encoding="utf-8")


def _flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

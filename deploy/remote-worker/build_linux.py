"""Build a native Linux artifact without including user settings or credentials."""
import hashlib
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile


def main():
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise SystemExit("This build targets Linux x86_64; run it on that platform.")
    import tkinter
    tkinter.Tcl()  # Verify Tcl data discovery before starting the build.
    root = Path(__file__).resolve().parents[2]
    output = root / "dist" / "linux-x86_64"
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm",
        "--distpath", str(output), "--workpath", str(root / ".runtime/remote-linux-build"),
        str(root / "AgentParkRemote.spec"),
    ], cwd=root, check=True)
    executable = output / "AgentParkRemote"
    executable.chmod(0o755)
    shutil.copyfile(Path(__file__).with_name("README-linux.md"), output / "README.md")
    (output / "build-info.txt").write_text(
        f"Platform: Linux x86_64\nPython: {platform.python_version()}\n"
        f"C library: {' '.join(platform.libc_ver())}\n", encoding="utf-8")
    archive = root / "dist/AgentParkRemote-linux-x86_64.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for name in ("AgentParkRemote", "README.md", "build-info.txt"):
            bundle.add(output / name, arcname=f"AgentParkRemote-linux-x86_64/{name}")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(archive.suffix + ".sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"Built {archive}\nSHA256 {digest}")


if __name__ == "__main__":
    main()

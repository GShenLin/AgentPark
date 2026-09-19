"""Legacy DOC conversion runs in its own process/profile, never in the server."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time

from .document_types import DocumentError
from .scanner import check_stop


def converter_path():
    configured = os.environ.get("AGENTPARK_LIBREOFFICE", "")
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise DocumentError("AGENTPARK_LIBREOFFICE 指向的程序不存在")
        return str(path)
    found = shutil.which("soffice")
    if found:
        return found
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base:
                path = Path(base) / "LibreOffice/program/soffice.com"
                if path.is_file():
                    return str(path)
    raise DocumentError("旧版 .doc 需要 LibreOffice；安装后重试，或设置 AGENTPARK_LIBREOFFICE 为 soffice 可执行文件路径")


@contextmanager
def converted_doc(path, stop):
    executable = converter_path()
    with TemporaryDirectory(prefix="agentpark-word-") as directory:
        root = Path(directory)
        profile = root / "profile"
        (profile / "user").mkdir(parents=True)
        (profile / "user/registrymodifications.xcu").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            '</item></oor:items>', encoding="utf-8")
        # Copy the input: the converter cannot alter the user's original file.
        source = root / "source.doc"
        shutil.copyfile(path, source)
        output = root / "output"
        output.mkdir()
        with (root / "conversion.log").open("wb") as log:
            process = subprocess.Popen([
                executable, f"-env:UserInstallation={profile.as_uri()}", "--headless",
                "--nologo", "--nodefault", "--norestore", "--convert-to", "docx",
                "--outdir", str(output), str(source),
            ], stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                deadline = time.monotonic() + 120
                while process.poll() is None:
                    check_stop(stop)
                    if time.monotonic() >= deadline:
                        raise DocumentError("DOC 转换超过 120 秒")
                    stop.wait(0.1)
                target = output / "source.docx"
                if process.returncode != 0 or not target.is_file():
                    raise DocumentError(f"DOC 转换失败（exit={process.returncode}）；请检查文档是否损坏或加密")
                yield target
            finally:
                if process.poll() is None:
                    if os.name == "nt":
                        # Only the process tree created above; never stop an existing
                        # Office session or another application instance.
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW, check=True)
                    else:
                        process.kill()
                    process.wait(timeout=10)

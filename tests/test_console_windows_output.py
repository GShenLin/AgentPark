import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from functions.console_tools import execute_console_command


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell integration")


@pytest.mark.parametrize("suffix,code,stderr", [
    ("", 0, ""),
    ("; exit 7", 7, ""),
    ("; & cmd /c exit 9", 9, ""),
    ("; & cmd /c exit 9; Write-Output 'after native'", 9, ""),
    ("; & cmd /c exit 9; if ($LASTEXITCODE -eq 9) { exit 0 }", 0, ""),
    ("; throw 'intentional failure'", 1, "intentional failure"),
    ("; Write-Error 'cmdlet failure'; Write-Output 'must not run'", 1, "cmdlet failure"),
])
def test_formatted_objects_and_utf8_survive_all_exit_paths(tmp_path, suffix, code, stderr):
    working = tmp_path / "含 空格"
    working.mkdir()
    (working / "AGENTS.md").write_text("项目说明\n", encoding="utf-8")
    agent = SimpleNamespace(config={"working_path": str(working)})
    result = json.loads(execute_console_command(
        "Get-Location; Get-ChildItem -Name; Get-Content -Encoding UTF8 AGENTS.md; Write-Output '中文尾部'" + suffix,
        agent=agent,
    ))
    assert result["returncode"] == code
    assert result["status"] == ("success" if code == 0 else "error")
    for text in (str(working), "AGENTS.md", "项目说明", "中文尾部"):
        assert text in result["stdout"]
    assert stderr in result["stderr"]
    assert "must not run" not in result["stdout"]


def test_native_stderr_and_explicit_stdout_are_separate():
    command = f"& '{sys.executable}' -c \"import sys; print('中文'); print('错误',file=sys.stderr); sys.exit(23)\""
    result = json.loads(execute_console_command(command))
    assert result["returncode"] == 23
    assert result["stdout"].strip() == "中文"
    assert "错误" in result["stderr"]


def test_launch_script_is_removed_after_execution(monkeypatch):
    import functions.console_tools as module
    real = module.ConsoleLaunch
    paths = []

    def record(command):
        launch = real(command)
        paths.append(Path(launch.directory.name))
        return launch

    monkeypatch.setattr(module, "ConsoleLaunch", record)
    execute_console_command("Get-Location; exit 5")
    assert paths and not paths[0].exists()

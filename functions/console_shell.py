"""Prepare a shell invocation and own its temporary script until the process exits."""

import os
from pathlib import Path
import tempfile

from src.runtime_environment import get_runtime_environment


class ConsoleLaunch:
    def __init__(self, command: str):
        environment = get_runtime_environment()
        child_env = {**os.environ, **environment.variables()}
        self.directory = None
        self.options = {"env": child_env}
        if not environment.is_windows:
            self.argv = [environment.shell_executable, "-c", command]
            self.options["start_new_session"] = True
            return
        self.directory = tempfile.TemporaryDirectory(prefix="agentpark-console-")
        try:
            script = Path(self.directory.name) / "command.ps1"
            # A script-file boundary makes explicit exit return to the caller, allowing
            # Out-Default to drain its deferred formatting before the host exits.
            script.write_text(
                "try {\n" + command + "\n"
                "if (-not $?) { if ($LASTEXITCODE) { exit $LASTEXITCODE }; exit 1 }\n"
                "if ($LASTEXITCODE) { exit $LASTEXITCODE }\n"
                "} catch { [Console]::Error.WriteLine($_.ToString()); exit 1 }\n",
                encoding="utf-8-sig",  # Windows PowerShell requires BOM for UTF-8 files.
            )
            quoted_path = str(script).replace("'", "''")
            wrapper = (
                "$__AgentParkUtf8 = [System.Text.UTF8Encoding]::new($false); "
                "[Console]::InputEncoding = $__AgentParkUtf8; "
                "[Console]::OutputEncoding = $__AgentParkUtf8; "
                "$OutputEncoding = $__AgentParkUtf8; "
                "$ErrorActionPreference = 'Stop'; $LASTEXITCODE = 0; "
                f"& '{quoted_path}' | Out-Default; "
                "$__AgentParkOk = $?; "
                "if ($LASTEXITCODE) { exit $LASTEXITCODE }; "
                "if (-not $__AgentParkOk) { exit 1 }; exit 0"
            )
            self.argv = [environment.shell_executable, "-NoProfile", "-NonInteractive", "-Command", wrapper]
            self.options["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.directory is not None:
            self.directory.cleanup()

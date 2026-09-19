"""Resolve npm without invoking a shell, including Windows npm shims."""
from __future__ import annotations

import os
from pathlib import Path
import shutil


def npm_argv() -> list[str]:
    npm = shutil.which("npm")
    node = shutil.which("node")
    if not npm or not node:
        raise RuntimeError("Install Node.js and npm before managing Harness packages.")
    if os.name != "nt":
        return [npm]
    cli = Path(npm).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if not cli.is_file():
        raise RuntimeError(f"Cannot locate npm-cli.js beside {npm}.")
    return [node, str(cli)]

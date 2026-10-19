"""Read the model identifiers exposed by the installed official CLI."""
from __future__ import annotations

import re

from .install_manager import command_argv, install_root, runtime_lease
from .process import run_process


def list_models() -> list[str]:
    with runtime_lease("opencode"):
        root = install_root("opencode")
        root.mkdir(parents=True, exist_ok=True)
        output = run_process([*command_argv("opencode"), "models", "--standalone"],
                             cwd=str(root), timeout=60)
    models = output.splitlines()
    if not models or len(models) != len(set(models)) or any(
            re.fullmatch(r"[^\s/]+/[^\s]+", model) is None for model in models):
        raise ValueError("OpenCode models returned an invalid model catalog.")
    return models

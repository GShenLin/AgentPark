"""Read the authenticated model directory from the official CLI, without aliases."""
from __future__ import annotations

import re

from .install_manager import command_argv, install_root, runtime_lease
from .process import run_process


def list_models() -> list[str]:
    with runtime_lease("antigravity"):
        root = install_root("antigravity")
        root.mkdir(parents=True, exist_ok=True)
        output = run_process([*command_argv("antigravity"), "models"], cwd=str(root), timeout=60)
    models = []
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or not fields[1].strip() or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", fields[0]) is None:
            raise ValueError("Antigravity models returned an invalid model catalog.")
        models.append(fields[0])
    if not models or len(models) != len(set(models)):
        raise ValueError("Antigravity returned an empty or duplicate model catalog.")
    return models

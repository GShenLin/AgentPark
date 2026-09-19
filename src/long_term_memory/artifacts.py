"""Immutable publication files, with bounded cleanup inside the node-owned directory."""
from pathlib import Path
import re
import shutil


def prune_generations(root: Path, keep: str | None) -> None:
    base = root / "generations"
    if not base.exists():
        return
    if base.is_symlink() or not base.resolve().is_relative_to(root.resolve()):
        raise ValueError("memory generations directory escapes node memory root")
    for folder in base.iterdir():
        if folder.name == keep:
            continue
        if not re.fullmatch(r"[a-f0-9]{64}-[a-f0-9]{32}", folder.name):
            raise ValueError("unexpected entry in generated memory artifacts")
        if folder.is_symlink() or not folder.resolve().is_relative_to(base.resolve()):
            raise ValueError("memory artifact escapes its generation directory")
        shutil.rmtree(folder)

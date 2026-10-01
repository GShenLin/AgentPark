"""Directory data only: the initiating browser owns the folder picker UI."""
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DirectoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = ""


class DirectoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str
    path: str
    type: Literal["dir"] = "dir"


class DirectoryListing(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    current_path: str
    parent_path: str | None
    files: list[DirectoryEntry] = Field(max_length=10000)
    roots: list[DirectoryEntry]


def list_directories(arguments: dict, workspace: str) -> str:
    query = DirectoryQuery.model_validate(arguments)
    raw = query.path.strip() or workspace
    if not os.path.isabs(raw):
        raise ValueError("Remote directory path must be absolute on the target machine.")
    path = Path(os.path.abspath(raw))
    if not path.is_dir():
        raise ValueError(f"Remote directory does not exist: {path}")
    entries = []
    with os.scandir(path) as children:
        for child in children:
            if child.is_dir():
                entries.append(DirectoryEntry(name=child.name, path=child.path))
                if len(entries) > 10000:
                    raise ValueError("Directory contains too many subfolders; enter a more specific path.")
    roots = [Path(f"{letter}:\\") for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
             if os.path.isdir(f"{letter}:\\")] if os.name == "nt" else [Path("/")]
    listing = DirectoryListing(
        current_path=str(path), parent_path=str(path.parent) if path.parent != path else None,
        files=sorted(entries, key=lambda item: item.name.casefold()),
        roots=[DirectoryEntry(name=str(root), path=str(root)) for root in roots],
    )
    return listing.model_dump_json()

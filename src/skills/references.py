"""Read only the configuration locations that can select project skills."""
from __future__ import annotations

import json
import os
from pathlib import Path

from src.name_lists import path_reference_key


def skill_references(workspace: Path, memories: Path) -> dict[str, list[str]]:
    documents = [*sorted((workspace / "agent").glob("*.json")),
                 *sorted((workspace / "graph").glob("*.json")),
                 *sorted(memories.glob("*/*/config.json"))]
    references: dict[str, list[str]] = {}

    def visit(value: object, location: str) -> None:
        if isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{location}[{index}]")
        elif isinstance(value, dict):
            for key, child in value.items():
                if key == "skills":
                    if not isinstance(child, list) or not all(isinstance(item, str) for item in child):
                        raise ValueError(f"Skill 引用格式错误：{location}.skills")
                    for item in child:
                        reference = path_reference_key(item.strip())
                        references.setdefault(reference, []).append(location)
                elif isinstance(child, (dict, list)):
                    visit(child, f"{location}.{key}")

    for document in documents:
        label = os.path.relpath(document, workspace).replace(os.sep, "/")
        try:
            value = json.loads(document.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError(f"无法检查 Skill 引用：{label}: {exc}") from exc
        visit(value, label)
    return references


def references_under(references: dict[str, list[str]], path: str) -> list[str]:
    target = os.path.normcase(path).replace("\\", "/")
    return sorted({location for key, locations in references.items()
                   if (normalized := os.path.normcase(key).replace("\\", "/")) == target
                   or normalized.startswith(target + "/") for location in locations})

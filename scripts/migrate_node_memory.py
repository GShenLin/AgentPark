"""Explicit one-time retirement of old memory writers and injection rules.

Run from the workspace: python -m scripts.migrate_node_memory --apply
Without --apply, list only the files that would change. Original histories are untouched.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from src.file_transaction import atomic_write_text

WRITERS = {"MemoryHobbitWriter", "MemoryNoteWriter", "MemorySoulWriter"}
OLD_FILES = {"note.md", "hobbit.md", "soul.md", "memory.md"}
COMPANION_PROMPT = """You are AgentPark Companion. Review persisted runs and direct user requests using concrete evidence.
Reconstruct tool calls, tool results, and final answers. Distinguish verified outcomes, attempts, and uncertainty.
Identify actionable improvements to environment, project code, and answer quality. Do not write a separate report unless asked.
Each node maintains its own long-term memory through extraction and consolidation. Do not edit another node's memory.
Do not hide defects through swallowed errors, default-value masking, loose protocols, or heuristic shortcuts."""


def migrate(value):
    if isinstance(value, list):
        return [item for raw in value if (item := migrate(raw)) is not None]
    if not isinstance(value, dict):
        return value
    result = {key: migrate(item) for key, item in value.items()}
    params = result.get("params", {})
    if result.get("action") == "node.dispatch" and isinstance(params.get("profile_ids"), list):
        params["profile_ids"] = [p for p in params["profile_ids"] if p not in WRITERS]
        if not params["profile_ids"]:
            return None
    if result.get("action") == "context.append_file" and isinstance(params.get("paths"), list):
        params["paths"] = [p for p in params["paths"] if Path(p).name.lower() not in OLD_FILES]
        if not params["paths"]:
            return None
    if isinstance(result.get("tools"), list):
        result["tools"] = [t for t in result["tools"] if t != "operational_memory_tools"]
    if isinstance(result.get("system_prompt"), str) and "You are AgentPark Companion." in result["system_prompt"]:
        result["system_prompt"] = COMPANION_PROMPT
    if isinstance(result.get("system_prompt_append"), str):
        result["system_prompt_append"] = result["system_prompt_append"].replace(
            "- Do not persist speculative operational memory from a failed schema or asset-path experiment unless the follow-up call confirms the rule. If recording operational memory, include the required `reason` argument.",
            "- Treat failed schema or asset-path experiments as attempts. Record a reusable rule only after a follow-up call confirms it, with the supporting evidence.",
        )
    if result.get("id") == "Companion" and isinstance(result.get("description"), str):
        result["description"] = "审阅节点的持久化运行记录与失败通知，基于证据提出改进；各节点独立维护长期记忆。"
    return result


def main():
    from src.web_backend.runtime_paths import _get_graphs_dir
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    paths = list((root / "agent").glob("*.json")) + [root / "config" / "events.json"]
    paths += list(Path(_get_graphs_dir()).glob("*/*/config.json"))
    changed = []
    for path in paths:
        original = json.loads(path.read_text(encoding="utf-8-sig"))
        updated = migrate(copy.deepcopy(original))
        if original != updated:
            if args.apply:
                atomic_write_text(str(path), json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
            changed.append(str(path))
    print(json.dumps({"applied": args.apply, "changed": changed}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

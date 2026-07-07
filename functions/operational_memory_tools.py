import json

from src.operational_memory import OperationalMemoryError
from src.operational_memory import record_operational_memory_entry


def edit_operational_memory(
    memory_path,
    action,
    reason,
    kind="",
    title="",
    lesson="",
    evidence="",
    scope=None,
    tool_name="",
    error="",
    command="",
    conclusion="",
    avoid=None,
    prefer=None,
    confidence="medium",
    key="",
    resolve_key="",
    memories=None,
):
    path = str(memory_path or "").strip()
    if not path:
        return json.dumps(
            {"status": "error", "error": "memory_path is required", "tool": "edit_operational_memory"},
            ensure_ascii=False,
        )
    try:
        result = record_operational_memory_entry(
            path=path,
            action=action,
            reason=reason,
            kind=kind,
            title=title,
            lesson=lesson,
            evidence=evidence,
            scope=scope if isinstance(scope, dict) else {},
            tool_name=tool_name,
            error=error,
            command=command,
            conclusion=conclusion,
            avoid=avoid if isinstance(avoid, list) else [],
            prefer=prefer if isinstance(prefer, list) else [],
            confidence=confidence,
            key=key,
            resolve_key=resolve_key,
            memories=memories if isinstance(memories, dict) else None,
        )
        result["path"] = path
        return json.dumps(result, ensure_ascii=False)
    except OperationalMemoryError as exc:
        return json.dumps(
            {"status": "error", "error": str(exc), "tool": "edit_operational_memory", "path": path},
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps(
            {
                "status": "exception",
                "error": f"{type(exc).__name__}: {exc}",
                "tool": "edit_operational_memory",
                "path": path,
            },
            ensure_ascii=False,
        )


edit_operational_memory_declaration = {
    "type": "function",
    "function": {
        "name": "edit_operational_memory",
        "description": (
            "Edit the exact operational_memory.json file named in a Companion notice. "
            "Use this for reusable node-behavior corrections from tool-failure or persisted-run review notices. "
            "The active memory summary is injected into "
            "future model input for that node, so keep entries compact and high signal."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "memory_path": {
                    "type": "string",
                    "description": "Exact operational_memory.json path to edit. Use the path from the Companion notice.",
                },
                "action": {
                    "type": "string",
                    "enum": ["upsert", "replace", "skip", "resolve"],
                    "description": "Use skip when no durable memory should be recorded.",
                },
                "reason": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["environment_fact", "tool_limitation", "repo_convention", "bad_pattern", "recovery_strategy"],
                },
                "title": {"type": "string"},
                "lesson": {
                    "type": "string",
                    "description": "Short reusable correction. Keep it concise because it can enter future model context.",
                },
                "evidence": {"type": "string"},
                "scope": {
                    "type": "object",
                    "description": "Scope where the lesson applies, such as project, node_id, graph_id, platform, shell, or tool.",
                    "additionalProperties": True,
                },
                "tool_name": {"type": "string"},
                "error": {"type": "string"},
                "command": {"type": "string"},
                "conclusion": {"type": "string"},
                "avoid": {"type": "array", "items": {"type": "string"}},
                "prefer": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                "key": {"type": "string"},
                "resolve_key": {"type": "string"},
                "memories": {
                    "type": "object",
                    "description": "For action=replace, the corrected full memories object keyed by memory key.",
                    "additionalProperties": True,
                },
            },
            "required": ["memory_path", "action", "reason"],
            "oneOf": [
                {
                    "properties": {"action": {"enum": ["upsert"]}},
                    "required": [
                        "memory_path",
                        "action",
                        "reason",
                        "kind",
                        "title",
                        "lesson",
                        "evidence",
                        "scope",
                        "confidence",
                    ],
                },
                {
                    "properties": {"action": {"enum": ["replace"]}},
                    "required": ["memory_path", "action", "reason", "memories"],
                },
                {
                    "properties": {"action": {"enum": ["resolve"]}},
                    "required": ["memory_path", "action", "reason"],
                    "anyOf": [{"required": ["key"]}, {"required": ["resolve_key"]}],
                },
                {
                    "properties": {"action": {"enum": ["skip"]}},
                    "required": ["memory_path", "action", "reason"],
                },
            ],
            "additionalProperties": False,
        },
    },
}

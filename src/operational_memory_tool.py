import json

from src.operational_memory import OperationalMemoryError
from src.operational_memory import operational_memory_path_for_agent
from src.operational_memory import record_operational_memory_entry


def record_operational_memory(
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
    agent=None,
):
    try:
        path = operational_memory_path_for_agent(agent)
        arguments = {
            "action": action,
            "reason": reason,
            "kind": kind,
            "title": title,
            "lesson": lesson,
            "evidence": evidence,
            "scope": scope if isinstance(scope, dict) else {},
            "tool_name": tool_name,
            "error": error,
            "command": command,
            "conclusion": conclusion,
            "avoid": avoid if isinstance(avoid, list) else [],
            "prefer": prefer if isinstance(prefer, list) else [],
            "confidence": confidence,
            "key": key,
            "resolve_key": resolve_key,
            "memories": memories if isinstance(memories, dict) else None,
        }
        result = record_operational_memory_entry(
            path=path,
            action=arguments["action"],
            reason=arguments["reason"],
            kind=arguments["kind"],
            title=arguments["title"],
            lesson=arguments["lesson"],
            evidence=arguments["evidence"],
            scope=arguments["scope"],
            tool_name=arguments["tool_name"],
            error=arguments["error"],
            command=arguments["command"],
            conclusion=arguments["conclusion"],
            avoid=arguments["avoid"],
            prefer=arguments["prefer"],
            confidence=arguments["confidence"],
            key=arguments["key"],
            resolve_key=arguments["resolve_key"],
            memories=arguments["memories"],
        )
        result["path"] = path
        return json.dumps(result, ensure_ascii=False)
    except OperationalMemoryError as exc:
        return json.dumps({"status": "error", "error": str(exc), "tool": "record_operational_memory"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {
                "status": "exception",
                "error": f"{type(exc).__name__}: {exc}",
                "tool": "record_operational_memory",
            },
            ensure_ascii=False,
        )


record_operational_memory_declaration = {
    "type": "function",
    "function": {
        "name": "record_operational_memory",
        "description": (
            "Make the required memory decision after a tool failure. Use action=upsert only for reusable "
            "operational lessons, action=replace to rewrite the corrected memory set, action=skip for transient or non-reusable failures, and action=resolve "
            "when an existing operational memory is obsolete."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["upsert", "replace", "skip", "resolve"],
                    "description": "Required decision for the current failure.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this memory decision is appropriate.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["environment_fact", "tool_limitation", "repo_convention", "bad_pattern", "recovery_strategy"],
                },
                "title": {"type": "string"},
                "lesson": {"type": "string"},
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
            "required": ["action", "reason"],
            "oneOf": [
                {
                    "properties": {"action": {"enum": ["upsert"]}},
                    "required": ["action", "reason", "kind", "title", "lesson", "evidence", "scope", "confidence"],
                },
                {
                    "properties": {"action": {"enum": ["replace"]}},
                    "required": ["action", "reason", "memories"],
                },
                {
                    "properties": {"action": {"enum": ["resolve"]}},
                    "required": ["action", "reason"],
                    "anyOf": [{"required": ["key"]}, {"required": ["resolve_key"]}],
                },
                {
                    "properties": {"action": {"enum": ["skip"]}},
                    "required": ["action", "reason"],
                },
            ],
            "additionalProperties": False,
        },
    },
}

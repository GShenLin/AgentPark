import json


def compact_tool_context(
    action,
    reason,
    summary="",
    keep_message_ids=None,
    delete_message_ids=None,
    rewrites=None,
    agent=None,
):
    try:
        if agent is None or not hasattr(agent, "_apply_tool_context_compaction"):
            return json.dumps(
                {
                    "status": "error",
                    "error": "compact_tool_context requires an active agent compaction gate.",
                    "tool": "compact_tool_context",
                },
                ensure_ascii=False,
            )
        result = agent._apply_tool_context_compaction(
            action=action,
            reason=reason,
            summary=summary,
            keep_message_ids=keep_message_ids if isinstance(keep_message_ids, list) else [],
            delete_message_ids=delete_message_ids if isinstance(delete_message_ids, list) else [],
            rewrites=rewrites if isinstance(rewrites, list) else [],
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {
                "status": "exception",
                "error": f"{type(exc).__name__}: {exc}",
                "tool": "compact_tool_context",
            },
            ensure_ascii=False,
        )


compact_tool_context_declaration = {
    "type": "function",
    "function": {
        "name": "compact_tool_context",
        "description": (
            "Make the required context compaction decision after many tool calls. "
            "Use action=replace to replace the eligible tool-call window with a concise summary, "
            "action=patch to delete or rewrite specific eligible messages, and action=skip when no "
            "safe compaction is possible. The resulting summary is working memory for continuation, "
            "not a completion signal. After compaction, resume the current task using the latest "
            "user request, pending work, and verification state. Do not send a final response "
            "solely because compaction completed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["replace", "patch", "skip"],
                    "description": "Required compaction decision for the current tool-call window.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this compaction decision is appropriate.",
                },
                "summary": {
                    "type": "string",
                    "description": (
                        "Concise replacement summary preserving useful findings, inspected files, "
                        "state changes, failed attempts, and remaining next steps."
                    ),
                },
                "keep_message_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Eligible message ids that must remain raw.",
                },
                "delete_message_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For action=patch, eligible message ids to remove.",
                },
                "rewrites": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "message_id": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["message_id", "content"],
                        "additionalProperties": False,
                    },
                    "description": "For action=patch, replacement content for eligible tool/system messages.",
                },
            },
            "required": ["action", "reason"],
            "additionalProperties": False,
        },
    },
}

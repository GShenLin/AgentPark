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
            "Use action=replace to replace the eligible tool-call window with a structured checkpoint, "
            "and action=patch to delete or rewrite specific eligible messages. The resulting summary is working memory for continuation, "
            "not a completion signal. After compaction, resume the current task using the latest "
            "user request, pending work, and verification state. Do not send a final response "
            "solely because compaction completed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["replace", "patch"],
                    "description": "Required compaction decision for the current tool-call window.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this compaction decision is appropriate.",
                },
                "summary": {
                    "type": "object",
                    "properties": {
                        "task_anchor": {
                            "type": "string",
                            "description": "The exact current user objective and non-negotiable constraints.",
                        },
                        "completed_facts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Confirmed architecture facts and conclusions that should be trusted without re-reading.",
                        },
                        "changed_state": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Files or external state changed, including the material effect of each change.",
                        },
                        "verification": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Checks already run with their exact outcome; do not rerun unless later changes invalidate them.",
                        },
                        "failed_attempts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Failures and rejected approaches whose repetition would waste work.",
                        },
                        "remaining_steps": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string"},
                            "description": "Concrete unfinished steps in execution order.",
                        },
                        "immediate_next_step": {
                            "type": "string",
                            "description": "Exactly one item copied verbatim from remaining_steps.",
                        },
                        "avoid_repeating": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific reads, searches, or validations already sufficient and not to repeat.",
                        },
                    },
                    "required": [
                        "task_anchor",
                        "completed_facts",
                        "changed_state",
                        "verification",
                        "failed_attempts",
                        "remaining_steps",
                        "immediate_next_step",
                        "avoid_repeating",
                    ],
                    "additionalProperties": False,
                    "description": (
                        "Strict continuation checkpoint. Record enough evidence to resume the immediate "
                        "next step without repeating completed repository reads or validations."
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
            "required": ["action", "reason", "summary"],
            "additionalProperties": False,
        },
    },
}

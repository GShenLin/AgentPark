import json


def compact_session_context(reason, summary, agent=None):
    try:
        if agent is None or not hasattr(agent, "_apply_session_context_compaction"):
            raise RuntimeError("compact_session_context requires an active session compaction gate")
        result = agent._apply_session_context_compaction(reason=reason, summary=summary)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {
                "status": "exception",
                "tool": "compact_session_context",
                "error": f"{type(exc).__name__}: {exc}",
            },
            ensure_ascii=False,
        )


compact_session_context_declaration = {
    "type": "function",
    "function": {
        "name": "compact_session_context",
        "description": (
            "Replace the selected older session prefix with a durable structured checkpoint. "
            "The checkpoint is working memory for continuing the current task, not a final answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why the older session prefix can be replaced now.",
                },
                "summary": {
                    "type": "object",
                    "properties": {
                        "task_anchor": {"type": "string"},
                        "completed_facts": {"type": "array", "items": {"type": "string"}},
                        "changed_state": {"type": "array", "items": {"type": "string"}},
                        "verification": {"type": "array", "items": {"type": "string"}},
                        "failed_attempts": {"type": "array", "items": {"type": "string"}},
                        "remaining_steps": {"type": "array", "items": {"type": "string"}},
                        "immediate_next_step": {"type": "string"},
                        "critical_context": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "task_anchor",
                        "completed_facts",
                        "changed_state",
                        "verification",
                        "failed_attempts",
                        "remaining_steps",
                        "immediate_next_step",
                        "critical_context",
                    ],
                    "additionalProperties": False,
                },
            },
            "required": ["reason", "summary"],
            "additionalProperties": False,
        },
    },
}


__all__ = ["compact_session_context", "compact_session_context_declaration"]

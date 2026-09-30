RAW_CONTEXT_COMPACTION_GATE_PROMPT = (
    "Tool calls have accumulated in the current task. This is a context maintenance checkpoint. "
    "If more function-tool work is needed, call compact_tool_context before using another function tool. "
    "If the task is already complete, return the final answer directly without calling it; a substantive "
    "response closes the checkpoint and ends the current turn.\n"
    "Review the tool-call history already present in the conversation and decide what should remain. "
    "Use the latest user request as the primary task anchor. Prefer action=replace when the raw tool-call "
    "window can be replaced by a concise but actionable summary. Use action=patch when only specific "
    "messages should be deleted or rewritten.\n"
    "Keep actionable facts, changed paths, verification, failed attempts, and pending decisions; "
    "drop raw logs and repetition. Current runtime skill state overrides historical activation claims. "
    "Include any missing activation "
    "before the dependent step. Ordinary tools are temporarily hidden during this checkpoint.\n"
    "The summary is working memory for continuation, not a completion signal. Distinguish confirmed facts, "
    "changed state, verification, failed attempts, and ordered remaining steps. Set immediate_next_step to "
    "exactly one remaining step and record already-sufficient evidence in avoid_repeating. "
    "Then perform that step; finish with results or a concrete blocker, not a promise to continue."
)

RAW_CONTEXT_COMPACTION_RETRY_PROMPT = (
    "The compaction checkpoint is still active. compact_tool_context is the only function tool currently "
    "offered. If more function-tool work is needed, correct the previous compaction error and call "
    "compact_tool_context again before requesting any other function tool. Ordinary function tools are "
    "restored after compaction succeeds. If the task is already complete, return the final answer directly; "
    "a substantive response closes this checkpoint."
)


__all__ = [
    "RAW_CONTEXT_COMPACTION_GATE_PROMPT",
    "RAW_CONTEXT_COMPACTION_RETRY_PROMPT",
]

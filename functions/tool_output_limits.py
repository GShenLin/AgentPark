from __future__ import annotations


TOOL_SUBMISSION_RESERVE_CHARS = 512


def resolve_tool_result_char_limit(agent, default_limit: int) -> int:
    """Resolve a tool's total result budget without exceeding provider submission limits."""
    if isinstance(default_limit, bool) or not isinstance(default_limit, int) or default_limit <= 0:
        raise ValueError("default_limit must be a positive integer")

    config = getattr(agent, "config", None)
    if not isinstance(config, dict) or "toolResultSubmissionMaxChars" not in config:
        return default_limit

    submission_limit = config["toolResultSubmissionMaxChars"]
    if isinstance(submission_limit, bool) or not isinstance(submission_limit, int) or submission_limit <= 0:
        raise ValueError("toolResultSubmissionMaxChars must be a positive integer")

    reserve = min(TOOL_SUBMISSION_RESERVE_CHARS, submission_limit // 10)
    return min(default_limit, max(1, submission_limit - reserve))

from __future__ import annotations

import json


def resolve_tool_submission_char_limit(agent=None) -> int | None:
    config = getattr(agent, "config", None)
    if not isinstance(config, dict) or "toolResultSubmissionMaxChars" not in config:
        return None
    value = config.get("toolResultSubmissionMaxChars")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(
            "agent.config.toolResultSubmissionMaxChars must be a positive integer"
        )
    return value


def build_console_command_result(
    *,
    command,
    stdout: str,
    stderr: str,
    status: str,
    output_limit: int,
    submission_limit: int | None,
    returncode=None,
    error: str | None = None,
    extra: dict | None = None,
) -> str:
    preserve_head = status != "success"

    def build(effective_limit: int, applied_submission_limit: int | None = None):
        return _console_result_payload(
            command=command,
            stdout=stdout,
            stderr=stderr,
            status=status,
            configured_output_limit=output_limit,
            effective_output_limit=effective_limit,
            preserve_head=preserve_head,
            returncode=returncode,
            error=error,
            extra=extra,
            submission_limit=applied_submission_limit,
        )

    serialized = json.dumps(build(output_limit), ensure_ascii=False)
    if submission_limit is None or len(serialized) <= submission_limit:
        return serialized

    low, high = 1, output_limit
    best_serialized = None
    while low <= high:
        candidate_limit = (low + high) // 2
        candidate_serialized = json.dumps(
            build(candidate_limit, submission_limit),
            ensure_ascii=False,
        )
        if len(candidate_serialized) <= submission_limit:
            best_serialized = candidate_serialized
            low = candidate_limit + 1
        else:
            high = candidate_limit - 1
    if best_serialized is None:
        raise ValueError(
            "console command metadata exceeds agent.config.toolResultSubmissionMaxChars "
            "even after stdout/stderr are reduced to one character each"
        )
    return best_serialized


def _console_result_payload(
    *,
    command,
    stdout: str,
    stderr: str,
    status: str,
    configured_output_limit: int,
    effective_output_limit: int,
    preserve_head: bool,
    returncode=None,
    error: str | None = None,
    extra: dict | None = None,
    submission_limit: int | None = None,
) -> dict:
    stdout, stdout_meta = _limit_stream_text(
        stdout,
        stream_name="stdout",
        limit=effective_output_limit,
        preserve_head=preserve_head,
    )
    stderr, stderr_meta = _limit_stream_text(
        stderr,
        stream_name="stderr",
        limit=effective_output_limit,
        preserve_head=preserve_head,
    )
    result = {
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "status": status,
    }
    if returncode is not None:
        result["returncode"] = returncode
    if error is not None:
        result["error"] = error
    if isinstance(extra, dict) and extra:
        result.update(extra)

    result.update(
        {
            "stdout_truncated": stdout_meta["truncated"],
            "stdout_original_chars": stdout_meta["original_chars"],
            "stdout_returned_chars": stdout_meta["returned_chars"],
            "stderr_truncated": stderr_meta["truncated"],
            "stderr_original_chars": stderr_meta["original_chars"],
            "stderr_returned_chars": stderr_meta["returned_chars"],
            "output_max_chars_per_stream": configured_output_limit,
            "output_effective_max_chars_per_stream": effective_output_limit,
        }
    )
    truncated_streams = []
    if stdout_meta["truncated"]:
        truncated_streams.append({"stream": "stdout", **stdout_meta})
    if stderr_meta["truncated"]:
        truncated_streams.append({"stream": "stderr", **stderr_meta})
    if truncated_streams:
        result["output_truncated"] = True
        result["output_truncation_notice"] = (
            "Command output exceeded the hard stdout/stderr size limit. "
            "The returned stdout/stderr fields are partial; successful commands preserve tail content, "
            "while failed or timed-out commands preserve both the beginning and tail for diagnosis."
        )
        result["output_truncation"] = {
            "max_chars_per_stream": effective_output_limit,
            "streams": truncated_streams,
        }
    if submission_limit is not None:
        result["output_submission_budget"] = {
            "applied": True,
            "configured_submission_max_chars": submission_limit,
            "configured_output_max_chars_per_stream": configured_output_limit,
            "effective_output_max_chars_per_stream": effective_output_limit,
            "strategy": "serialized_payload_binary_search",
        }
    return result


def _limit_stream_text(
    text: str,
    *,
    stream_name: str,
    limit: int,
    preserve_head: bool,
) -> tuple[str, dict]:
    value = str(text or "")
    original_chars = len(value)
    if original_chars <= limit:
        return value, {
            "truncated": False,
            "original_chars": original_chars,
            "returned_chars": original_chars,
        }
    if preserve_head:
        omitted_chars = original_chars - limit
        marker = f"\n... <{omitted_chars} chars omitted> ...\n"
        if len(marker) < limit:
            available = limit - len(marker)
            head_chars = max(1, available // 4)
            tail_chars = available - head_chars
            limited = value[:head_chars] + marker + value[-tail_chars:]
        else:
            head_chars = limit // 2
            tail_chars = limit - head_chars
            limited = value[:head_chars] + value[-tail_chars:]
        strategy = "head_tail"
        notice = (
            f"{stream_name} exceeded the hard limit of {limit} characters; "
            "the beginning and tail of this stream are returned for failure diagnosis."
        )
    else:
        limited = value[-limit:]
        head_chars = 0
        tail_chars = limit
        strategy = "tail"
        notice = (
            f"{stream_name} exceeded the hard limit of {limit} characters; "
            f"only the tail of this stream is returned."
        )
    return limited, {
        "truncated": True,
        "original_chars": original_chars,
        "returned_chars": limit,
        "omitted_chars": original_chars - limit,
        "strategy": strategy,
        "head_chars": head_chars,
        "tail_chars": tail_chars,
        "notice": notice,
    }

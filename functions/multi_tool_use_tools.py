import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


_TOOL_NAME = "multi_tool_use_parallel"
_LEGACY_TOOL_NAME = "multi_tool_use.parallel"
_RECIPIENT_PREFIX = "functions."
_MAX_TOOL_USES = 64
_ERROR_STATUSES = {"error", "exception", "blocked", "timeout", "permission_denied", "locked", "locked_or_readonly"}


def _validate_tool_uses(tool_uses):
    if not isinstance(tool_uses, list) or not tool_uses:
        return None, "tool_uses must be a non-empty array."
    if len(tool_uses) > _MAX_TOOL_USES:
        return None, f"tool_uses cannot exceed {_MAX_TOOL_USES} items."

    normalized = []
    for index, item in enumerate(tool_uses):
        if not isinstance(item, dict):
            return None, f"tool_uses[{index}] must be an object."

        recipient_name = item.get("recipient_name")
        if not isinstance(recipient_name, str) or not recipient_name.strip():
            return None, f"tool_uses[{index}].recipient_name must be a non-empty string."
        recipient_name = recipient_name.strip()
        if not recipient_name.startswith(_RECIPIENT_PREFIX):
            return None, (
                f"tool_uses[{index}].recipient_name must start with '{_RECIPIENT_PREFIX}'."
            )

        tool_name = recipient_name[len(_RECIPIENT_PREFIX):].strip()
        if not tool_name:
            return None, f"tool_uses[{index}].recipient_name does not contain a tool name."
        if tool_name in {_TOOL_NAME, _LEGACY_TOOL_NAME}:
            return None, f"tool_uses[{index}] cannot invoke {_TOOL_NAME} recursively."

        parameters = item.get("parameters")
        if parameters is None:
            parameters = {}
        if not isinstance(parameters, dict):
            return None, f"tool_uses[{index}].parameters must be an object."

        normalized.append(
            {
                "index": index,
                "recipient_name": recipient_name,
                "tool_name": tool_name,
                "parameters": parameters,
            }
        )
    return normalized, None


def _classify_tool_result(raw_result):
    if isinstance(raw_result, str):
        stripped = raw_result.strip()
        try:
            parsed = json.loads(stripped)
        except Exception:
            return "success"
        if isinstance(parsed, dict):
            status = str(parsed.get("status") or "").strip().lower()
            if status in _ERROR_STATUSES:
                return "error"
        return "success"

    if isinstance(raw_result, dict):
        status = str(raw_result.get("status") or "").strip().lower()
        if status in _ERROR_STATUSES:
            return "error"
    return "success"


def _run_single_use(agent, use_spec):
    started_at = time.monotonic()
    raw_result = agent.execute_tool(use_spec["tool_name"], use_spec["parameters"])
    status = _classify_tool_result(raw_result)
    duration_ms = int((time.monotonic() - started_at) * 1000)
    return {
        "index": use_spec["index"],
        "recipient_name": use_spec["recipient_name"],
        "tool_name": use_spec["tool_name"],
        "status": status,
        "duration_ms": duration_ms,
        "result": raw_result,
    }


def multi_tool_use_parallel(tool_uses, agent=None):
    """
    Execute multiple function tools in parallel.
    recipient_name must use the shape: functions.<tool_name>
    """
    try:
        if agent is None or not hasattr(agent, "execute_tool") or not callable(agent.execute_tool):
            return json.dumps(
                {
                    "status": "error",
                    "tool": _TOOL_NAME,
                    "error": "agent.execute_tool is required.",
                },
                ensure_ascii=False,
            )

        normalized, validation_error = _validate_tool_uses(tool_uses)
        if validation_error:
            return json.dumps(
                {
                    "status": "error",
                    "tool": _TOOL_NAME,
                    "error": validation_error,
                },
                ensure_ascii=False,
            )

        task_count = len(normalized)
        max_workers = task_count
        if hasattr(agent, "_resolve_parallel_workers") and callable(agent._resolve_parallel_workers):
            try:
                resolved = int(agent._resolve_parallel_workers(task_count))
                if resolved > 0:
                    max_workers = min(task_count, resolved)
            except Exception:
                max_workers = task_count
        max_workers = max(1, min(task_count, max_workers))

        results = [None] * task_count
        if max_workers == 1:
            for spec in normalized:
                results[spec["index"]] = _run_single_use(agent, spec)
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_index = {
                    executor.submit(_run_single_use, agent, spec): spec["index"]
                    for spec in normalized
                }
                for future in as_completed(future_to_index):
                    index = future_to_index[future]
                    try:
                        results[index] = future.result()
                    except Exception as e:
                        results[index] = {
                            "index": index,
                            "recipient_name": normalized[index]["recipient_name"],
                            "tool_name": normalized[index]["tool_name"],
                            "status": "error",
                            "duration_ms": 0,
                            "error": f"{type(e).__name__}: {str(e)}",
                            "result": None,
                        }

        succeeded = sum(1 for item in results if isinstance(item, dict) and item.get("status") == "success")
        failed = task_count - succeeded
        status = "success" if failed == 0 else ("partial_success" if succeeded > 0 else "error")

        return json.dumps(
            {
                "status": status,
                "tool": _TOOL_NAME,
                "summary": {
                    "requested": task_count,
                    "succeeded": succeeded,
                    "failed": failed,
                    "max_workers": max_workers,
                },
                "results": results,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            {
                "status": "exception",
                "tool": _TOOL_NAME,
                "error": f"{type(e).__name__}: {str(e)}",
            },
            ensure_ascii=False,
        )


multi_tool_use_parallel_declaration = {
    "type": "function",
    "function": {
        "name": _TOOL_NAME,
        "description": (
            "Run multiple function tools in parallel. "
            "Each item must provide recipient_name='functions.<tool_name>' and parameters object."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tool_uses": {
                    "type": "array",
                    "description": "List of tool calls to run in parallel.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "recipient_name": {
                                "type": "string",
                                "description": "Target function name with functions. prefix, e.g. functions.read_file.",
                            },
                            "parameters": {
                                "type": "object",
                                "description": "Arguments passed to the target tool function.",
                            },
                        },
                        "required": ["recipient_name", "parameters"],
                    },
                }
            },
            "required": ["tool_uses"],
        },
    },
}


# Disable wrapper timeout to avoid cutting off long-running child tool batches.
multi_tool_use_parallel.tool_timeout_seconds = 0

# Keep the old dotted name executable for internal callers, but never expose it in tool declarations.
globals()[_LEGACY_TOOL_NAME] = multi_tool_use_parallel
tool_function_aliases = {
    _TOOL_NAME: [_LEGACY_TOOL_NAME],
}


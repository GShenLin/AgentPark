from __future__ import annotations

from typing import Any

from src.providers.responses_image_input import build_tool_image_responses_input_item
from src.providers.responses_input_items import build_responses_function_call_output_item


def build_responses_followup_items(runtime: Any, executions) -> list[dict[str, Any]]:
    followup_items = []
    for execution in executions if isinstance(executions, list) else []:
        runtime.Message("tool", execution.cleaned_result, tool_call_id=execution.call_id, name=execution.func_name)
        non_retry_warn = runtime._build_non_retryable_tool_warning(execution.func_name, execution.cleaned_result)
        if non_retry_warn:
            runtime.Message("system", non_retry_warn)
        call_id = str(execution.call_id or "").strip()
        if call_id:
            runtime._validate_responses_followup_call_id(call_id)
            followup_items.append(
                build_responses_function_call_output_item(call_id, runtime._responses_tool_output(execution))
            )
        image_item = build_tool_image_responses_input_item(execution.image_data)
        if image_item is not None:
            followup_items.append(image_item)
    return followup_items

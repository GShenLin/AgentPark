from __future__ import annotations

from typing import Any

from src.providers.tool_image_input import build_tool_image_responses_input_item
from src.providers.tool_image_input import build_image_tool_output
from src.providers.responses_input_items import build_responses_function_call_output_item


def build_responses_followup_items(runtime: Any, executions) -> list[dict[str, Any]]:
    followup_items = []
    for execution in executions if isinstance(executions, list) else []:
        model_output = runtime._responses_tool_output(execution)
        runtime.Message("tool", model_output, tool_call_id=execution.call_id, name=execution.func_name)
        non_retry_warn = runtime._build_non_retryable_tool_warning(execution.func_name, model_output)
        if non_retry_warn:
            runtime.RuntimeInstruction(non_retry_warn)
        call_id = str(execution.call_id or "").strip()
        output_images = [image for image in execution.images if image.get("placement") == "tool_output"]
        if output_images and not call_id:
            raise ValueError("Image tool output requires a call ID")
        if call_id:
            runtime._validate_responses_followup_call_id(call_id)
            followup_items.append(
                build_image_tool_output(call_id, model_output, output_images) if output_images
                else build_responses_function_call_output_item(call_id, model_output)
            )
        for image_data in execution.images:
            if image_data.get("placement") == "tool_output":
                continue
            image_item = build_tool_image_responses_input_item(image_data)
            if image_item is not None:
                followup_items.append(image_item)
    return followup_items

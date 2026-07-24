import json
import os
from datetime import datetime

from src.config_loader import ConfigLoader
from src.runtime_cancellation import cancel_source_from_agent
from src.value_parsing import parse_bool_value


GUI_MODE = "GUIAgent"
DEFAULT_GUI_PROVIDER_ID = "doubao-seed-1-6-vision-250815"
Node = None


def _safe_text(value):
    return str(value or "").strip()


def _supports_gui_agent(provider_config):
    if not isinstance(provider_config, dict):
        return False
    supportmode = provider_config.get("supportmode")
    if not isinstance(supportmode, (list, tuple, set)):
        return False
    for mode in supportmode:
        if str(mode or "").strip().lower() == GUI_MODE.lower():
            return True
    return False


def _resolve_gui_provider(provider_id):
    requested = _safe_text(provider_id)
    try:
        providers = ConfigLoader().get_all_providers()
    except Exception:
        providers = {}
    if not isinstance(providers, dict):
        providers = {}

    if requested:
        provider_cfg = providers.get(requested)
        if provider_cfg is None:
            return "", f"provider not found: {requested}"
        if not _supports_gui_agent(provider_cfg):
            return "", f"provider does not support {GUI_MODE}: {requested}"
        return requested, ""

    gui_candidates = [
        str(provider_key)
        for provider_key, provider_cfg in providers.items()
        if _supports_gui_agent(provider_cfg)
    ]
    if DEFAULT_GUI_PROVIDER_ID in gui_candidates:
        return DEFAULT_GUI_PROVIDER_ID, ""
    if gui_candidates:
        return gui_candidates[0], ""
    return "", f"no provider supports {GUI_MODE}"


def _extract_structured_and_images(output_envelope):
    structured = {}
    image_paths = []
    if not isinstance(output_envelope, dict):
        return structured, image_paths
    parts = output_envelope.get("parts")
    if not isinstance(parts, list):
        return structured, image_paths
    for part in parts:
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type") or "").strip().lower()
        if part_type == "structured":
            data = part.get("data")
            if isinstance(data, dict):
                structured = data
        if part_type != "resource":
            continue
        resource = part.get("resource")
        if not isinstance(resource, dict):
            continue
        kind = str(resource.get("kind") or "").strip().lower()
        if kind and kind != "image":
            continue
        uri = str(resource.get("uri") or "").strip()
        if not uri:
            continue
        raw_path = uri[7:] if uri.startswith("file://") else uri
        image_paths.append(raw_path)
    return structured, image_paths


def _extract_output_envelope(result):
    if not isinstance(result, dict):
        return {}, "node_result_not_object"
    routes = result.get("routes")
    if not isinstance(routes, list) or not routes:
        return {}, "missing_routes"
    first = routes[0]
    if not isinstance(first, dict):
        return {}, "invalid_route_item"
    payload = first.get("payload")
    if not isinstance(payload, dict):
        return {}, "missing_route_payload"
    parts = payload.get("parts")
    if not isinstance(parts, list):
        return {}, "invalid_route_payload_parts"
    return payload, ""


def _pick_feedback_image_path(structured, image_paths):
    steps = structured.get("steps") if isinstance(structured, dict) else None
    if isinstance(steps, list):
        for step in reversed(steps):
            if not isinstance(step, dict):
                continue
            action_name = str(step.get("action_name") or "").strip().lower()
            if action_name not in {"click", "left_double", "right_single", "long_press"}:
                continue
            marked_path = str(step.get("screenshot_after_marked") or "").strip()
            if marked_path and os.path.isfile(marked_path):
                return marked_path
            after_path = str(step.get("screenshot_after") or "").strip()
            if after_path and os.path.isfile(after_path):
                return after_path
    return image_paths[-1] if image_paths else ""


def _json_result(status, **fields):
    payload = {
        "status": status,
        "tool": "run_gui_agent_task",
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    payload.update(fields)
    return json.dumps(payload, ensure_ascii=False)


def _resolve_node_class():
    global Node
    if Node is not None:
        return Node
    from nodes.gui_agent_node import Node as GuiAgentNode

    Node = GuiAgentNode
    return Node


def run_gui_agent_task(
    task,
    provider_id="",
    image_path="",
    system_prompt="",
    verify_prompt="",
    verify_on_finish=True,
    dry_run=False,
    capture_region=None,
    agent=None,
):
    instruction = _safe_text(task)
    if not instruction:
        return _json_result(
            "blocked",
            task_result="failed",
            task_completed=False,
            task_failed=True,
            retryable=False,
            error="task is required",
        )

    resolved_provider_id, provider_error = _resolve_gui_provider(provider_id)
    if provider_error:
        return _json_result(
            "blocked",
            task_result="failed",
            task_completed=False,
            task_failed=True,
            retryable=False,
            error=provider_error,
            requested_provider_id=_safe_text(provider_id),
        )

    image_path_value = _safe_text(image_path)
    if image_path_value and not os.path.isfile(image_path_value):
        return _json_result(
            "blocked",
            task_result="failed",
            task_completed=False,
            task_failed=True,
            retryable=False,
            error=f"image_path not found: {image_path_value}",
            provider_id=resolved_provider_id,
        )

    context = {
        "graph_id": "gui_agent",
        "node_instance_id": "gui_agent_runner",
        "provider_id": resolved_provider_id,
        "mode": GUI_MODE,
        "verify_mode": GUI_MODE,
        "instruction": instruction,
        "verify_on_finish": "true" if parse_bool_value(verify_on_finish, default=True) else "false",
        "dry_run": "true" if parse_bool_value(dry_run, default=False) else "false",
    }
    cancel_source = cancel_source_from_agent(agent)
    if cancel_source is not None:
        context["cancel_event"] = cancel_source
        context["cancel_check"] = cancel_source
    prompt_text = _safe_text(system_prompt)
    if prompt_text:
        context["system_prompt"] = prompt_text
    verify_prompt_text = _safe_text(verify_prompt)
    if verify_prompt_text:
        context["verify_prompt"] = verify_prompt_text
    if isinstance(capture_region, dict):
        context["capture_region"] = json.dumps(capture_region, ensure_ascii=False)

    parts = [{"type": "text", "text": instruction}]
    if image_path_value:
        parts.append(
            {
                "type": "resource",
                "resource": {"uri": image_path_value, "kind": "image"},
            }
        )
    message = {"role": "user", "parts": parts}

    try:
        node_cls = _resolve_node_class()
        node = node_cls()
        result = node.on_input(message, context)
    except Exception as e:
        return _json_result(
            "error",
            task_result="failed",
            task_completed=False,
            task_failed=True,
            retryable=True,
            error=f"gui_agent_failed: {type(e).__name__}: {str(e)}",
            provider_id=resolved_provider_id,
            mode=GUI_MODE,
        )

    output_envelope, output_error = _extract_output_envelope(result)
    if output_error:
        return _json_result(
            "error",
            task_result="failed",
            task_completed=False,
            task_failed=True,
            retryable=True,
            error=f"invalid_gui_agent_output: {output_error}",
            provider_id=resolved_provider_id,
            mode=GUI_MODE,
        )
    structured, image_paths = _extract_structured_and_images(output_envelope)
    final_image_path = _pick_feedback_image_path(structured, image_paths)
    steps = structured.get("steps") if isinstance(structured.get("steps"), list) else []

    response_payload = {
        "status": str(structured.get("status") or "stopped"),
        "finished": parse_bool_value(structured.get("finished"), default=False),
        "reason": str(structured.get("reason") or ""),
        "instruction": str(structured.get("instruction") or instruction),
        "summary": str(result.get("display") or ""),
        "provider_id": resolved_provider_id,
        "mode": GUI_MODE,
        "run_dir": str(structured.get("run_dir") or ""),
        "step_count": len(steps),
        "steps": steps,
    }
    is_finished = parse_bool_value(response_payload.get("finished"), default=False)
    response_payload["task_result"] = "completed" if is_finished else "failed"
    response_payload["task_completed"] = bool(is_finished)
    response_payload["task_failed"] = not bool(is_finished)
    response_payload["model_judgement_required"] = True
    if final_image_path:
        response_payload["final_image_path"] = final_image_path
    final_status = str(response_payload.pop("status", "ok") or "ok")
    return _json_result(final_status, **response_payload)


run_gui_agent_task.tool_timeout_seconds = 0


run_gui_agent_task_declaration = {
    "type": "function",
    "function": {
        "name": "run_gui_agent_task",
        "description": (
            "Use GUIAgent to directly operate the local desktop by screenshot-plan-act loop. "
            "Use this when task execution requires real GUI operations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The GUI task goal in natural language.",
                },
                "provider_id": {
                    "type": "string",
                    "description": "Optional GUI planner provider_id. Must support GUIAgent mode.",
                },
                "image_path": {
                    "type": "string",
                    "description": "Optional local image path as first fallback screenshot.",
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Optional planner system prompt override.",
                },
                "verify_prompt": {
                    "type": "string",
                    "description": "Optional verify prompt override for finished action.",
                },
                "verify_on_finish": {
                    "type": "boolean",
                    "description": "Whether to verify completion when model outputs finished.",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "If true, only simulates action execution without real GUI actions.",
                },
                "capture_region": {
                    "type": "object",
                    "description": "Optional capture region object: {left, top, width, height}.",
                },
            },
            "required": ["task"],
        },
    },
}

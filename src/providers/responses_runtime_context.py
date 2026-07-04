from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Any

from src.providers.agent_collaboration_mode import is_collaboration_mode_text
from src.providers.agent_environment_context import build_agent_environment_context as _default_build_agent_environment_context
from src.providers.agent_environment_context import is_agent_environment_context_text
from src.providers.agent_permissions_context import is_agent_permissions_context_text
from src.providers.agent_project_instructions import build_agent_project_instructions_context
from src.providers.agent_project_instructions import is_agent_project_instructions_text
from src.providers.agent_project_instructions import project_instructions_update_notice
from src.providers.agent_turn_context import build_agent_turn_context_item
from src.providers.agent_turn_context import build_agent_turn_context_update


@dataclass(frozen=True)
class ResponsesTurnContext:
    environment_context: Any
    project_instructions_context: Any
    context_item: dict[str, Any]
    context_update: dict[str, Any]
    persistent_update_mode: str
    project_instructions_notice: str


def build_responses_agent_environment_context(*args, **kwargs):
    runtime_module = sys.modules.get("src.providers.responses_runtime")
    bridge = getattr(runtime_module, "build_agent_environment_context", None)
    if callable(bridge):
        return bridge(*args, **kwargs)
    return _default_build_agent_environment_context(*args, **kwargs)


def build_responses_turn_context(
    runtime,
    *,
    current_input: list[Any],
    tools_payload: list[Any],
    mode_decision,
    request_index: int,
    model_reference_context_item: dict[str, Any] | None,
    persistent_reference_context_item: dict[str, Any] | None,
    environment_context_builder,
) -> ResponsesTurnContext:
    environment_context = environment_context_builder(runtime, current_input=current_input)
    project_instructions_context = build_agent_project_instructions_context(
        runtime,
        environment_context=environment_context,
    )
    context_item = build_agent_turn_context_item(
        runtime,
        environment_context=environment_context,
        project_instructions_context=project_instructions_context,
        tools_payload=tools_payload,
        responses_mode=mode_decision.mode,
        requested_responses_mode=mode_decision.requested_mode,
    )
    model_context_update = build_agent_turn_context_update(
        model_reference_context_item,
        context_item,
        request_index=request_index,
    )
    persistent_context_update = build_agent_turn_context_update(
        persistent_reference_context_item,
        context_item,
        request_index=request_index,
    )
    context_update = dict(persistent_context_update)
    context_update["model_context_update_mode"] = str(
        model_context_update.get("context_update_mode") or ""
    )
    context_update["persistent_context_update_mode"] = str(
        persistent_context_update.get("context_update_mode") or ""
    )
    context_update["persistent_context_item_hash"] = str(
        persistent_context_update.get("context_item_hash") or ""
    )
    persistent_update_mode = str(persistent_context_update.get("context_update_mode") or "")
    return ResponsesTurnContext(
        environment_context=environment_context,
        project_instructions_context=project_instructions_context,
        context_item=context_item,
        context_update=context_update,
        persistent_update_mode=persistent_update_mode,
        project_instructions_notice=project_instructions_update_notice(
            context_item,
            project_instructions_context,
        ),
    )


def has_environment_context(items: list[Any]) -> bool:
    return _has_context_text(items, is_agent_environment_context_text)


def has_collaboration_context(items: list[Any]) -> bool:
    return _has_context_text(items, is_collaboration_mode_text)


def has_permissions_context(items: list[Any]) -> bool:
    return _has_context_text(items, is_agent_permissions_context_text)


def has_project_instructions_context(items: list[Any]) -> bool:
    return _has_context_text(items, is_agent_project_instructions_text)


def runtime_context_history_items(items: list[Any]) -> list[dict[str, Any]]:
    return _dedupe_runtime_context_history_items(
        [
            context_item
            for item in items
            for context_item in [runtime_context_history_item(item)]
            if context_item is not None
        ]
    )


def runtime_context_history_item(item: Any) -> dict[str, Any] | None:
    if not is_model_visible_runtime_context_item(item):
        return None
    content = []
    for part in content_parts(item):
        text = part.get("text")
        if (
            is_agent_permissions_context_text(text)
            or is_collaboration_mode_text(text)
            or is_agent_environment_context_text(text)
            or is_agent_project_instructions_text(text)
        ):
            content.append(part)
    if not content:
        return None
    output = dict(item)
    output["content"] = content
    return output


def is_model_visible_runtime_context_item(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and str(item.get("type") or "").strip().lower() == "message"
        and (
            has_permissions_context([item])
            or has_collaboration_context([item])
            or has_environment_context([item])
            or has_project_instructions_context([item])
        )
    )


def is_system_message_item(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and str(item.get("type") or "").strip().lower() == "message"
        and str(item.get("role") or "").strip().lower() == "system"
    )


def message_item_text(item: Any) -> str:
    parts = []
    for part in content_parts(item):
        text = str(part.get("text") or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def is_developer_message_item(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and str(item.get("type") or "").strip().lower() == "message"
        and str(item.get("role") or "").strip().lower() == "developer"
    )


def content_parts(item: Any) -> list[dict[str, Any]]:
    if not isinstance(item, dict):
        return []
    content = item.get("content")
    if not isinstance(content, list):
        return []
    return [dict(part) for part in content if isinstance(part, dict)]


def peel_initial_developer_items(items: list[Any]) -> tuple[list[dict[str, Any]], list[Any]]:
    developer_parts: list[dict[str, Any]] = []
    remaining: list[Any] = []
    in_initial_prefix = True
    for item in items:
        if in_initial_prefix and is_system_message_item(item):
            remaining.append(item)
            continue
        if in_initial_prefix and is_initial_runtime_user_context_item(item):
            remaining.append(item)
            continue
        if in_initial_prefix and is_developer_message_item(item):
            developer_parts.extend(content_parts(item))
            continue
        in_initial_prefix = False
        remaining.append(item)
    return developer_parts, remaining


def is_initial_runtime_user_context_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("type") or "").strip().lower() != "message":
        return False
    if str(item.get("role") or "").strip().lower() != "user":
        return False
    return has_environment_context([item]) or has_project_instructions_context([item])


def runtime_context_item_signature(item: dict[str, Any]) -> tuple[str, ...]:
    kinds = []
    if has_permissions_context([item]):
        kinds.append("permissions")
    if has_collaboration_context([item]):
        kinds.append("collaboration_mode")
    if has_environment_context([item]):
        kinds.append("environment")
    if has_project_instructions_context([item]):
        kinds.append("project_instructions")
    return tuple(kinds)


def _dedupe_runtime_context_history_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for item in items:
        signature = runtime_context_item_signature(item)
        if not signature or signature in seen:
            continue
        seen.add(signature)
        output.append(dict(item))
    return output


def _has_context_text(items: list[Any], predicate) -> bool:
    for item in items:
        for part in content_parts(item):
            if predicate(part.get("text")):
                return True
    return False

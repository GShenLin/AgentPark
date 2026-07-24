from __future__ import annotations

from collections.abc import Callable

from src.providers.instructions import resolve_agent_default_instructions


def merge_structured_response(response: object, structured_result: object) -> object:
    if not isinstance(structured_result, dict) or not structured_result:
        return response
    if isinstance(response, dict):
        return {**response, **structured_result}
    return {"response": "" if response is None else str(response), **structured_result}


def resolve_instruction_role(agent: object) -> str:
    return "developer" if uses_responses_api_context(agent) else "system"


def effective_instruction(agent: object, instruction: object) -> str:
    explicit_instruction = str(instruction or "").strip()
    if explicit_instruction:
        return explicit_instruction
    if uses_responses_api_context(agent):
        return resolve_agent_default_instructions(agent)
    return ""


def uses_responses_api_context(agent: object) -> bool:
    config = getattr(agent, "config", None)
    if not isinstance(config, dict):
        return False
    provider_type = str(config.get("type") or "").strip()
    return provider_type in {"openai", "grok", "doubao"} and config.get("responsesApi") is True


def stream_enabled(agent: object) -> bool:
    config = getattr(agent, "config", None)
    if not isinstance(config, dict):
        return True
    value = config.get("streamEnabled", True)
    return value if isinstance(value, bool) else True


def stream_callback(context: dict | None) -> Callable[[dict], None] | None:
    if not isinstance(context, dict):
        return None
    callback = context.get("stream_callback")
    return callback if callable(callback) else None

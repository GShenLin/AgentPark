from __future__ import annotations

from nodes.agent_message_adapter import history_envelope_to_agent_message
from src.message_protocol import normalize_envelope
from src.web_backend.node_memory_store import load_recent_node_memory_records


def load_agent_history_messages(
    *,
    memory_path: str,
    messages_path: str,
    current_message: object,
    provider_id: str,
    public_base_url: object,
    history_message_limit: int,
) -> list[dict]:
    if not messages_path:
        return []
    if history_message_limit <= 0:
        raise ValueError("history_message_limit must be positive")

    current = normalize_envelope(current_message, default_role="user")
    current_id = str(current.get("id") or "").strip()
    records = load_recent_node_memory_records(
        memory_path,
        messages_path,
        limit=history_message_limit + 1,
        roles={"user", "assistant"},
    )

    history: list[dict] = []
    for item in records:
        envelope = normalize_envelope(item, default_role="assistant")
        if current_id and str(envelope.get("id") or "").strip() == current_id:
            continue
        message = history_envelope_to_agent_message(envelope, provider_id, public_base_url)
        if message is not None:
            history.append(message)
    return history[-history_message_limit:]

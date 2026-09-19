from __future__ import annotations

from pathlib import Path

from nodes.agent_message_adapter import history_envelope_to_agent_message
from src.conversation_context.checkpoint import encode
from src.conversation_context.model import ConversationModel
from src.conversation_context.settings import ConversationSettings
from src.conversation_context.window import ConversationWindow
from src.message_protocol import envelope_text, normalize_envelope
from src.web_backend.node_memory_store import load_recent_node_memory_records
from src.web_backend.node_conversation_context import publish_conversation_checkpoint


def load_agent_history_messages(
    *,
    memory_path: str,
    messages_path: str,
    current_message: object,
    provider_id: str,
    public_base_url: object,
    settings: ConversationSettings,
    reserved_tokens: int = 0, graph_id: str = "", node_id: str = "", cancel_source=None, tracker=None,
) -> list[dict]:
    if not messages_path:
        return []
    current_id = normalize_envelope(current_message, default_role="user").get("id")

    def read():
        records, projected = [], []
        for item in load_recent_node_memory_records(memory_path, messages_path, limit=None):
            if item.get("id") == current_id:
                break
            if item.get("context_policy") == "exclude":
                continue
            envelope = normalize_envelope(item, default_role="assistant")
            message = history_envelope_to_agent_message(envelope, provider_id, public_base_url)
            if item.get("role") in {"tool", "function"}:
                # Audit envelopes are projected as evidence, never as orphan provider tool results.
                content = envelope_text(envelope).strip()
                if content:
                    message = {"role": "assistant", "content": "[Historical tool evidence]\n" + content}
            if message is not None:
                records.append({"id": item["id"], "record": encode({
                    "role": item["role"], "parts": item.get("parts", []), "trace_id": item.get("trace_id"),
                })})
                projected.append(message)
        return records, projected

    records, messages = read()
    model = ConversationModel(settings.provider or provider_id, graph_id=graph_id, node_id=node_id,
                              cancel_source=cancel_source, tracker=tracker)
    return ConversationWindow(Path(messages_path).parent, settings, model.complete).prepare(
        records, messages, reserved_tokens=reserved_tokens,
        publish=lambda expected, summary: publish_conversation_checkpoint(
            memory_path, messages_path, expected, summary, lambda: read()[0]),
    )

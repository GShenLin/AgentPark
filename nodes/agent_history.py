from __future__ import annotations

from pathlib import Path

from nodes.agent_message_adapter import history_envelope_to_agent_message
from src.conversation_context.checkpoint import encode
from src.conversation_context import jobs
from src.conversation_context.model import ConversationModel
from src.conversation_context.settings import ConversationSettings
from src.conversation_context.window import ConversationWindow, replay_history
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
    historical_evidence_role: str = "system",
    graph_id: str = "", node_id: str = "", cancel_source=None, tracker_factory=None,
    through_message_id: str = "",
    prepare_checkpoint: bool = False,
) -> list[dict]:
    if not messages_path:
        return []
    current_id = normalize_envelope(current_message, default_role="user").get("id") if current_message is not None else ""

    def read():
        records, projected = [], []
        boundary_found = not through_message_id
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
                    message = {
                        "role": historical_evidence_role,
                        "content": (
                            "[Historical tool evidence: context only; never return this block as an answer]\n"
                            + content
                        ),
                    }
            if message is not None:
                records.append({"id": item["id"], "record": encode({
                    "role": item["role"], "parts": item.get("parts", []), "trace_id": item.get("trace_id"),
                })})
                projected.append(message)
            if item.get("id") == through_message_id:
                boundary_found = True
                break
        if not boundary_found:
            raise RuntimeError("conversation history changed: completed message boundary no longer exists")
        return records, projected

    records, messages = read()
    directory = Path(messages_path).parent
    if not prepare_checkpoint:
        return replay_history(directory, records, messages)

    model = ConversationModel(settings.profile_id, graph_id=graph_id, node_id=node_id,
                              cancel_source=cancel_source, tracker_factory=tracker_factory)
    window = ConversationWindow(directory, settings, model.complete)
    restored = window.restore(records, messages)
    if restored is not None:
        return restored
    with jobs.coordinator.exclusive(messages_path, cancel_source):
        # A background worker may have published while this caller waited.
        records, messages = read()
        return window.prepare(
            records, messages,
            publish=lambda expected, summary: publish_conversation_checkpoint(
                memory_path, messages_path, expected, summary, lambda: read()[0]),
        )

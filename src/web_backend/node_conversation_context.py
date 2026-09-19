"""Publish a derived conversation checkpoint under the history store's reset/edit lock."""
from pathlib import Path

from src.conversation_context.checkpoint import fingerprint, save_checkpoint
from .node_memory_store import _run_node_memory_transaction


def publish_conversation_checkpoint(memory_path, messages_path, expected_records, summary, reload_records):
    def publish():
        latest = reload_records()
        count = len(expected_records)
        if len(latest) < count or fingerprint(latest[:count]) != fingerprint(expected_records):
            raise RuntimeError("conversation history changed during compaction; checkpoint was not published")
        save_checkpoint(Path(messages_path).parent, expected_records, summary)
    _run_node_memory_transaction(memory_path, messages_path, publish)

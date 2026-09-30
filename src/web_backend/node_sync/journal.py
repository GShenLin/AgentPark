"""Recover a committed node merge before any normal memory reader/writer."""
from pathlib import Path

from src.file_transaction import atomic_write_text
from .blobs import read_json, write_json

JOURNAL = ".sync-commit.json"


def recover(directory: Path):
    journal = directory / JOURNAL
    if not journal.exists():
        return
    changes = read_json(journal)
    for relative, text in changes.items():
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError("invalid sync journal path")
        atomic_write_text(str(path), text)
    # Derived state must also be invalidated when recovering after a crash.
    from src.long_term_memory.store import invalidate_node_memory
    from src.conversation_context.checkpoint import clear_checkpoint
    from ..node_memory_active_state import save_active_memory_state, state_from_records
    from ..node_memory_records import read_jsonl_records
    active = str(directory / "messages.jsonl")
    save_active_memory_state(active, state_from_records(read_jsonl_records(active), active))
    invalidate_node_memory(str(directory))
    clear_checkpoint(str(directory))
    journal.unlink()


def commit(directory: Path, changes: dict[str, str]):
    write_json(directory / JOURNAL, changes)
    recover(directory)

"""Shared transaction boundary for normal history operations and synchronization."""
from pathlib import Path

from src.file_transaction import KeyedTransactionQueue, run_with_interprocess_lock
from .node_memory_paths import node_memory_dir

_QUEUE = KeyedTransactionQueue()


def run_memory_transaction(memory_path: str, messages_path: str, operation):
    directory = node_memory_dir(memory_path, messages_path)
    if not directory:
        return operation()

    def recovered():
        from .node_sync.journal import recover
        recover(Path(directory))
        return operation()

    return _QUEUE.run(directory, lambda: run_with_interprocess_lock(
        str(Path(directory) / ".node-memory.lock"), recovered))


def wait_for_memory_transaction(directory: str):
    if directory:
        _QUEUE.wait_empty(directory)

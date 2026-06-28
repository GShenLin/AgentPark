from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeMemoryPersistenceFailure:
    target: str
    path: str
    error: str


class NodeMemoryPersistenceError(RuntimeError):
    def __init__(self, failures: list[NodeMemoryPersistenceFailure]):
        self.failures = tuple(failures)
        joined = "; ".join(f"{item.target} {item.path}: {item.error}" for item in self.failures)
        super().__init__("Node memory persistence failed: " + joined)


def raise_if_failures(failures: list[NodeMemoryPersistenceFailure]) -> None:
    if failures:
        raise NodeMemoryPersistenceError(failures)

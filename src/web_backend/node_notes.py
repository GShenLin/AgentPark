from __future__ import annotations


class NodeNotesDataError(ValueError):
    pass


def normalize_node_notes(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise NodeNotesDataError("graph node_notes must be an object")

    normalized: dict[str, str] = {}
    for raw_node_id, raw_note in value.items():
        node_id = str(raw_node_id or "").strip()
        if not node_id:
            raise NodeNotesDataError("graph node_notes keys must be non-empty node ids")
        if not isinstance(raw_note, str):
            raise NodeNotesDataError(f"graph node_notes.{node_id} must be a string")
        note = raw_note.strip()
        if note:
            normalized[node_id] = note
    return normalized


__all__ = ["NodeNotesDataError", "normalize_node_notes"]

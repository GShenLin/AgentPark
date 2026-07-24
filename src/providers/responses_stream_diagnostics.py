from __future__ import annotations

from typing import Any


def build_reasoning_snapshot_diagnostics(
    *,
    event: dict[str, Any],
    item_id: str,
    output_index: int | None,
    segment_index: int,
    streamed_text: str,
    snapshot_text: str,
    context_chars: int = 120,
) -> dict[str, Any]:
    common_prefix_length = 0
    comparison_length = min(len(streamed_text), len(snapshot_text))
    while (
        common_prefix_length < comparison_length
        and streamed_text[common_prefix_length] == snapshot_text[common_prefix_length]
    ):
        common_prefix_length += 1

    context_start = max(0, common_prefix_length - context_chars)
    context_end = common_prefix_length + context_chars
    return {
        "item_id": item_id,
        "output_index": output_index,
        "segment_index": segment_index,
        "sequence_number": event.get("sequence_number"),
        "streamed_length": len(streamed_text),
        "snapshot_length": len(snapshot_text),
        "common_prefix_length": common_prefix_length,
        "first_difference_index": common_prefix_length,
        "snapshot_is_prefix_of_streamed": streamed_text.startswith(snapshot_text),
        "streamed_is_prefix_of_snapshot": snapshot_text.startswith(streamed_text),
        "streamed_context_start": context_start,
        "streamed_context": streamed_text[context_start:context_end],
        "snapshot_context_start": context_start,
        "snapshot_context": snapshot_text[context_start:context_end],
    }

"""Unified stream-emit + de-dup contract shared by every provider runtime.

All streaming providers (OpenAI/doubao/gemini/zhipu/Claude ...) converge on
the same two-argument callback contract:

    stream_handler(delta_text, full_text)
    thinking_stream_handler(delta_text, full_text, provider)

``delta_text`` is the incremental text produced by the latest SSE/stream
event; ``full_text`` is the accumulated text so far (monotonically
non-decreasing within one turn). Presentation layers (CLI ``_StreamPrinter``,
companion TUI, web backend) rely on this contract to de-duplicate rendering:
they either print ``delta_text`` incrementally, or fall back to diffing
``full_text`` against what has already been printed. Because the contract is
enforced here in one place, provider runtimes do not need (and must not
implement) their own ad-hoc de-dup logic.

Historically every provider runtime (doubao/gemini/openai/zhipu) duplicated
an identical ``_emit_stream_text``/``_emit_stream_thinking`` staticmethod.
This module is the single source of truth those runtimes now delegate to.
"""

from __future__ import annotations

from typing import Callable

from src.runtime_cancellation import CancellationRequested


def emit_stream_text(
    stream_handler: Callable[[object, object], None] | None,
    delta_text: object,
    full_text: object,
) -> None:
    """Forward one text delta to ``stream_handler`` using the shared contract.

    Swallows any handler exception except cancellation so a misbehaving
    presentation layer can never break the underlying provider request loop.
    """
    if not callable(stream_handler):
        return
    try:
        stream_handler(delta_text, full_text)
    except CancellationRequested:
        raise
    except Exception:
        return


def emit_stream_thinking(
    thinking_stream_handler: Callable[[object, object, object], None] | None,
    delta_text: object,
    full_text: object,
    provider: object = "",
) -> None:
    """Forward one reasoning/thinking delta to ``thinking_stream_handler``."""
    if not callable(thinking_stream_handler):
        return
    try:
        thinking_stream_handler(delta_text, full_text, provider)
    except CancellationRequested:
        raise
    except Exception:
        return


class ProviderStreamEmitMixin:
    """Mixin giving provider runtimes the shared emit helpers as methods.

    Kept as thin ``staticmethod`` wrappers around the module-level functions
    so existing call sites (``self._emit_stream_text(...)``) keep working
    unchanged while the actual logic lives in exactly one place.
    """

    @staticmethod
    def _emit_stream_text(
        stream_handler: Callable[[object, object], None] | None,
        delta_text: object,
        full_text: object,
    ) -> None:
        emit_stream_text(stream_handler, delta_text, full_text)

    @staticmethod
    def _emit_stream_thinking(
        thinking_stream_handler: Callable[[object, object, object], None] | None,
        delta_text: object,
        full_text: object,
        provider: object = "",
    ) -> None:
        emit_stream_thinking(thinking_stream_handler, delta_text, full_text, provider)

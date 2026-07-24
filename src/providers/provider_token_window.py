from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderTokenWindowUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class _ProviderTokenUsageEntry:
    completed_at: float
    input_tokens: int
    output_tokens: int


class ProviderRollingTokenWindow:
    """Tracks completed token usage in a rolling time window."""

    def __init__(self) -> None:
        self._entries: deque[_ProviderTokenUsageEntry] = deque()
        self._input_tokens = 0
        self._output_tokens = 0

    def record(
        self,
        *,
        completed_at: float,
        input_tokens: int,
        output_tokens: int,
        window_seconds: float,
    ) -> ProviderTokenWindowUsage:
        self._evict_expired(now=completed_at, window_seconds=window_seconds)
        normalized_input = max(0, int(input_tokens))
        normalized_output = max(0, int(output_tokens))
        if normalized_input > 0 or normalized_output > 0:
            self._entries.append(
                _ProviderTokenUsageEntry(
                    completed_at=float(completed_at),
                    input_tokens=normalized_input,
                    output_tokens=normalized_output,
                )
            )
            self._input_tokens += normalized_input
            self._output_tokens += normalized_output
        return self._usage()

    def usage(self, *, now: float, window_seconds: float) -> ProviderTokenWindowUsage:
        self._evict_expired(now=now, window_seconds=window_seconds)
        return self._usage()

    def next_available_in_seconds(
        self,
        *,
        now: float,
        window_seconds: float,
        limit: int | None,
    ) -> float:
        usage = self.usage(now=now, window_seconds=window_seconds)
        if limit is None or usage.total_tokens < limit:
            return 0.0

        safe_window_seconds = max(0.001, float(window_seconds))
        remaining_total = usage.total_tokens
        for entry in self._entries:
            remaining_total -= entry.input_tokens + entry.output_tokens
            if remaining_total < limit:
                return max(0.0, entry.completed_at + safe_window_seconds - now)
        return 0.0

    def _evict_expired(self, *, now: float, window_seconds: float) -> None:
        safe_window_seconds = max(0.001, float(window_seconds))
        cutoff = float(now) - safe_window_seconds
        while self._entries and self._entries[0].completed_at <= cutoff:
            entry = self._entries.popleft()
            self._input_tokens = max(0, self._input_tokens - entry.input_tokens)
            self._output_tokens = max(0, self._output_tokens - entry.output_tokens)

    def _usage(self) -> ProviderTokenWindowUsage:
        return ProviderTokenWindowUsage(
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
        )

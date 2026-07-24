from __future__ import annotations

from dataclasses import dataclass
import re


_PYTEST_QUIET_PROGRESS_GLYPHS = frozenset(b".FEsxX")
_PYTEST_VERBOSE_STATUS = re.compile(
    rb"::[^\r\n]{1,4096}\s(?:PASSED|FAILED|SKIPPED|XFAIL|XPASS|ERROR)(?:\s|\[|$)",
    re.IGNORECASE,
)
_MAX_LINE_BUFFER_BYTES = 4096


@dataclass(frozen=True)
class ProgressWatchdogSnapshot:
    kind: str
    timeout_seconds: float
    progress_events: int
    elapsed_seconds: float
    seconds_since_progress: float

    def to_payload(self) -> dict:
        return {
            "kind": self.kind,
            "timeout_seconds": self.timeout_seconds,
            "progress_events": self.progress_events,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "seconds_since_progress": round(self.seconds_since_progress, 3),
        }


class PytestProgressWatchdog:
    """Tracks explicit pytest test-completion markers from incremental stdout.

    stderr is intentionally excluded: repeated tracebacks and logging are diagnostic
    activity, not evidence that another test case completed.
    """

    kind = "pytest"

    def __init__(
        self,
        *,
        stdout_chunks: list[bytes],
        timeout_seconds: float,
        started_at: float,
    ):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._stdout_chunks = stdout_chunks
        self._timeout_seconds = float(timeout_seconds)
        self._started_at = float(started_at)
        self._last_progress_at = float(started_at)
        self._processed_chunks = 0
        self._progress_events = 0
        self._line = bytearray()
        self._quiet_candidate = True
        self._quiet_glyph_count = 0
        self._quiet_reported_count = 0
        self._quiet_has_terminal_glyph = False

    def observe(self, *, now: float) -> None:
        current_count = len(self._stdout_chunks)
        if current_count <= self._processed_chunks:
            return
        chunks = self._stdout_chunks[self._processed_chunks:current_count]
        self._processed_chunks = current_count
        for chunk in chunks:
            self._consume(bytes(chunk), now=float(now))

    def expired(self, *, now: float) -> bool:
        return float(now) - self._last_progress_at >= self._timeout_seconds

    def snapshot(self, *, now: float) -> ProgressWatchdogSnapshot:
        current = float(now)
        return ProgressWatchdogSnapshot(
            kind=self.kind,
            timeout_seconds=self._timeout_seconds,
            progress_events=self._progress_events,
            elapsed_seconds=max(0.0, current - self._started_at),
            seconds_since_progress=max(0.0, current - self._last_progress_at),
        )

    def _consume(self, data: bytes, *, now: float) -> None:
        for value in data:
            if value == 13:
                continue
            if value == 10:
                self._finish_line(now=now)
                continue
            self._append_line_byte(value)
            self._observe_quiet_glyph(value, now=now)

    def _append_line_byte(self, value: int) -> None:
        self._line.append(value)
        if len(self._line) > _MAX_LINE_BUFFER_BYTES:
            del self._line[: len(self._line) - _MAX_LINE_BUFFER_BYTES]

    def _observe_quiet_glyph(self, value: int, *, now: float) -> None:
        if not self._quiet_candidate:
            return
        if value in _PYTEST_QUIET_PROGRESS_GLYPHS:
            self._quiet_glyph_count += 1
            if value != ord("."):
                self._quiet_has_terminal_glyph = True
            minimum_run = 2 if self._quiet_has_terminal_glyph else 4
            if self._quiet_glyph_count >= minimum_run:
                newly_reported = self._quiet_glyph_count - self._quiet_reported_count
                if newly_reported > 0:
                    self._record_progress(newly_reported, now=now)
                    self._quiet_reported_count = self._quiet_glyph_count
            return
        if value in b" \t" and (
            self._quiet_glyph_count == 0 or self._quiet_reported_count > 0
        ):
            return
        self._quiet_candidate = False

    def _finish_line(self, *, now: float) -> None:
        if _PYTEST_VERBOSE_STATUS.search(bytes(self._line)):
            self._record_progress(1, now=now)
        self._line.clear()
        self._quiet_candidate = True
        self._quiet_glyph_count = 0
        self._quiet_reported_count = 0
        self._quiet_has_terminal_glyph = False

    def _record_progress(self, count: int, *, now: float) -> None:
        self._progress_events += int(count)
        self._last_progress_at = float(now)

"""Per-attempt timings and terminal evidence for CurlHttpTransport streams."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
import uuid

from src.providers.provider_runtime_events import emit_provider_runtime_notice


METRICS_MARKER = "__CURL_STREAM_METRICS__:"
METRICS_FORMAT = '%{stderr}\n' + METRICS_MARKER + (
    '{"http_code":"%{http_code}","connect_seconds":%{time_connect},'
    '"tls_seconds":%{time_appconnect},"first_byte_seconds":%{time_starttransfer},'
    '"total_seconds":%{time_total}}\n'
)


def read_stream_stderr(handle) -> tuple[str, dict]:
    handle.seek(0)
    text = handle.read().decode("utf-8", errors="replace")
    errors, metrics = [], {}
    for line in text.splitlines():
        if line.startswith(METRICS_MARKER):
            payload = line[len(METRICS_MARKER):]
            try:
                metrics = json.loads(payload)
                metrics["http_code"] = int(metrics["http_code"])
            except json.JSONDecodeError:
                errors.append("Invalid curl stream timing record: " + payload)
        else:
            errors.append(line)
    return "\n".join(errors).strip(), metrics


@dataclass
class CurlStreamDiagnostics:
    owner: object
    attempt_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started: float = field(default_factory=time.perf_counter)
    queued_at: float | None = None
    acquired_at: float | None = None
    process_started: float | None = None
    first_byte: float | None = None
    last_byte: float | None = None
    received_bytes: int = 0
    eof: bool = False
    reason: str = "consumer_closed"

    def emit(self, stage: str, **details) -> None:
        emit_provider_runtime_notice(
            getattr(self.owner, "tool_event_callback", None),
            provider=getattr(self.owner, "provider_name", "provider"),
            stage=stage, message=json.dumps({"attempt_id": self.attempt_id, **details}),
        )

    def process_ready(self) -> None:
        self.process_started = time.perf_counter()
        self.emit("curl_stream_process_started", queue_wait_ms=self.queue_wait_ms(),
                  process_launch_ms=self.ms(self.process_started - self.acquired_at))

    def queue_wait_ms(self) -> float | None:
        if self.queued_at is None or self.acquired_at is None:
            return None
        return self.ms(self.acquired_at - self.queued_at)

    def received(self, count: int, received_at: float) -> None:
        self.received_bytes += count
        self.last_byte = received_at
        if self.first_byte is None:
            self.first_byte = received_at
            self.emit("curl_stream_first_byte", elapsed_ms=self.ms(received_at - self.started))

    @staticmethod
    def ms(seconds: float) -> float:
        return round(seconds * 1000, 3)

    def finish(self, *, return_code: int | None, killed: bool, stderr: str, metrics: dict) -> None:
        now = time.perf_counter()
        self.emit("curl_stream_end", reason=self.reason, eof=self.eof, return_code=return_code,
                  killed=killed, stderr=stderr, curl_timings=metrics, received_bytes=self.received_bytes,
                  elapsed_ms=self.ms(now - self.started),
                  queue_wait_ms=self.queue_wait_ms(),
                  first_byte_ms=None if self.first_byte is None else self.ms(self.first_byte - self.started),
                  receive_ms=None if self.first_byte is None or self.last_byte is None
                  else self.ms(self.last_byte - self.first_byte),
                  tail_wait_ms=None if self.last_byte is None else self.ms(now - self.last_byte))

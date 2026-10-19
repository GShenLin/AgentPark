"""SSE process lifetime for CurlHttpTransport; not a separate HTTP client."""
import queue
import os
import subprocess
import tempfile
import threading
import time
from typing import Iterable
from src.runtime_cancellation import CancellationRequested, raise_if_cancel_requested
from .curl_types import CurlResponse, CurlTransportError
from .curl_stream_diagnostics import CurlStreamDiagnostics, METRICS_FORMAT, read_stream_stderr


class CurlStreamMixin:
    def _curl_post_sse_raw_lines(
        self, *, url: str, headers: dict, payload_json: str, timeout_sec: float,
        marker: str, yield_all_lines: bool = False,
    ) -> Iterable[CurlResponse | str]:
        idle_timeout = max(1, float(timeout_sec))
        connect_timeout = max(1, min(15, idle_timeout))
        payload_path, proc = "", None
        response_lines: list[str] = []
        status_code = None
        cancel_source = self._cancel_source()
        diagnostics = CurlStreamDiagnostics(self)
        stderr_file = tempfile.TemporaryFile()
        pending = b""
        killed = False
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as temp_file:
                temp_file.write(payload_json)
                payload_path = temp_file.name
            cmd = self._build_curl_post_command(
                url=url, headers=headers, payload_path=payload_path, timeout_val=None,
                connect_timeout=connect_timeout, marker=marker, no_buffer=True, write_out=METRICS_FORMAT,
            )
            # Only explicit timing/status fields go to stderr, never request
            # headers, credentials or URLs. A file also avoids stderr pipe stalls.
            diagnostics.queued_at = time.perf_counter()
            diagnostics.emit("curl_stream_queued")
            with self._provider_pressure_slot():
                diagnostics.acquired_at = time.perf_counter()
                raise_if_cancel_requested(cancel_source)
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=stderr_file, bufsize=0,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                diagnostics.process_ready()
                if proc.stdout is None:
                    raise CurlTransportError("curl stdout pipe is unavailable")
                chunks: queue.Queue[tuple[bytes, float] | Exception | None] = queue.Queue()

                def read_stdout() -> None:
                    try:
                        while chunk := proc.stdout.read(65536):
                            chunks.put((chunk, time.perf_counter()))
                    except Exception as exc:
                        chunks.put(exc)
                    finally:
                        chunks.put(None)

                reader = threading.Thread(target=read_stdout, daemon=True, name="curl-sse-reader")
                reader.start()
                last_activity = time.monotonic()
                while True:
                    raise_if_cancel_requested(cancel_source)
                    if time.monotonic() - last_activity >= idle_timeout:
                        diagnostics.reason = "idle_timeout"
                        raise CurlTransportError(f"curl idle timeout after {idle_timeout:g}s without stream data")
                    try:
                        received = chunks.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    if received is None:
                        diagnostics.eof = True
                        break
                    if isinstance(received, Exception):
                        diagnostics.reason = "read_error"
                        raise CurlTransportError(f"curl stdout read failed: {received}") from received
                    chunk, received_at = received
                    last_activity = time.monotonic()
                    diagnostics.received(len(chunk), received_at)
                    pending += chunk
                    while b"\n" in pending:
                        raw_line, pending = pending.split(b"\n", 1)
                        line = raw_line.rstrip(b"\r").decode("utf-8")
                        response_lines.append(line)
                        if line.startswith("data:"):
                            yield line[5:].strip()
                        elif yield_all_lines and line.strip():
                            yield line.strip()
                try:
                    return_code = proc.wait(timeout=5)
                except subprocess.TimeoutExpired as exc:
                    diagnostics.reason = "exit_timeout"
                    raise CurlTransportError(f"curl exit timeout: {exc}") from exc
                stderr, metrics = read_stream_stderr(stderr_file)
                if "http_code" in metrics:
                    status_code = metrics["http_code"]
                if return_code != 0:
                    diagnostics.reason = "transport_error"
                    raise CurlTransportError(stderr or f"curl exit code: {return_code}")
                if status_code is None:
                    diagnostics.reason = "missing_http_status"
                    raise CurlTransportError("missing HTTP status from curl: " + stderr)
                if not 200 <= status_code < 300:
                    # HTTP error bodies are not SSE and need no final newline.
                    if pending:
                        response_lines.append(pending.decode("utf-8"))
                    diagnostics.reason = "http_error"
                    yield CurlResponse(body="\n".join(response_lines), status_code=status_code)
                    return
                # EOF cannot turn an unfinished data line into a complete SSE
                # event. Check curl's terminal error first to retain its cause.
                if pending.strip():
                    diagnostics.reason = "truncated_line"
                    raise CurlTransportError(f"curl stream ended with an unterminated line ({len(pending)} bytes)")
                diagnostics.reason = "eof"
                yield CurlResponse(body="\n".join(response_lines), status_code=status_code)
        except CancellationRequested:
            diagnostics.reason = "cancelled"
            raise
        except CurlTransportError:
            if diagnostics.reason == "consumer_closed":
                diagnostics.reason = "transport_error"
            raise
        except Exception as exc:
            diagnostics.reason = "stream_error"
            raise CurlTransportError(str(exc)) from exc
        finally:
            try:
                if proc is not None and proc.poll() is None:
                    killed = True
                    proc.kill()
                    proc.wait(timeout=5)
                stderr, metrics = read_stream_stderr(stderr_file)
                diagnostics.finish(return_code=None if proc is None else proc.poll(),
                                   killed=killed, stderr=stderr, metrics=metrics)
            finally:
                if proc is not None and proc.stdout is not None:
                    proc.stdout.close()
                stderr_file.close()
                self._remove_temp_payload(payload_path)

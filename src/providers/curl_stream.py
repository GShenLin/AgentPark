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


class CurlStreamMixin:
    def _curl_post_sse_raw_lines(
        self,
        *,
        url: str,
        headers: dict,
        payload_json: str,
        timeout_sec: float,
        marker: str,
        yield_all_lines: bool = False,
    ) -> Iterable[CurlResponse | str]:
        idle_timeout = int(max(1, float(timeout_sec or 60)))
        connect_timeout = max(1, min(15, idle_timeout))
        payload_path = ""
        proc = None
        response_lines: list[str] = []
        status_code = None
        cancel_source = self._cancel_source()
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as temp_file:
                temp_file.write(payload_json)
                payload_path = temp_file.name

            cmd = self._build_curl_post_command(
                url=url,
                headers=headers,
                payload_path=payload_path,
                # Active SSE streams may legitimately outlive one timeout
                # interval. The read loop below enforces an inactivity timeout.
                timeout_val=None,
                connect_timeout=connect_timeout,
                marker=marker,
                no_buffer=True,
            )
            with self._provider_pressure_slot():
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if proc.stdout is None:
                    raise CurlTransportError("curl stdout pipe is unavailable")

                line_queue: queue.Queue[str | None] = queue.Queue()

                def _read_stdout() -> None:
                    try:
                        for raw in proc.stdout:
                            line_queue.put(raw)
                    finally:
                        line_queue.put(None)

                threading.Thread(target=_read_stdout, daemon=True, name="curl-sse-reader").start()
                last_activity = time.monotonic()
                while True:
                    raise_if_cancel_requested(cancel_source)
                    if time.monotonic() - last_activity >= idle_timeout:
                        raise CurlTransportError(f"curl idle timeout after {idle_timeout}s without stream data")
                    try:
                        raw_line = line_queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    if raw_line is None:
                        break
                    last_activity = time.monotonic()
                    line = raw_line.rstrip("\r\n")
                    if line.startswith(marker):
                        status_code = self._parse_curl_status(line[len(marker) :].strip())
                        continue
                    response_lines.append(line)
                    if line.startswith("data:"):
                        yield line[5:].strip()
                    elif yield_all_lines and line.strip():
                        yield line.strip()

                try:
                    return_code = proc.wait(timeout=5)
                except subprocess.TimeoutExpired as exc:
                    proc.kill()
                    raise CurlTransportError(f"curl timeout: {exc}") from exc

                stderr = proc.stderr.read().strip() if proc.stderr is not None else ""
                if return_code != 0:
                    detail = stderr or "\n".join(response_lines[-20:])
                    raise CurlTransportError(detail or f"curl exit code: {return_code}")
                if status_code is None:
                    detail = stderr or "\n".join(response_lines[-20:])
                    raise CurlTransportError(f"missing HTTP status from curl: {detail}")
                yield CurlResponse(body="\n".join(response_lines), status_code=status_code)
        except CancellationRequested:
            raise
        except CurlTransportError:
            raise
        except Exception as exc:
            raise CurlTransportError(str(exc)) from exc
        finally:
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
            self._remove_temp_payload(payload_path)

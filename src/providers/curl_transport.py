import os
import queue
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from contextlib import contextmanager
from typing import Iterable

from src.providers.provider_pressure import acquire_provider_pressure
from src.providers.provider_errors import ProviderTransportError
from src.runtime_cancellation import CancellationRequested, raise_if_cancel_requested


@dataclass(frozen=True)
class CurlResponse:
    body: str
    status_code: int


class CurlTransportError(ProviderTransportError):
    pass


class CurlHttpTransport:
    @staticmethod
    def _curl_executable() -> str:
        return "curl.exe" if os.name == "nt" else "curl"

    def _cancel_source(self):
        return getattr(self, "cancel_event", None) or getattr(self, "cancel_check", None)

    @contextmanager
    def _provider_pressure_slot(self):
        with acquire_provider_pressure(self, cancel_source=self._cancel_source()):
            yield

    def _curl_get_bytes_raw(self, *, url: str, timeout_sec: float) -> bytes:
        timeout_val = int(max(1, float(timeout_sec or 60)))
        connect_timeout = max(1, min(15, timeout_val))
        try:
            with self._provider_pressure_slot():
                proc = subprocess.run(
                    [
                        self._curl_executable(),
                        "--silent",
                        "--show-error",
                        "--location",
                        "--max-time",
                        str(timeout_val),
                        "--connect-timeout",
                        str(connect_timeout),
                        str(url),
                    ],
                    capture_output=True,
                    timeout=timeout_val + 10,
                )
        except subprocess.TimeoutExpired as exc:
            raise CurlTransportError(f"curl timeout: {exc}") from exc
        except Exception as exc:
            raise CurlTransportError(str(exc)) from exc

        if proc.returncode != 0:
            stderr_text = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
            raise CurlTransportError(stderr_text or f"curl exit code: {proc.returncode}")
        return proc.stdout or b""

    def _curl_get_text_once_raw(self, *, url: str, headers: dict, timeout_sec: float, marker: str) -> CurlResponse:
        timeout_val = int(max(1, float(timeout_sec or 60)))
        connect_timeout = max(1, min(15, timeout_val))
        try:
            cmd = [
                self._curl_executable(),
                "--silent",
                "--show-error",
                "--location",
                "--max-time",
                str(timeout_val),
                "--connect-timeout",
                str(connect_timeout),
                str(url),
            ]
            for key, value in (headers or {}).items():
                cmd.extend(["-H", f"{key}: {value}"])
            cmd.extend(["-w", f"\n{marker}%{{http_code}}"])
            with self._provider_pressure_slot():
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_val + 10,
                )
        except subprocess.TimeoutExpired as exc:
            raise CurlTransportError(f"curl timeout: {exc}") from exc
        except Exception as exc:
            raise CurlTransportError(str(exc)) from exc

        stdout = proc.stdout or ""
        stderr = (proc.stderr or "").strip()
        marker_pos = stdout.rfind(f"\n{marker}")
        if marker_pos < 0:
            detail = stderr or stdout[-400:]
            raise CurlTransportError(f"invalid curl output: {detail}")

        body = stdout[:marker_pos]
        status_text = stdout[marker_pos + len(f"\n{marker}") :].strip().splitlines()[0]
        status_code = self._parse_curl_status(status_text)
        if proc.returncode != 0:
            detail = stderr or body[-400:]
            raise CurlTransportError(detail or f"curl exit code: {proc.returncode}")
        return CurlResponse(body=body, status_code=status_code)

    def _curl_post_once_raw(
        self,
        *,
        url: str,
        headers: dict,
        payload_json: str,
        timeout_sec: float,
        marker: str,
        no_buffer: bool = False,
    ) -> CurlResponse:
        timeout_val = int(max(1, float(timeout_sec or 60)))
        connect_timeout = max(1, min(15, timeout_val))
        payload_path = ""
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as temp_file:
                temp_file.write(payload_json)
                payload_path = temp_file.name

            cmd = self._build_curl_post_command(
                url=url,
                headers=headers,
                payload_path=payload_path,
                timeout_val=timeout_val,
                connect_timeout=connect_timeout,
                marker=marker,
                no_buffer=no_buffer,
            )
            with self._provider_pressure_slot():
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_val + 10,
                )
        except subprocess.TimeoutExpired as exc:
            raise CurlTransportError(f"curl timeout: {exc}") from exc
        except Exception as exc:
            raise CurlTransportError(str(exc)) from exc
        finally:
            self._remove_temp_payload(payload_path)

        stdout = proc.stdout or ""
        stderr = (proc.stderr or "").strip()
        marker_pos = stdout.rfind(f"\n{marker}")
        if marker_pos < 0:
            detail = stderr or stdout[-400:]
            raise CurlTransportError(f"invalid curl output: {detail}")

        body = stdout[:marker_pos]
        status_text = stdout[marker_pos + len(f"\n{marker}") :].strip().splitlines()[0]
        status_code = self._parse_curl_status(status_text)
        if proc.returncode != 0:
            detail = stderr or body[-400:]
            raise CurlTransportError(detail or f"curl exit code: {proc.returncode}")
        return CurlResponse(body=body, status_code=status_code)

    def _curl_post_sse_raw_lines(
        self,
        *,
        url: str,
        headers: dict,
        payload_json: str,
        timeout_sec: float,
        marker: str,
    ) -> Iterable[CurlResponse | str]:
        timeout_val = int(max(1, float(timeout_sec or 60)))
        connect_timeout = max(1, min(15, timeout_val))
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
                    if time.monotonic() - last_activity >= timeout_val:
                        raise CurlTransportError(f"curl idle timeout after {timeout_val}s without stream data")
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

    @staticmethod
    def _parse_curl_status(status_text: str) -> int:
        try:
            return int(str(status_text or "").strip())
        except Exception as exc:
            raise CurlTransportError(f"invalid HTTP status from curl: {status_text}") from exc

    @staticmethod
    def _remove_temp_payload(payload_path: str) -> None:
        if not payload_path:
            return
        try:
            os.remove(payload_path)
        except Exception:
            pass

    @classmethod
    def _build_curl_post_command(cls, *, url, headers, payload_path, timeout_val, connect_timeout, marker, no_buffer):
        cmd = [
            cls._curl_executable(),
            "--silent",
            "--show-error",
            "--location",
            "--connect-timeout",
            str(connect_timeout),
            "-X",
            "POST",
            str(url),
        ]
        if no_buffer:
            cmd.insert(3, "--no-buffer")
        if timeout_val is not None:
            cmd[4:4] = ["--max-time", str(timeout_val)]
        for key, value in (headers or {}).items():
            cmd.extend(["-H", f"{key}: {value}"])
        cmd.extend(["--data-binary", f"@{payload_path}", "-w", f"\n{marker}%{{http_code}}"])
        return cmd

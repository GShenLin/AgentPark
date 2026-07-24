import os
import queue
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from contextlib import contextmanager
from urllib.parse import urlparse
from typing import Iterable

from src.providers.provider_pressure import acquire_provider_pressure
from src.providers.provider_errors import ProviderTransportError
from src.runtime_cancellation import CancellationRequested, raise_if_cancel_requested


@dataclass(frozen=True)
class CurlResponse:
    body: str
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)


class CurlTransportError(ProviderTransportError):
    pass


class CurlHttpTransport:
    _WINDOWS_PROXY_CACHE: str | None = None
    _GENERIC_HTTP_MARKER = "__AGENTPARK_HTTP_CODE__:"

    def post_json_response(
        self,
        *,
        url: str,
        headers: dict,
        payload_json: str,
        timeout_sec: float,
    ) -> CurlResponse:
        return self._curl_post_once_raw(
            url=url,
            headers=headers,
            payload_json=payload_json,
            timeout_sec=timeout_sec,
            marker=self._GENERIC_HTTP_MARKER,
        )

    def stream_sse_data(
        self,
        *,
        url: str,
        headers: dict,
        payload_json: str,
        timeout_sec: float,
    ) -> Iterable[CurlResponse | str]:
        return self._curl_post_sse_raw_lines(
            url=url,
            headers=headers,
            payload_json=payload_json,
            timeout_sec=timeout_sec,
            marker=self._GENERIC_HTTP_MARKER,
        )

    @staticmethod
    def _curl_executable() -> str:
        return "curl.exe" if os.name == "nt" else "curl"

    @classmethod
    def _curl_proxy_args(cls, url: str) -> list[str]:
        if cls._url_is_loopback(url):
            return []
        proxy_url = cls._fallback_proxy_url()
        return ["--proxy", proxy_url] if proxy_url else []

    @staticmethod
    def _url_is_loopback(url: str) -> bool:
        try:
            host = (urlparse(str(url or "")).hostname or "").strip().lower()
        except Exception:
            host = ""
        if not host:
            return False
        return host == "localhost" or host == "::1" or host.startswith("127.")

    @classmethod
    def _fallback_proxy_url(cls) -> str:
        for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"):
            value = str(os.environ.get(name) or "").strip()
            if value:
                return ""
        if os.name != "nt":
            return ""
        if cls._WINDOWS_PROXY_CACHE is not None:
            return cls._WINDOWS_PROXY_CACHE
        cls._WINDOWS_PROXY_CACHE = cls._read_windows_user_proxy()
        return cls._WINDOWS_PROXY_CACHE

    @staticmethod
    def _read_windows_user_proxy() -> str:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
                proxy_enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0)
                if not proxy_enabled:
                    return ""
                raw_proxy = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "").strip()
        except Exception:
            return ""
        return CurlHttpTransport._normalize_windows_proxy(raw_proxy)

    @staticmethod
    def _normalize_windows_proxy(raw_proxy: str) -> str:
        text = str(raw_proxy or "").strip()
        if not text:
            return ""
        selected = ""
        if ";" in text or "=" in text:
            parts = [part.strip() for part in text.split(";") if part.strip()]
            parsed: dict[str, str] = {}
            for part in parts:
                if "=" not in part:
                    continue
                key, value = part.split("=", 1)
                parsed[key.strip().lower()] = value.strip()
            selected = parsed.get("https") or parsed.get("http") or parsed.get("socks") or ""
        else:
            selected = text
        if not selected:
            return ""
        if "://" not in selected:
            selected = f"http://{selected}"
        return selected

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
                proxy_args = self._curl_proxy_args(str(url))
                if proxy_args:
                    cmd[1:1] = proxy_args
                proc = subprocess.run(
                    cmd,
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
            proxy_args = self._curl_proxy_args(str(url))
            if proxy_args:
                cmd[1:1] = proxy_args
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
        header_path = ""
        response_headers: dict[str, str] = {}
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as temp_file:
                temp_file.write(payload_json)
                payload_path = temp_file.name
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".headers", delete=False) as header_file:
                header_path = header_file.name

            cmd = self._build_curl_post_command(
                url=url,
                headers=headers,
                payload_path=payload_path,
                timeout_val=timeout_val,
                connect_timeout=connect_timeout,
                marker=marker,
                no_buffer=no_buffer,
            )
            cmd.extend(["--dump-header", header_path])
            with self._provider_pressure_slot():
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_val + 10,
                )
            response_headers = self._read_response_headers(header_path)
        except subprocess.TimeoutExpired as exc:
            raise CurlTransportError(f"curl timeout: {exc}") from exc
        except Exception as exc:
            raise CurlTransportError(str(exc)) from exc
        finally:
            self._remove_temp_payload(payload_path)
            self._remove_temp_payload(header_path)

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
        return CurlResponse(body=body, status_code=status_code, headers=response_headers)

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

    @staticmethod
    def _read_response_headers(header_path: str) -> dict[str, str]:
        if not header_path or not os.path.isfile(header_path):
            return {}
        try:
            with open(header_path, "r", encoding="iso-8859-1") as handle:
                text = handle.read()
        except OSError:
            return {}
        blocks = [block for block in text.replace("\r\n", "\n").split("\n\n") if block.strip()]
        for block in reversed(blocks):
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines or not lines[0].upper().startswith("HTTP/"):
                continue
            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
            return headers
        return {}

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
        proxy_args = cls._curl_proxy_args(str(url))
        if proxy_args:
            cmd[1:1] = proxy_args
        if no_buffer:
            cmd.insert(3, "--no-buffer")
        if timeout_val is not None:
            cmd[4:4] = ["--max-time", str(timeout_val)]
        for key, value in (headers or {}).items():
            cmd.extend(["-H", f"{key}: {value}"])
        cmd.extend(["--data-binary", f"@{payload_path}", "-w", f"\n{marker}%{{http_code}}"])
        return cmd

import os
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlparse
from typing import Iterable
import asyncio
from pathlib import Path
from .curl_types import CurlResponse, CurlTransportError, CurlHttpError
from .curl_stream import CurlStreamMixin

from src.runtime_cancellation import CancellationRequested, raise_if_cancel_requested


class CurlHttpTransport(CurlStreamMixin):
    _WINDOWS_PROXY_CACHE: str | None = None
    _GENERIC_HTTP_MARKER = "__AGENTPARK_HTTP_CODE__:"

    @staticmethod
    def cookie_header(cookie_file: str, url: str) -> str:
        """Select curl's persisted cookies for the WebSocket upgrade at this URL."""
        from http.cookiejar import MozillaCookieJar
        jar = MozillaCookieJar(cookie_file)
        if not os.path.exists(cookie_file):
            return ""
        # curl writes session cookies with expiry 0; CookieJar otherwise drops them.
        jar.load(ignore_discard=True, ignore_expires=True)
        target = urlparse(url)
        host, path = target.hostname or "", target.path or "/"
        selected = []
        for cookie in jar:
            if cookie.expires not in (None, 0) and cookie.expires <= time.time():
                continue
            domain = cookie.domain.lstrip(".")
            if host != domain and not (cookie.domain_specified and host.endswith("." + domain)):
                continue
            if cookie.secure and target.scheme not in {"https", "wss"}:
                continue
            if path != cookie.path and not path.startswith(cookie.path.rstrip("/") + "/"):
                continue
            selected.append(cookie)
        return "; ".join(f"{c.name}={c.value}" for c in sorted(selected, key=lambda c: -len(c.path)))

    def request(self, *, url: str, method: str = "GET", headers: dict | None = None,
                body: bytes | None = None, timeout_sec: float = 60,
                connect_timeout: float = 15, follow_redirects: bool = True,
                trust_env: bool = True, cookie_file: str | None = None,
                max_response_bytes: int | None = None, cancel_event=None,
                revocation_best_effort: bool = False) -> CurlResponse:
        """One binary-safe HTTP exchange; HTTP status is returned, never retried."""
        if urlparse(url).scheme not in {"http", "https"}:
            raise ValueError("curl transport only accepts HTTP/HTTPS URLs")
        if not method.isalpha():
            raise ValueError("Invalid HTTP method")
        if body is not None and not isinstance(body, bytes):
            raise TypeError("HTTP body must be bytes")
        timeout_sec = max(.001, float(timeout_sec))
        with tempfile.TemporaryDirectory(prefix="agentpark-curl-") as folder:
            root = Path(folder)
            output, response_headers = root / "body", root / "headers"
            header_lines = []
            for name, value in (headers or {}).items():
                if any(c in str(name) + str(value) for c in "\r\n\x00"):
                    raise ValueError("Invalid HTTP header")
                header_lines.append(f"{name}: {value}")
            (root / "request-headers").write_text("\n".join(header_lines), encoding="utf-8")
            cmd = [self._curl_executable(), "--disable", "--silent", "--show-error",
                   "--globoff", "--proto", "=http,https", "--proto-redir", "=http,https",
                   "--max-time", str(timeout_sec), "--connect-timeout", str(min(connect_timeout, timeout_sec)),
                   "--output", str(output), "--dump-header", str(response_headers),
                   "--write-out", "%{http_code}", "--header", "@" + str(root / "request-headers")]
            if follow_redirects:
                cmd += ["--location", "--max-redirs", "10"]
            if revocation_best_effort and os.name == "nt":
                # Private CAs may publish no CRL. Still verify chain, name and known revocations.
                cmd += ["--ssl-revoke-best-effort"]
            if not trust_env or self._url_is_loopback(url):
                cmd += ["--noproxy", "*"]
            else:
                cmd += self._curl_proxy_args(url)
            if cookie_file is not None:
                cmd += ["--cookie", cookie_file, "--cookie-jar", cookie_file]
            if max_response_bytes is not None:
                cmd += ["--max-filesize", str(max_response_bytes)]
            if body is not None:
                (root / "request-body").write_bytes(body)
                cmd += ["--data-binary", "@" + str(root / "request-body")]
            if method.upper() == "HEAD":
                cmd += ["--head"]
            elif (method.upper() not in {"GET", "POST"}
                  or (method.upper() == "POST" and body is None)
                  or (method.upper() == "GET" and body is not None)):
                cmd += ["--request", method.upper()]
            cmd += ["--url", url]
            proc = None
            try:
                with self._provider_pressure_slot():
                    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    deadline = time.monotonic() + timeout_sec + 5
                    while True:
                        raise_if_cancel_requested(cancel_event)
                        raise_if_cancel_requested(self._cancel_source())
                        if time.monotonic() >= deadline:
                            raise CurlTransportError("curl request timed out")
                        try:
                            stdout, stderr = proc.communicate(timeout=.05)
                            break
                        except subprocess.TimeoutExpired:
                            continue
                if proc.returncode:
                    raise CurlTransportError(stderr.decode("utf-8", errors="replace").strip()
                                             or f"curl exit code: {proc.returncode}")
                data = output.read_bytes()
                if max_response_bytes is not None and len(data) > max_response_bytes:
                    raise CurlTransportError("HTTP response exceeds size limit")
                return CurlResponse(data.decode("utf-8", errors="replace"),
                                    self._parse_curl_status(stdout.decode("ascii")),
                                    self._read_response_headers(str(response_headers)), data)
            except OSError as exc:
                raise CurlTransportError(str(exc)) from exc
            finally:
                if proc is not None:
                    if proc.poll() is None:
                        proc.kill()
                    proc.communicate()

    async def request_async(self, **kwargs) -> CurlResponse:
        """Cancel and reap the curl process before releasing an async caller."""
        cancelled = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(self.request, cancel_event=cancelled, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled.set()
            try:
                await task
            except (CancellationRequested, CurlTransportError):
                pass
            raise

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
            return ["--noproxy", "*"]
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
        from src.providers.provider_pressure import acquire_provider_pressure
        with acquire_provider_pressure(self, cancel_source=self._cancel_source()):
            yield

    def _curl_get_bytes_raw(self, *, url: str, timeout_sec: float) -> bytes:
        return self.request(url=url, timeout_sec=timeout_sec).content

    def _curl_get_text_once_raw(self, *, url: str, headers: dict, timeout_sec: float, marker: str) -> CurlResponse:
        return self.request(url=url, headers=headers, timeout_sec=timeout_sec)

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
        return self.request(url=url, method="POST", headers=headers, body=payload_json.encode("utf-8"), timeout_sec=timeout_sec)


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
            "--disable",
            "--silent",
            "--show-error",
            "--globoff",
            "--proto", "=http,https",
            "--proto-redir", "=http,https",
            "--location",
            "--connect-timeout",
            str(connect_timeout),
            "-X",
            "POST",
            str(url),
        ]
        cmd.extend(cls._curl_proxy_args(str(url)))
        if no_buffer:
            cmd.append("--no-buffer")
        if timeout_val is not None:
            cmd.extend(["--max-time", str(timeout_val)])
        for key, value in (headers or {}).items():
            cmd.extend(["-H", f"{key}: {value}"])
        cmd.extend(["--data-binary", f"@{payload_path}", "-w", f"\n{marker}%{{http_code}}"])
        return cmd

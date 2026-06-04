import json
import os
import random
import subprocess
import tempfile
import time
from datetime import datetime
from typing import Callable

from src.providers.doubao_agent_common import _CurlHTTPError, _CurlTransportError, format_doubao_http_error
from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.service_host import HostBoundService


class DoubaoHttpTransport(ProviderRuntimeEventMixin, HostBoundService):
    def _mask_headers_for_log(self, headers):
        masked = {}
        if not isinstance(headers, dict):
            return masked
        for key, value in headers.items():
            k = str(key)
            v = str(value)
            if k.lower() == "authorization":
                if " " in v:
                    scheme = v.split(" ", 1)[0]
                    masked[k] = f"{scheme} ***"
                else:
                    masked[k] = "***"
            else:
                masked[k] = v
        return masked

    def _http_debug_dump_path(self, prefix):
        runtime_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        debug_dir = os.path.join(runtime_root, "memories", "_http_debug")
        os.makedirs(debug_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return os.path.join(debug_dir, f"{prefix}_{ts}_{os.getpid()}.json")

    def _dump_http_400_request(self, *, endpoint, url, method, headers, payload_json, status_code, response_body):
        masked_headers = self._mask_headers_for_log(headers)
        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "provider": self.provider_name,
            "endpoint": str(endpoint),
            "request": {
                "method": str(method),
                "url": str(url),
                "headers": masked_headers,
                "body": payload_json,
            },
            "response": {
                "status_code": int(status_code),
                "body": str(response_body),
            },
        }
        dump_path = ""
        try:
            dump_path = self._http_debug_dump_path("doubao_http400")
            with open(dump_path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
        except Exception as write_error:
            print(f"[DouBao][HTTP400] Failed to write debug dump: {write_error}")

        print("\n[DouBao][HTTP400] Request dump begin")
        print(f"[DouBao][HTTP400] endpoint={endpoint}")
        print(f"[DouBao][HTTP400] method={method}")
        print(f"[DouBao][HTTP400] url={url}")
        print(f"[DouBao][HTTP400] request_headers={json.dumps(masked_headers, ensure_ascii=False)}")
        print(f"[DouBao][HTTP400] request_body={payload_json}")
        print(f"[DouBao][HTTP400] response_status={status_code}")
        print(f"[DouBao][HTTP400] response_body={response_body}")
        if dump_path:
            print(f"[DouBao][HTTP400] dump_file={dump_path}")
        print("[DouBao][HTTP400] Request dump end\n")

    @staticmethod
    def _http_status_retryable(status_code):
        code = int(status_code or 0)
        return code == 429 or code >= 500

    def _curl_post_json_once(self, *, url, headers, payload_json, timeout_sec):
        timeout_val = int(max(1, float(timeout_sec or 60)))
        connect_timeout = max(1, min(15, timeout_val))
        payload_path = ""
        marker = "__DOUBAO_HTTP_CODE__:"
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as temp_file:
                temp_file.write(payload_json)
                payload_path = temp_file.name

            cmd = [
                "curl.exe",
                "--silent",
                "--show-error",
                "--location",
                "--max-time",
                str(timeout_val),
                "--connect-timeout",
                str(connect_timeout),
                "-X",
                "POST",
                str(url),
            ]
            for key, value in (headers or {}).items():
                cmd.extend(["-H", f"{key}: {value}"])
            cmd.extend(["--data-binary", f"@{payload_path}", "-w", f"\n{marker}%{{http_code}}"])
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_val + 10,
            )
        except subprocess.TimeoutExpired as e:
            raise _CurlTransportError(f"curl timeout: {e}") from e
        except Exception as e:
            raise _CurlTransportError(str(e)) from e
        finally:
            if payload_path:
                try:
                    os.remove(payload_path)
                except Exception:
                    pass

        stdout = proc.stdout or ""
        stderr = (proc.stderr or "").strip()
        marker_pos = stdout.rfind(f"\n{marker}")
        if marker_pos < 0:
            detail = stderr or stdout[-400:]
            raise _CurlTransportError(f"invalid curl output: {detail}")

        body = stdout[:marker_pos]
        status_text = stdout[marker_pos + len(f"\n{marker}") :].strip().splitlines()[0]
        try:
            status_code = int(status_text)
        except Exception as e:
            raise _CurlTransportError(f"invalid HTTP status from curl: {status_text}") from e

        if proc.returncode != 0:
            detail = stderr or body[-400:]
            raise _CurlTransportError(detail or f"curl exit code: {proc.returncode}")
        if status_code != 200:
            raise _CurlHTTPError(status_code, body)

        try:
            return json.loads(body)
        except Exception as e:
            preview = body[:500]
            raise RuntimeError(f"Invalid JSON response: {e}; body={preview}") from e

    def _curl_get_bytes_once(self, *, url, timeout_sec):
        timeout_val = int(max(1, float(timeout_sec or 60)))
        connect_timeout = max(1, min(15, timeout_val))
        try:
            proc = subprocess.run(
                [
                    "curl.exe",
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
        except subprocess.TimeoutExpired as e:
            raise _CurlTransportError(f"curl timeout: {e}") from e
        except Exception as e:
            raise _CurlTransportError(str(e)) from e

        if proc.returncode != 0:
            stderr_text = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
            raise _CurlTransportError(stderr_text or f"curl exit code: {proc.returncode}")
        return proc.stdout or b""

    def _curl_get_json_once(self, *, url, headers, timeout_sec):
        timeout_val = int(max(1, float(timeout_sec or 60)))
        connect_timeout = max(1, min(15, timeout_val))
        marker = "__DOUBAO_HTTP_CODE__:"
        try:
            cmd = [
                "curl.exe",
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
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_val + 10,
            )
        except subprocess.TimeoutExpired as e:
            raise _CurlTransportError(f"curl timeout: {e}") from e
        except Exception as e:
            raise _CurlTransportError(str(e)) from e

        stdout = proc.stdout or ""
        stderr = (proc.stderr or "").strip()
        marker_pos = stdout.rfind(f"\n{marker}")
        if marker_pos < 0:
            detail = stderr or stdout[-400:]
            raise _CurlTransportError(f"invalid curl output: {detail}")

        body = stdout[:marker_pos]
        status_text = stdout[marker_pos + len(f"\n{marker}") :].strip().splitlines()[0]
        try:
            status_code = int(status_text)
        except Exception as e:
            raise _CurlTransportError(f"invalid HTTP status from curl: {status_text}") from e

        if proc.returncode != 0:
            detail = stderr or body[-400:]
            raise _CurlTransportError(detail or f"curl exit code: {proc.returncode}")
        if status_code != 200:
            raise _CurlHTTPError(status_code, body)

        try:
            return json.loads(body)
        except Exception as e:
            preview = body[:500]
            raise RuntimeError(f"Invalid JSON response: {e}; body={preview}") from e

    def _post_json_with_retry(self, *, endpoint, url, headers, payload_json, max_retries, retry_delay):
        timeout = self.config.get("timeoutMs", 60000) / 1000
        current_delay = float(retry_delay)
        for attempt in range(max_retries + 1):
            try:
                return self._curl_post_json_once(url=url, headers=headers, payload_json=payload_json, timeout_sec=timeout)
            except _CurlHTTPError as e:
                status_code = int(e.status_code or 0)
                response_body = str(e.response_body or "")
                if status_code == 400:
                    self._dump_http_400_request(
                        endpoint=endpoint,
                        url=url,
                        method="POST",
                        headers=headers,
                        payload_json=payload_json,
                        status_code=status_code,
                        response_body=response_body,
                    )
                error_str = format_doubao_http_error(status_code, response_body)
                retryable = self._http_status_retryable(status_code)
                if retryable and attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="post_json_retry")
                    time.sleep(current_delay + random.uniform(0, 0.5))
                    current_delay *= 2
                    continue
                raise RuntimeError(error_str)
            except _CurlTransportError as e:
                error_str = str(e)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="post_json_retry")
                    time.sleep(current_delay + random.uniform(0, 0.5))
                    current_delay *= 2
                    continue
                raise RuntimeError(f"Error after {max_retries} retries: {error_str}")
            except Exception as e:
                error_str = str(e)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="post_json_retry")
                    time.sleep(current_delay + random.uniform(0, 0.5))
                    current_delay *= 2
                    continue
                raise RuntimeError(f"Error after {max_retries} retries: {error_str}")
        raise RuntimeError("Error: Max retries exceeded")

    def _curl_get_bytes_with_retry(self, *, url, max_retries, retry_delay):
        timeout = self.config.get("timeoutMs", 60000) / 1000
        current_delay = float(retry_delay)
        for attempt in range(max_retries + 1):
            try:
                return self._curl_get_bytes_once(url=url, timeout_sec=timeout)
            except Exception as e:
                error_str = str(e)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="get_bytes_retry")
                    time.sleep(current_delay + random.uniform(0, 0.5))
                    current_delay *= 2
                    continue
                raise RuntimeError(f"Error after {max_retries} retries: {error_str}") from e
        raise RuntimeError("Error: Max retries exceeded")

    def _get_json_with_retry(self, *, endpoint, url, headers, max_retries, retry_delay):
        timeout = self.config.get("timeoutMs", 60000) / 1000
        current_delay = float(retry_delay)
        for attempt in range(max_retries + 1):
            try:
                return self._curl_get_json_once(url=url, headers=headers, timeout_sec=timeout)
            except _CurlHTTPError as e:
                status_code = int(e.status_code or 0)
                response_body = str(e.response_body or "")
                error_str = format_doubao_http_error(status_code, response_body)
                retryable = self._http_status_retryable(status_code)
                if retryable and attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="get_json_retry")
                    time.sleep(current_delay + random.uniform(0, 0.5))
                    current_delay *= 2
                    continue
                raise RuntimeError(f"{endpoint}: {error_str}")
            except _CurlTransportError as e:
                error_str = str(e)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="get_json_retry")
                    time.sleep(current_delay + random.uniform(0, 0.5))
                    current_delay *= 2
                    continue
                raise RuntimeError(f"{endpoint}: Error after {max_retries} retries: {error_str}")
            except Exception as e:
                error_str = str(e)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="get_json_retry")
                    time.sleep(current_delay + random.uniform(0, 0.5))
                    current_delay *= 2
                    continue
                raise RuntimeError(f"{endpoint}: Error after {max_retries} retries: {error_str}") from e
        raise RuntimeError("Error: Max retries exceeded")

    @staticmethod
    def _emit_stream_text(stream_handler: Callable[[object, object], None] | None, delta_text: object, full_text: object) -> None:
        if not callable(stream_handler):
            return
        try:
            stream_handler(delta_text, full_text)
        except Exception:
            return

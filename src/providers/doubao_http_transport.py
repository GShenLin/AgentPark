import json
import os
import random
import time
from datetime import datetime

from src.providers.curl_transport import CurlHttpTransport, CurlTransportError
from src.providers.doubao_agent_common import _CurlHTTPError, _CurlTransportError, format_doubao_http_error
from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.providers.provider_stream_emit import ProviderStreamEmitMixin
from src.runtime_cancellation import CancellationRequested
from src.runtime_cancellation import sleep_with_cancel
from src.service_host import HostBoundService


class DoubaoHttpTransport(ProviderStreamEmitMixin, CurlHttpTransport, ProviderRuntimeEventMixin, HostBoundService):
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
        try:
            response = self._curl_post_once_raw(
                url=url,
                headers=headers,
                payload_json=payload_json,
                timeout_sec=timeout_sec,
                marker="__DOUBAO_HTTP_CODE__:",
            )
        except CurlTransportError as e:
            raise _CurlTransportError(str(e)) from e
        if response.status_code != 200:
            raise _CurlHTTPError(response.status_code, response.body)

        try:
            return json.loads(response.body)
        except Exception as e:
            preview = response.body[:500]
            raise RuntimeError(f"Invalid JSON response: {e}; body={preview}") from e

    def _curl_get_bytes_once(self, *, url, timeout_sec):
        try:
            return self._curl_get_bytes_raw(url=url, timeout_sec=timeout_sec)
        except CurlTransportError as e:
            raise _CurlTransportError(str(e)) from e

    def _curl_get_json_once(self, *, url, headers, timeout_sec):
        try:
            response = self._curl_get_text_once_raw(
                url=url,
                headers=headers,
                timeout_sec=timeout_sec,
                marker="__DOUBAO_HTTP_CODE__:",
            )
        except CurlTransportError as e:
            raise _CurlTransportError(str(e)) from e
        if response.status_code != 200:
            raise _CurlHTTPError(response.status_code, response.body)

        try:
            return json.loads(response.body)
        except Exception as e:
            preview = response.body[:500]
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
                    sleep_with_cancel(current_delay + random.uniform(0, 0.5), self._cancel_source())
                    current_delay *= 2
                    continue
                raise RuntimeError(error_str)
            except _CurlTransportError as e:
                error_str = str(e)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="post_json_retry")
                    sleep_with_cancel(current_delay + random.uniform(0, 0.5), self._cancel_source())
                    current_delay *= 2
                    continue
                raise RuntimeError(f"Error after {max_retries} retries: {error_str}")
            except CancellationRequested:
                raise
            except Exception as e:
                error_str = str(e)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="post_json_retry")
                    sleep_with_cancel(current_delay + random.uniform(0, 0.5), self._cancel_source())
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
            except CancellationRequested:
                raise
            except Exception as e:
                error_str = str(e)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="get_bytes_retry")
                    sleep_with_cancel(current_delay + random.uniform(0, 0.5), self._cancel_source())
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
                    sleep_with_cancel(current_delay + random.uniform(0, 0.5), self._cancel_source())
                    current_delay *= 2
                    continue
                raise RuntimeError(f"{endpoint}: {error_str}")
            except _CurlTransportError as e:
                error_str = str(e)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="get_json_retry")
                    sleep_with_cancel(current_delay + random.uniform(0, 0.5), self._cancel_source())
                    current_delay *= 2
                    continue
                raise RuntimeError(f"{endpoint}: Error after {max_retries} retries: {error_str}")
            except CancellationRequested:
                raise
            except Exception as e:
                error_str = str(e)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="get_json_retry")
                    sleep_with_cancel(current_delay + random.uniform(0, 0.5), self._cancel_source())
                    current_delay *= 2
                    continue
                raise RuntimeError(f"{endpoint}: Error after {max_retries} retries: {error_str}") from e
        raise RuntimeError("Error: Max retries exceeded")

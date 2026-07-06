import json
import random
import time
from typing import Any, Callable

from src.providers.curl_transport import CurlHttpTransport, CurlResponse, CurlTransportError
from src.providers.provider_errors import ProviderHttpError, ProviderProtocolError, ProviderTransportError
from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.providers.provider_stream_emit import ProviderStreamEmitMixin
from src.runtime_cancellation import CancellationRequested
from src.runtime_cancellation import sleep_with_cancel
from src.service_host import HostBoundService


class ZhipuHttpError(ProviderHttpError):
    pass


class ZhipuTransportError(ProviderTransportError):
    pass


class ZhipuHttpTransport(ProviderStreamEmitMixin, CurlHttpTransport, ProviderRuntimeEventMixin, HostBoundService):
    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"

    def _chat_completions_url(self) -> str:
        base_url = str(self.config.get("baseUrl") or self.DEFAULT_BASE_URL).strip().rstrip("/")
        if not base_url:
            base_url = self.DEFAULT_BASE_URL
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _resolve_retry_policy(self):
        try:
            max_retries = int(self.config.get("maxRetries", self.config.get("max_retries", 3)))
        except Exception:
            max_retries = 3
        try:
            retry_delay = float(self.config.get("retryDelaySec", self.config.get("retry_delay_sec", 1)))
        except Exception:
            retry_delay = 1
        return max(0, max_retries), max(0, retry_delay)

    def _resolve_timeout_seconds(self):
        try:
            return max(1, float(self.config.get("timeoutMs", 60000)) / 1000)
        except Exception:
            return 60

    @staticmethod
    def _is_quota_error(error_text: object) -> bool:
        text = str(error_text or "").lower()
        return any(
            marker in text
            for marker in (
                "accountquotaexceeded",
                "insufficient_quota",
                "quota exceeded",
                "usage quota",
                "quotaexceeded",
            )
        )

    @classmethod
    def _http_status_retryable(cls, status_code: object, error_text: object = "") -> bool:
        if cls._is_quota_error(error_text):
            return False
        code = int(status_code or 0)
        return code == 429 or code >= 500

    @staticmethod
    def _format_http_error(status_code: int, response_body: str) -> str:
        text = str(response_body or "").strip()
        try:
            payload = json.loads(text)
        except Exception:
            payload = None
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            code = str(error.get("code") or error.get("type") or "").strip()
            message = str(error.get("message") or "").strip()
            if code and message:
                return f"HTTP Error {status_code}: {code}: {message}"
            if message:
                return f"HTTP Error {status_code}: {message}"
        return f"HTTP Error {status_code}: {text}"

    def _post_json_once(self, *, url: str, headers: dict, payload_json: str, timeout_sec: float) -> dict:
        try:
            response = self._curl_post_once_raw(
                url=url,
                headers=headers,
                payload_json=payload_json,
                timeout_sec=timeout_sec,
                marker="__ZHIPU_HTTP_CODE__:",
            )
        except CurlTransportError as exc:
            raise ZhipuTransportError(str(exc)) from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise ZhipuHttpError(response.status_code, response.body)
        try:
            return json.loads(response.body)
        except Exception as exc:
            raise ProviderProtocolError(f"Invalid JSON response: {exc}; body={response.body[:500]}") from exc

    def _post_json_with_retry(self, *, endpoint: str, url: str, headers: dict, payload_json: str) -> dict:
        max_retries, retry_delay = self._resolve_retry_policy()
        current_delay = retry_delay
        for attempt in range(max_retries + 1):
            try:
                return self._post_json_once(
                    url=url,
                    headers=headers,
                    payload_json=payload_json,
                    timeout_sec=self._resolve_timeout_seconds(),
                )
            except ZhipuHttpError as exc:
                error_str = self._format_http_error(exc.status_code, exc.response_body)
                if self._http_status_retryable(exc.status_code, error_str) and attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="zhipu_chat_completions_retry")
                    sleep_with_cancel(current_delay + random.uniform(0, 0.5), self._cancel_source())
                    current_delay *= 2
                    continue
                raise RuntimeError(error_str) from exc
            except ZhipuTransportError as exc:
                error_str = str(exc)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="zhipu_chat_completions_retry")
                    sleep_with_cancel(current_delay + random.uniform(0, 0.5), self._cancel_source())
                    current_delay *= 2
                    continue
                raise RuntimeError(f"{endpoint}: Error after {max_retries} retries: {error_str}") from exc
            except RuntimeError:
                raise
            except Exception as exc:
                error_str = str(exc)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="zhipu_chat_completions_retry")
                    sleep_with_cancel(current_delay + random.uniform(0, 0.5), self._cancel_source())
                    current_delay *= 2
                    continue
                raise RuntimeError(f"{endpoint}: Error after {max_retries} retries: {error_str}") from exc
        raise RuntimeError("Error: Max retries exceeded")

    def _curl_post_sse_data_lines(self, *, url: str, headers: dict, payload_json: str, timeout_sec: float):
        try:
            for item in self._curl_post_sse_raw_lines(
                url=url,
                headers=headers,
                payload_json=payload_json,
                timeout_sec=timeout_sec,
                marker="__ZHIPU_HTTP_CODE__:",
            ):
                if isinstance(item, CurlResponse):
                    if item.status_code < 200 or item.status_code >= 300:
                        raise ZhipuHttpError(item.status_code, item.body)
                    continue
                yield item
        except CurlTransportError as exc:
            raise ZhipuTransportError(str(exc)) from exc

    def _stream_chat_completions_with_retry(
        self,
        *,
        endpoint: str,
        url: str,
        headers: dict,
        payload_json: str,
        stream_handler: Callable[[object, object], None] | None,
    ) -> dict:
        max_retries, retry_delay = self._resolve_retry_policy()
        current_delay = retry_delay
        for attempt in range(max_retries + 1):
            try:
                return self._stream_chat_completions_once(
                    url=url,
                    headers=headers,
                    payload_json=payload_json,
                    stream_handler=stream_handler,
                )
            except ZhipuHttpError as exc:
                error_str = self._format_http_error(exc.status_code, exc.response_body)
                if self._http_status_retryable(exc.status_code, error_str) and attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="zhipu_chat_completions_retry")
                    sleep_with_cancel(current_delay + random.uniform(0, 0.5), self._cancel_source())
                    current_delay *= 2
                    continue
                raise RuntimeError(error_str) from exc
            except ZhipuTransportError as exc:
                error_str = str(exc)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="zhipu_chat_completions_retry")
                    sleep_with_cancel(current_delay + random.uniform(0, 0.5), self._cancel_source())
                    current_delay *= 2
                    continue
                raise RuntimeError(f"{endpoint}: Error after {max_retries} retries: {error_str}") from exc
            except RuntimeError:
                raise
            except Exception as exc:
                error_str = str(exc)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="zhipu_chat_completions_retry")
                    time.sleep(current_delay + random.uniform(0, 0.5))
                    current_delay *= 2
                    continue
                raise RuntimeError(f"{endpoint}: Error after {max_retries} retries: {error_str}") from exc
        raise RuntimeError("Error: Max retries exceeded")

    def _stream_chat_completions_once(
        self,
        *,
        url: str,
        headers: dict,
        payload_json: str,
        stream_handler: Callable[[object, object], None] | None,
    ) -> dict:
        content_chunks: list[str] = []
        tool_calls_by_index: dict[int, dict] = {}
        finish_reason = ""
        for data_text in self._curl_post_sse_data_lines(
            url=url,
            headers=headers,
            payload_json=payload_json,
            timeout_sec=self._resolve_timeout_seconds(),
        ):
            if not data_text or data_text == "[DONE]":
                continue
            event = self._parse_sse_json_event(data_text, stage="zhipu_chat_completions_stream_parse")
            if not isinstance(event, dict):
                continue
            for choice in event.get("choices") if isinstance(event.get("choices"), list) else []:
                if not isinstance(choice, dict):
                    continue
                finish_reason = str(choice.get("finish_reason") or finish_reason or "")
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    continue
                delta_text = delta.get("content")
                if isinstance(delta_text, str) and delta_text:
                    content_chunks.append(delta_text)
                    self._emit_stream_text(stream_handler, delta_text, "".join(content_chunks))
                self._merge_tool_call_deltas(tool_calls_by_index, delta.get("tool_calls"))
        message = {"role": "assistant", "content": "".join(content_chunks)}
        tool_calls = self._assembled_tool_calls(tool_calls_by_index)
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {"choices": [{"message": message, "finish_reason": finish_reason}]}

    @staticmethod
    def _merge_tool_call_deltas(tool_calls_by_index: dict[int, dict], tool_calls_delta: Any) -> None:
        if not isinstance(tool_calls_delta, list):
            return
        for tool_item in tool_calls_delta:
            if not isinstance(tool_item, dict):
                continue
            try:
                index = int(tool_item.get("index")) if tool_item.get("index") is not None else len(tool_calls_by_index)
            except Exception:
                index = len(tool_calls_by_index)
            bucket = tool_calls_by_index.get(index)
            if not isinstance(bucket, dict):
                bucket = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                tool_calls_by_index[index] = bucket
            if tool_item.get("id"):
                bucket["id"] = str(tool_item.get("id") or "")
            if tool_item.get("type"):
                bucket["type"] = str(tool_item.get("type") or "")
            fn = tool_item.get("function")
            if not isinstance(fn, dict):
                continue
            bucket_fn = bucket.get("function")
            if not isinstance(bucket_fn, dict):
                bucket_fn = {"name": "", "arguments": ""}
                bucket["function"] = bucket_fn
            if fn.get("name"):
                bucket_fn["name"] = str(bucket_fn.get("name") or "") + str(fn.get("name") or "")
            if fn.get("arguments") is not None:
                bucket_fn["arguments"] = str(bucket_fn.get("arguments") or "") + str(fn.get("arguments") or "")

    @staticmethod
    def _assembled_tool_calls(tool_calls_by_index: dict[int, dict]) -> list[dict]:
        output: list[dict] = []
        for index in sorted(tool_calls_by_index.keys()):
            item = tool_calls_by_index.get(index)
            if not isinstance(item, dict):
                continue
            fn = item.get("function")
            if not isinstance(fn, dict) or not str(fn.get("name") or "").strip():
                continue
            output.append(
                {
                    "id": str(item.get("id") or ""),
                    "type": str(item.get("type") or "function"),
                    "function": {
                        "name": str(fn.get("name") or "").strip(),
                        "arguments": str(fn.get("arguments") or ""),
                    },
                }
            )
        return output


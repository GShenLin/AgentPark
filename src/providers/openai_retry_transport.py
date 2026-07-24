from __future__ import annotations

from src.providers.openai_retry_policy import OpenAIRetryPolicy
from src.providers.openai_retry_policy import OpenAIRetryState
from src.providers.openai_retry_policy import is_retryable_provider_code
from src.providers.openai_transport_errors import OpenAIHttpError
from src.providers.openai_transport_errors import OpenAIResponseIncompleteError
from src.providers.openai_transport_errors import OpenAITransportError
from src.runtime_cancellation import sleep_with_cancel


class OpenAIRetryTransportMixin:
    def _resolve_retry_policy(self) -> OpenAIRetryPolicy:
        return OpenAIRetryPolicy.from_config(self.config)

    def _post_json_with_retry(self, *, endpoint, url, headers, payload_json):
        timeout = self.config.get("timeoutMs", 60000) / 1000
        retry_policy = self._resolve_retry_policy()
        retry_state = OpenAIRetryState(retry_policy)
        auth_refreshed = False
        while True:
            try:
                return self._curl_post_json_once(
                    url=url,
                    headers=headers,
                    payload_json=payload_json,
                    timeout_sec=timeout,
                )
            except OpenAIHttpError as exc:
                status_code = int(exc.status_code or 0)
                error_str = f"{endpoint}: HTTP {status_code} - {exc.response_body}"
                if status_code == 401 and not auth_refreshed:
                    refresh_auth = getattr(self, "_refresh_responses_auth_headers", None)
                    if callable(refresh_auth) and refresh_auth(headers):
                        auth_refreshed = True
                        continue
                provider_code = exc.provider_code
                decision = (
                    retry_state.next_retry(provider_code=provider_code)
                    if (
                        is_retryable_provider_code(provider_code)
                        or self._http_error_retryable(status_code, error_str)
                    )
                    else None
                )
                if decision is not None:
                    retry_delay = retry_policy.delay_seconds(
                        attempt=decision.attempt,
                        error_text=error_str,
                    )
                    self._emit_retry_notice(
                        error=error_str,
                        delay=retry_delay,
                        stage="openai_post_json_retry",
                        attempt=decision.attempt,
                        max_retries=decision.max_retries,
                    )
                    sleep_with_cancel(retry_delay, self._cancel_source())
                    continue
                raise RuntimeError(error_str) from exc
            except OpenAITransportError as exc:
                error_str = str(exc)
                decision = retry_state.next_retry()
                if decision is not None:
                    retry_delay = retry_policy.delay_seconds(
                        attempt=decision.attempt,
                        error_text=error_str,
                    )
                    self._emit_retry_notice(
                        error=error_str,
                        delay=retry_delay,
                        stage="openai_post_json_retry",
                        attempt=decision.attempt,
                        max_retries=decision.max_retries,
                    )
                    sleep_with_cancel(retry_delay, self._cancel_source())
                    continue
                raise RuntimeError(
                    f"{endpoint}: Error after retry budget was exhausted: {error_str}"
                ) from exc

    def _stream_responses_with_retry(
        self,
        *,
        endpoint,
        url,
        headers,
        payload_json,
        stream_handler,
        thinking_stream_handler=None,
        item_event_handler=None,
    ):
        timeout = self.config.get("timeoutMs", 60000) / 1000
        retry_policy = self._resolve_retry_policy()
        retry_state = OpenAIRetryState(retry_policy)
        auth_refreshed = False
        while True:
            try:
                return self._stream_responses_once(
                    url=url,
                    headers=headers,
                    payload_json=payload_json,
                    timeout_sec=timeout,
                    stream_handler=stream_handler,
                    thinking_stream_handler=thinking_stream_handler,
                    item_event_handler=item_event_handler,
                )
            except (OpenAIHttpError, OpenAITransportError) as exc:
                status_code = int(getattr(exc, "status_code", 0) or 0)
                error_str = str(exc)
                if isinstance(exc, OpenAIResponseIncompleteError):
                    raise RuntimeError(f"{endpoint}: {error_str}") from exc
                if status_code == 401 and not auth_refreshed:
                    refresh_auth = getattr(self, "_refresh_responses_auth_headers", None)
                    if callable(refresh_auth) and refresh_auth(headers):
                        auth_refreshed = True
                        continue
                retryable = isinstance(exc, OpenAITransportError) or self._http_error_retryable(
                    status_code,
                    error_str,
                )
                provider_code = (
                    exc.provider_code
                    if isinstance(exc, OpenAIHttpError)
                    else ""
                )
                retryable = retryable or is_retryable_provider_code(provider_code)
                decision = (
                    retry_state.next_retry(provider_code=provider_code)
                    if retryable
                    else None
                )
                if decision is not None:
                    retry_delay = retry_policy.delay_seconds(
                        attempt=decision.attempt,
                        error_text=error_str,
                    )
                    self._emit_retry_notice(
                        error=error_str,
                        delay=retry_delay,
                        stage="openai_responses_retry",
                        attempt=decision.attempt,
                        max_retries=decision.max_retries,
                    )
                    sleep_with_cancel(retry_delay, self._cancel_source())
                    continue
                raise RuntimeError(f"{endpoint}: {error_str}") from exc

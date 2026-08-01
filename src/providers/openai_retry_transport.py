from __future__ import annotations

from src.providers.openai_retry_policy import OpenAIRetryPolicy
from src.providers.openai_retry_policy import OpenAIRetryState
from src.providers.openai_retry_policy import OpenAITransportTimeouts
from src.providers.openai_retry_policy import is_fatal_responses_failure_code
from src.providers.openai_retry_policy import is_retryable_provider_code
from src.providers.openai_transport_errors import OpenAIHttpError
from src.providers.openai_transport_errors import OpenAITransportError
from src.runtime_cancellation import sleep_with_cancel


class OpenAIRetryTransportMixin:
    def _resolve_retry_policy(self) -> OpenAIRetryPolicy:
        return OpenAIRetryPolicy.from_config(self.config)

    def _resolve_transport_timeouts(self) -> OpenAITransportTimeouts:
        return OpenAITransportTimeouts.from_config(self.config)

    def _recover_responses_unauthorized(
        self,
        headers: dict[str, str],
        *,
        recovery_stage: int,
    ) -> int | None:
        if recovery_stage < 1:
            reload_auth = getattr(self, "_reload_responses_auth_headers", None)
            if callable(reload_auth) and reload_auth(headers):
                return 1
        if recovery_stage < 2:
            refresh_auth = getattr(self, "_refresh_responses_auth_headers", None)
            if callable(refresh_auth) and refresh_auth(headers):
                return 2
        return None

    def _post_json_with_retry(self, *, endpoint, url, headers, payload_json):
        timeout = self._resolve_transport_timeouts().request_seconds
        retry_policy = self._resolve_retry_policy()
        retry_state = OpenAIRetryState(retry_policy, scope="request")
        auth_recovery_stage = 0
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
                if status_code == 401:
                    next_auth_stage = self._recover_responses_unauthorized(
                        headers,
                        recovery_stage=auth_recovery_stage,
                    )
                    if next_auth_stage is not None:
                        auth_recovery_stage = next_auth_stage
                        retry_state = OpenAIRetryState(
                            retry_policy,
                            scope="request",
                        )
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
        timeout = self._resolve_transport_timeouts().stream_idle_seconds
        retry_policy = self._resolve_retry_policy()
        request_retry_state = OpenAIRetryState(
            retry_policy,
            scope="request",
        )
        stream_retry_state = OpenAIRetryState(
            retry_policy,
            scope="stream",
        )
        auth_recovery_stage = 0
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
                if status_code == 401:
                    next_auth_stage = self._recover_responses_unauthorized(
                        headers,
                        recovery_stage=auth_recovery_stage,
                    )
                    if next_auth_stage is not None:
                        auth_recovery_stage = next_auth_stage
                        self._reset_responses_websocket_for_retry()
                        request_retry_state = OpenAIRetryState(
                            retry_policy,
                            scope="request",
                        )
                        continue
                if status_code in {404, 405, 426} and self._fallback_responses_websocket_to_http(
                    reason=error_str,
                ):
                    request_retry_state = OpenAIRetryState(
                        retry_policy,
                        scope="request",
                    )
                    stream_retry_state = OpenAIRetryState(
                        retry_policy,
                        scope="stream",
                    )
                    continue
                provider_code = (
                    exc.provider_code
                    if isinstance(exc, OpenAIHttpError)
                    else ""
                )
                structured_failure = (
                    isinstance(exc, OpenAIHttpError)
                    and exc.response_event_type == "response.failed"
                )
                fatal_structured_failure = structured_failure and (
                    is_fatal_responses_failure_code(provider_code)
                    or self._quota_error_non_retryable(error_str)
                )
                if fatal_structured_failure:
                    retryable = False
                elif structured_failure:
                    retryable = True
                else:
                    retryable = (
                        isinstance(exc, OpenAITransportError)
                        or self._http_error_retryable(status_code, error_str)
                        or is_retryable_provider_code(provider_code)
                    )
                decision = None
                retry_stage = "openai_responses_retry"
                if retryable:
                    retry_scope = str(
                        getattr(exc, "retry_scope", "stream") or "stream"
                    )
                    if retry_scope == "request":
                        decision = request_retry_state.next_retry(
                            provider_code=provider_code
                        )
                        retry_stage = "openai_responses_request_retry"
                        if decision is None:
                            decision = stream_retry_state.next_retry(
                                provider_code=provider_code
                            )
                            retry_stage = "openai_responses_retry"
                            if decision is not None:
                                request_retry_state = OpenAIRetryState(
                                    retry_policy,
                                    scope="request",
                                )
                    else:
                        decision = stream_retry_state.next_retry(
                            provider_code=provider_code
                        )
                        if decision is not None:
                            request_retry_state = OpenAIRetryState(
                                retry_policy,
                                scope="request",
                            )
                if decision is not None:
                    self._reset_responses_websocket_for_retry()
                    retry_delay = retry_policy.delay_seconds(
                        attempt=decision.attempt,
                        error_text=error_str,
                    )
                    self._emit_retry_notice(
                        error=error_str,
                        delay=retry_delay,
                        stage=retry_stage,
                        attempt=decision.attempt,
                        max_retries=decision.max_retries,
                    )
                    sleep_with_cancel(retry_delay, self._cancel_source())
                    continue
                if retryable and self._fallback_responses_websocket_to_http(
                    reason=error_str,
                ):
                    request_retry_state = OpenAIRetryState(
                        retry_policy,
                        scope="request",
                    )
                    stream_retry_state = OpenAIRetryState(
                        retry_policy,
                        scope="stream",
                    )
                    continue
                raise RuntimeError(f"{endpoint}: {error_str}") from exc

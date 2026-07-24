from __future__ import annotations

import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from src.config_loader import ConfigLoader
from src.providers.provider_token_window import ProviderRollingTokenWindow
from src.runtime_cancellation import raise_if_cancel_requested


RPM_INTERVAL_BASE_SEC = 60.0
TPM_WINDOW_SEC = 60.0


@dataclass(frozen=True)
class ProviderPressureLimits:
    concurrency_limit: int | None = None
    rpm_limit: int | None = None
    tpm_limit: int | None = None


class _ProviderPressureState:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.waiters: deque[object] = deque()
        self.in_flight = 0
        self.queued = 0
        self.peak_in_flight = 0
        self.peak_queued = 0
        self.peak_rpm_used = 0
        self.peak_tpm_used = 0
        self.peak_input_tpm_used = 0
        self.peak_output_tpm_used = 0
        self.last_started_at: float | None = None
        self.last_interval_sec: float | None = None
        self.token_window = ProviderRollingTokenWindow()
        self.last_limits = ProviderPressureLimits()


class ProviderPressureManager:
    def __init__(self) -> None:
        self._states: dict[str, _ProviderPressureState] = {}
        self._states_lock = threading.Lock()
        self._config_lock = threading.Lock()
        self._config_cache_path = ""
        self._config_cache_mtime_ns = -1
        self._config_cache: dict[str, dict[str, Any]] = {}

    def _state_for(self, provider_id: str) -> _ProviderPressureState:
        safe_provider_id = str(provider_id or "").strip() or "<unknown>"
        with self._states_lock:
            state = self._states.get(safe_provider_id)
            if state is None:
                state = _ProviderPressureState()
                self._states[safe_provider_id] = state
            return state

    @contextmanager
    def acquire(self, provider_id: str, *, cancel_source: Any = None) -> Iterator[None]:
        safe_provider_id = str(provider_id or "").strip() or "<unknown>"
        limits = self._load_limits(safe_provider_id)
        state = self._state_for(safe_provider_id)

        if (
            limits.concurrency_limit is None
            and limits.rpm_limit is None
            and limits.tpm_limit is None
        ):
            with state.condition:
                state.last_limits = limits
                now = time.monotonic()
                self._record_request_start_locked(state, now)
                state.in_flight += 1
                self._record_peaks_locked(state)
                state.condition.notify_all()
            try:
                yield
            finally:
                with state.condition:
                    state.in_flight = max(0, state.in_flight - 1)
                    state.condition.notify_all()
            return

        waiter = object()
        acquired = False
        with state.condition:
            state.last_limits = limits
            state.waiters.append(waiter)
            state.queued += 1
            self._record_peaks_locked(state)
            state.condition.notify_all()
            try:
                while True:
                    raise_if_cancel_requested(cancel_source)
                    now = time.monotonic()
                    at_head = bool(state.waiters) and state.waiters[0] is waiter
                    concurrency_ok = (
                        limits.concurrency_limit is None
                        or state.in_flight < limits.concurrency_limit
                    )
                    rpm_ok = self._rpm_spacing_ok_locked(state, limits, now)
                    tpm_ok = self._tpm_next_available_in_sec_locked(
                        state,
                        limits,
                        now,
                    ) <= 0
                    if at_head and concurrency_ok and rpm_ok and tpm_ok:
                        state.waiters.popleft()
                        state.queued = max(0, state.queued - 1)
                        self._record_request_start_locked(state, now)
                        state.in_flight += 1
                        self._record_peaks_locked(state)
                        acquired = True
                        state.condition.notify_all()
                        break

                    state.condition.wait(
                        timeout=self._wait_timeout_locked(
                            state,
                            limits,
                            now,
                        )
                    )
            except BaseException:
                if not acquired:
                    try:
                        state.waiters.remove(waiter)
                    except ValueError:
                        pass
                    state.queued = max(0, state.queued - 1)
                    state.condition.notify_all()
                raise

        try:
            yield
        finally:
            with state.condition:
                state.in_flight = max(0, state.in_flight - 1)
                state.condition.notify_all()

    def record_tokens(self, provider_id: str, *, input_tokens: int, output_tokens: int) -> None:
        normalized_input_tokens = _non_negative_int_or_none(input_tokens)
        normalized_output_tokens = _non_negative_int_or_none(output_tokens)
        if normalized_input_tokens is None and normalized_output_tokens is None:
            return
        safe_provider_id = str(provider_id or "").strip() or "<unknown>"
        limits = self._load_limits(safe_provider_id)
        if limits.tpm_limit is None:
            return
        state = self._state_for(safe_provider_id)
        with state.condition:
            state.last_limits = limits
            usage = state.token_window.record(
                completed_at=time.monotonic(),
                input_tokens=normalized_input_tokens or 0,
                output_tokens=normalized_output_tokens or 0,
                window_seconds=TPM_WINDOW_SEC,
            )
            state.peak_tpm_used = max(state.peak_tpm_used, usage.total_tokens)
            state.peak_input_tpm_used = max(state.peak_input_tpm_used, usage.input_tokens)
            state.peak_output_tpm_used = max(state.peak_output_tpm_used, usage.output_tokens)
            state.condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        providers = self._configured_providers()
        provider_ids = set(providers)
        with self._states_lock:
            provider_ids.update(self._states)
            states = dict(self._states)

        rows: list[dict[str, Any]] = []
        now = time.monotonic()
        for provider_id in sorted(provider_ids):
            config = providers.get(provider_id) if isinstance(providers.get(provider_id), dict) else {}
            limits = self._limits_from_config(config)
            state = states.get(provider_id)
            if state is None:
                rows.append(self._empty_snapshot_row(provider_id, config, limits))
                continue
            with state.condition:
                state.last_limits = limits
                rpm_next_available_in_sec = self._rpm_next_available_in_sec_locked(state, limits, now)
                tpm_usage = state.token_window.usage(now=now, window_seconds=TPM_WINDOW_SEC)
                tpm_next_available_in_sec = self._tpm_next_available_in_sec_locked(
                    state,
                    limits,
                    now,
                )
                self._record_peaks_locked(state)
                rows.append(
                    {
                        "provider_id": provider_id,
                        "type": str(config.get("type") or ""),
                        "model": str(config.get("model") or ""),
                        "concurrency_limit": limits.concurrency_limit,
                        "rpm_limit": limits.rpm_limit,
                        "tpm_limit": limits.tpm_limit,
                        "in_flight": state.in_flight,
                        "queued": state.queued,
                        "rpm_used": 1 if rpm_next_available_in_sec > 0 else 0,
                        "rpm_interval_sec": self._rpm_interval_sec(limits),
                        "rpm_next_available_in_sec": rpm_next_available_in_sec,
                        "tpm_used": tpm_usage.total_tokens,
                        "tpm_remaining": None
                        if limits.tpm_limit is None
                        else max(0, limits.tpm_limit - tpm_usage.total_tokens),
                        "input_tpm_used": tpm_usage.input_tokens,
                        "output_tpm_used": tpm_usage.output_tokens,
                        "tpm_next_available_in_sec": tpm_next_available_in_sec,
                        "peak_in_flight": state.peak_in_flight,
                        "peak_queued": state.peak_queued,
                        "peak_rpm_used": state.peak_rpm_used,
                        "peak_tpm_used": state.peak_tpm_used,
                        "peak_input_tpm_used": state.peak_input_tpm_used,
                        "peak_output_tpm_used": state.peak_output_tpm_used,
                        "rpm_remaining": None
                        if limits.rpm_limit is None
                        else (0 if rpm_next_available_in_sec > 0 else 1),
                    }
                )
        return {
            "providers": rows,
            "interval_base_seconds": int(RPM_INTERVAL_BASE_SEC),
            "window_seconds": int(TPM_WINDOW_SEC),
        }

    def reset_for_tests(self) -> None:
        with self._states_lock:
            self._states.clear()
        with self._config_lock:
            self._config_cache_path = ""
            self._config_cache_mtime_ns = -1
            self._config_cache = {}

    def _load_limits(self, provider_id: str) -> ProviderPressureLimits:
        config = self._configured_providers().get(provider_id)
        return self._limits_from_config(config if isinstance(config, dict) else {})

    def _configured_providers(self) -> dict[str, dict[str, Any]]:
        try:
            loader = ConfigLoader()
            path = loader._resolve_provider_config_path()
            mtime_ns = os.stat(path).st_mtime_ns
        except Exception:
            return {}
        with self._config_lock:
            if (
                path == self._config_cache_path
                and mtime_ns == self._config_cache_mtime_ns
            ):
                return self._config_cache
        try:
            providers = loader.get_all_providers()
        except Exception:
            return {}
        if not isinstance(providers, dict):
            return {}
        normalized = {
            str(provider_id): config
            for provider_id, config in providers.items()
            if isinstance(config, dict)
        }
        with self._config_lock:
            self._config_cache_path = path
            self._config_cache_mtime_ns = mtime_ns
            self._config_cache = normalized
        return normalized

    @staticmethod
    def _limits_from_config(config: dict[str, Any]) -> ProviderPressureLimits:
        return ProviderPressureLimits(
            concurrency_limit=_positive_int_or_none(config.get("concurrencyLimit")),
            rpm_limit=_positive_int_or_none(config.get("rpmLimit")),
            tpm_limit=_positive_int_or_none(config.get("tpmLimit")),
        )

    @staticmethod
    def _record_request_start_locked(state: _ProviderPressureState, now: float) -> None:
        if state.last_started_at is not None:
            state.last_interval_sec = max(0.0, now - state.last_started_at)
            if state.last_interval_sec > 0:
                state.peak_rpm_used = max(
                    state.peak_rpm_used,
                    int(round(RPM_INTERVAL_BASE_SEC / state.last_interval_sec)),
                )
        state.last_started_at = now

    @staticmethod
    def _rpm_interval_sec(limits: ProviderPressureLimits) -> float | None:
        if limits.rpm_limit is None:
            return None
        return RPM_INTERVAL_BASE_SEC / float(limits.rpm_limit)

    @classmethod
    def _rpm_next_available_in_sec_locked(
        cls,
        state: _ProviderPressureState,
        limits: ProviderPressureLimits,
        now: float,
    ) -> float:
        interval_sec = cls._rpm_interval_sec(limits)
        if interval_sec is None or state.last_started_at is None:
            return 0.0
        return max(0.0, state.last_started_at + interval_sec - now)

    @classmethod
    def _rpm_spacing_ok_locked(
        cls,
        state: _ProviderPressureState,
        limits: ProviderPressureLimits,
        now: float,
    ) -> bool:
        return cls._rpm_next_available_in_sec_locked(state, limits, now) <= 0

    @staticmethod
    def _tpm_next_available_in_sec_locked(
        state: _ProviderPressureState,
        limits: ProviderPressureLimits,
        now: float,
    ) -> float:
        return state.token_window.next_available_in_seconds(
            now=now,
            window_seconds=TPM_WINDOW_SEC,
            limit=limits.tpm_limit,
        )

    @staticmethod
    def _wait_timeout_locked(
        state: _ProviderPressureState,
        limits: ProviderPressureLimits,
        monotonic_now: float,
    ) -> float:
        timeout = 0.25
        next_available = ProviderPressureManager._rpm_next_available_in_sec_locked(
            state,
            limits,
            monotonic_now,
        )
        if next_available > 0:
            timeout = min(timeout, max(0.01, next_available))
        tpm_next_available = ProviderPressureManager._tpm_next_available_in_sec_locked(
            state,
            limits,
            monotonic_now,
        )
        if tpm_next_available > 0:
            timeout = min(timeout, max(0.01, tpm_next_available))
        return timeout

    @staticmethod
    def _empty_snapshot_row(
        provider_id: str,
        config: dict[str, Any],
        limits: ProviderPressureLimits,
    ) -> dict[str, Any]:
        return {
            "provider_id": provider_id,
            "type": str(config.get("type") or ""),
            "model": str(config.get("model") or ""),
            "concurrency_limit": limits.concurrency_limit,
            "rpm_limit": limits.rpm_limit,
            "tpm_limit": limits.tpm_limit,
            "in_flight": 0,
            "queued": 0,
            "rpm_used": 0,
            "rpm_interval_sec": ProviderPressureManager._rpm_interval_sec(limits),
            "rpm_next_available_in_sec": 0.0,
            "tpm_used": 0,
            "tpm_remaining": limits.tpm_limit,
            "input_tpm_used": 0,
            "output_tpm_used": 0,
            "tpm_next_available_in_sec": 0.0,
            "peak_in_flight": 0,
            "peak_queued": 0,
            "peak_rpm_used": 0,
            "peak_tpm_used": 0,
            "peak_input_tpm_used": 0,
            "peak_output_tpm_used": 0,
            "rpm_remaining": None if limits.rpm_limit is None else limits.rpm_limit,
        }

    @staticmethod
    def _record_peaks_locked(state: _ProviderPressureState) -> None:
        state.peak_in_flight = max(state.peak_in_flight, state.in_flight)
        state.peak_queued = max(state.peak_queued, state.queued)


def _positive_int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _non_negative_int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed >= 0 else None


_MANAGER = ProviderPressureManager()


def get_provider_pressure_manager() -> ProviderPressureManager:
    return _MANAGER


def provider_id_for(owner: object) -> str:
    for attr in ("provider_name", "provider_id"):
        try:
            value = getattr(owner, attr)
        except Exception:
            value = ""
        text = str(value or "").strip()
        if text:
            return text
    return "<unknown>"


@contextmanager
def acquire_provider_pressure(owner: object, *, cancel_source: Any = None) -> Iterator[None]:
    with _MANAGER.acquire(provider_id_for(owner), cancel_source=cancel_source):
        yield


def record_provider_token_usage(owner: object, *, input_tokens: int, output_tokens: int) -> None:
    _MANAGER.record_tokens(
        provider_id_for(owner),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

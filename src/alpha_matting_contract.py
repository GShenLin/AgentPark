from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

ALPHA_MATTING_PROVIDER_TYPE = "alpha_matting"
ALPHA_MATTING_SUPPORT_MODE = "image_matting"


@dataclass(frozen=True)
class LocalRuntimeConfig:
    managed: bool
    startup_command: tuple[str, ...]
    working_directory: str
    health_url: str
    startup_timeout_ms: int


@dataclass(frozen=True)
class AlphaMattingConfig:
    base_url: str
    model: str
    model_revision: str
    timeout_ms: int
    local_runtime: LocalRuntimeConfig

    @property
    def health_url(self) -> str:
        return self.local_runtime.health_url

    @property
    def matting_url(self) -> str:
        return f"{self.base_url}/v1/matting"


def validate_alpha_matting_provider_config(
    provider_name: str,
    provider: dict,
) -> AlphaMattingConfig:
    label = f"Provider '{provider_name}'"
    if str(provider.get("type") or "").strip() != ALPHA_MATTING_PROVIDER_TYPE:
        raise ValueError(f"{label} must use type '{ALPHA_MATTING_PROVIDER_TYPE}'.")
    if str(provider.get("authMode") or "").strip().lower() != "none":
        raise ValueError(f"{label} must use authMode 'none'.")
    if provider.get("supportmode") != [ALPHA_MATTING_SUPPORT_MODE]:
        raise ValueError(
            f"{label} must declare exactly supportmode ['{ALPHA_MATTING_SUPPORT_MODE}']."
        )

    model = _required_string(label, "model", provider.get("model"))
    model_revision = _required_string(label, "modelRevision", provider.get("modelRevision"))
    base_url = _validate_loopback_url(label, "baseUrl", provider.get("baseUrl"), allow_path=False)
    timeout_ms = _positive_int(label, "timeoutMs", provider.get("timeoutMs", 120_000))

    raw_runtime = provider.get("localRuntime")
    if not isinstance(raw_runtime, dict):
        raise ValueError(f"{label} localRuntime must be an object.")
    managed = raw_runtime.get("managed")
    if not isinstance(managed, bool):
        raise ValueError(f"{label} localRuntime.managed must be a boolean.")

    raw_command = raw_runtime.get("startupCommand")
    if managed:
        if not isinstance(raw_command, list) or not raw_command:
            raise ValueError(
                f"{label} localRuntime.startupCommand must be a non-empty argument array."
            )
        startup_command = tuple(
            _required_string(label, f"localRuntime.startupCommand[{index}]", value)
            for index, value in enumerate(raw_command)
        )
    else:
        if raw_command not in (None, []):
            raise ValueError(
                f"{label} localRuntime.startupCommand is allowed only when managed is true."
            )
        startup_command = ()

    working_directory = str(raw_runtime.get("workingDirectory") or "").strip()
    if working_directory:
        if not os.path.isabs(working_directory):
            raise ValueError(
                f"{label} localRuntime.workingDirectory must be an absolute path."
            )
        working_directory = os.path.normpath(working_directory)
    if managed and not working_directory:
        raise ValueError(
            f"{label} localRuntime.workingDirectory is required when managed is true."
        )

    expected_health_url = f"{base_url}/health"
    health_url = _validate_loopback_url(
        label,
        "localRuntime.healthUrl",
        raw_runtime.get("healthUrl"),
        allow_path=True,
    )
    if health_url != expected_health_url:
        raise ValueError(
            f"{label} localRuntime.healthUrl must be exactly '{expected_health_url}'."
        )
    startup_timeout_ms = _positive_int(
        label,
        "localRuntime.startupTimeoutMs",
        raw_runtime.get("startupTimeoutMs", 120_000),
    )

    return AlphaMattingConfig(
        base_url=base_url,
        model=model,
        model_revision=model_revision,
        timeout_ms=timeout_ms,
        local_runtime=LocalRuntimeConfig(
            managed=managed,
            startup_command=startup_command,
            working_directory=working_directory,
            health_url=health_url,
            startup_timeout_ms=startup_timeout_ms,
        ),
    )


def _required_string(label: str, field_name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} {field_name} must be a non-empty string.")
    if value != value.strip():
        raise ValueError(f"{label} {field_name} must not contain surrounding whitespace.")
    return value


def _positive_int(label: str, field_name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} {field_name} must be a positive integer.")
    return value


def _validate_loopback_url(
    label: str,
    field_name: str,
    value: object,
    *,
    allow_path: bool,
) -> str:
    raw = _required_string(label, field_name, value)
    parsed = urlsplit(raw)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(
            f"{label} {field_name} must be an unauthenticated HTTP loopback URL."
        )
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} {field_name} contains an invalid port.") from exc
    if parsed.query or parsed.fragment:
        raise ValueError(f"{label} {field_name} must not contain a query or fragment.")
    try:
        is_loopback = parsed.hostname.lower() == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise ValueError(f"{label} {field_name} must use a loopback host.")
    path = parsed.path.rstrip("/")
    if not allow_path and path:
        raise ValueError(f"{label} {field_name} must not contain a path.")
    normalized_path = path if allow_path else ""
    return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, "", "")).rstrip("/")

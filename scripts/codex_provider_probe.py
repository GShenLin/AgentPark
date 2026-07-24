from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from dataclasses import asdict
from dataclasses import dataclass
from typing import Any

from src.codex_runtime.provider_adapter import provider_protocol
from src.codex_runtime.provider_gateway import CodexProviderGateway
from src.codex_runtime.session_manager import CodexSessionManager
from src.codex_runtime.session_manager import CodexSessionSpec
from src.config_loader import ConfigLoader


_HTTP_STATUS_RE = re.compile(
    r"(?:Upstream HTTP|HTTP|last status:|httpStatusCode['\"]?\s*[:=])\s*(\d{3})\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s)\]>\"']+", re.IGNORECASE)
_AUTH_RE = re.compile(r"(?i)\b(authorization|api[-_ ]?key)\b\s*[:=]\s*([^\s,;]+)")
_TOKEN_RE = re.compile(r"(?i)(?<![a-z0-9])(?:sk|ak)-[a-z0-9_-]{8,}")


@dataclass(frozen=True)
class ProbeResult:
    provider_id: str
    provider_type: str
    protocol: str
    model: str
    status: str
    elapsed_seconds: float
    http_status: int | None = None
    response: str = ""
    error: str = ""


def _chat_provider_ids(loader: ConfigLoader) -> list[str]:
    return [
        provider_id
        for provider_id, config in loader.get_all_providers().items()
        if "chat" in (config.get("supportmode") or [])
    ]


def _selected_provider_ids(loader: ConfigLoader, requested: list[str]) -> list[str]:
    available = _chat_provider_ids(loader)
    if not requested:
        return available
    unknown = [provider_id for provider_id in requested if provider_id not in available]
    if unknown:
        raise ValueError(f"Provider is missing or does not declare chat support: {', '.join(unknown)}")
    return requested


def _classify_error(error: Exception) -> tuple[str, int | None, str]:
    message = str(error)
    status_match = _HTTP_STATUS_RE.search(message)
    http_status = int(status_match.group(1)) if status_match else None
    lowered = message.casefold()
    if http_status is not None:
        status = "upstream_http_error"
    elif "protocol" in type(error).__name__.casefold() or "conversion" in lowered:
        status = "protocol_error"
    elif "curl" in lowered or "transport" in lowered or "ssl" in lowered:
        status = "transport_error"
    elif "timed out" in lowered or "timeout" in lowered:
        status = "timeout"
    else:
        status = "codex_error"
    return status, http_status, _bounded_error(message)


def _bounded_error(message: str, limit: int = 4000) -> str:
    text = _redact_sensitive(str(message or "").strip())
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _redact_sensitive(text: str) -> str:
    without_auth = _AUTH_RE.sub(lambda match: f"{match.group(1)}=<redacted>", str(text or ""))
    without_tokens = _TOKEN_RE.sub("<redacted-token>", without_auth)
    return _URL_RE.sub("<url>", without_tokens)


def _response_preview(response: object, limit: int = 500) -> str:
    text = _redact_sensitive(str(response or "").strip())
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _probe_one(
    *,
    loader: ConfigLoader,
    gateway: CodexProviderGateway,
    provider_id: str,
    codex_command: str,
    working_path: str,
    reasoning_effort: str,
) -> ProbeResult:
    config = loader.get_provider_config(provider_id)
    provider_type = str(config.get("type") or "")
    protocol = provider_protocol(config)
    model = str(config.get("model") or "")
    started = time.monotonic()
    manager = CodexSessionManager(gateway=gateway)
    event_counts: dict[str, int] = {}
    warnings: list[str] = []

    def count_event(event: dict[str, Any]) -> None:
        method = str(event.get("method") or "<unknown>")
        params = event.get("params")
        item = params.get("item") if isinstance(params, dict) else None
        item_type = str(item.get("type") or "") if isinstance(item, dict) else ""
        key = f"{method}:{item_type}" if item_type else method
        event_counts[key] = event_counts.get(key, 0) + 1
        if method == "warning" and isinstance(params, dict):
            message = _bounded_error(str(params.get("message") or ""))
            if message:
                warnings.append(message)

    try:
        with tempfile.TemporaryDirectory(prefix="agentpark-codex-probe-") as state_dir:
            response = manager.run_turn(
                CodexSessionSpec(
                    session_key=f"probe:{provider_id}",
                    provider_id=provider_id,
                    model=model,
                    command=codex_command,
                    cwd=working_path,
                    sandbox="read-only",
                    state_path=os.path.join(state_dir, "codex_thread.json"),
                    reasoning_effort=reasoning_effort,
                    web_search="disabled",
                ),
                "Reply with exactly OK. Do not use tools.",
                event_handler=count_event,
            )
        response_preview = _response_preview(response)
        if not response_preview:
            return ProbeResult(
                provider_id=provider_id,
                provider_type=provider_type,
                protocol=protocol,
                model=model,
                status="empty_response",
                elapsed_seconds=round(time.monotonic() - started, 3),
                error=(
                    "Codex turn completed without assistant text. "
                    f"Events: {json.dumps(event_counts, sort_keys=True)}. "
                    f"Warnings: {json.dumps(warnings, ensure_ascii=False)}"
                ),
            )
        return ProbeResult(
            provider_id=provider_id,
            provider_type=provider_type,
            protocol=protocol,
            model=model,
            status="success",
            elapsed_seconds=round(time.monotonic() - started, 3),
            response=response_preview,
        )
    except Exception as exc:
        status, http_status, message = _classify_error(exc)
        return ProbeResult(
            provider_id=provider_id,
            provider_type=provider_type,
            protocol=protocol,
            model=model,
            status=status,
            elapsed_seconds=round(time.monotonic() - started, 3),
            http_status=http_status,
            error=message,
        )
    finally:
        manager.close_all()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe configured chat Providers through the real Codex app-server.")
    parser.add_argument("--provider", action="append", default=[], help="ProviderID to probe; repeat as needed.")
    parser.add_argument("--codex-command", default="codex", help="Codex executable or command name.")
    parser.add_argument("--working-path", default=os.getcwd(), help="Existing working directory passed to Codex.")
    parser.add_argument("--reasoning-effort", default="high", help="Codex reasoning effort for the probe.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    working_path = os.path.abspath(os.path.expanduser(args.working_path))
    if not os.path.isdir(working_path):
        raise ValueError(f"Working path does not exist: {working_path}")
    loader = ConfigLoader()
    provider_ids = _selected_provider_ids(loader, [str(item) for item in args.provider])
    gateway = CodexProviderGateway()
    failures = 0
    try:
        for provider_id in provider_ids:
            result = _probe_one(
                loader=loader,
                gateway=gateway,
                provider_id=provider_id,
                codex_command=str(args.codex_command),
                working_path=working_path,
                reasoning_effort=str(args.reasoning_effort),
            )
            print(json.dumps(asdict(result), ensure_ascii=False), flush=True)
            if result.status != "success":
                failures += 1
    finally:
        gateway.close()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

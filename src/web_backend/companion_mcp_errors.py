from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException


@dataclass(frozen=True)
class CompanionErrorPayload:
    code: str
    message: str
    hint: str = ""

    def to_payload(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.hint:
            payload["hint"] = self.hint
        return payload


class CompanionError(RuntimeError):
    def __init__(self, code: str, message: str, *, hint: str = "") -> None:
        self.payload = CompanionErrorPayload(code=code, message=message, hint=hint)
        super().__init__(message)

    def to_result(self) -> dict[str, Any]:
        return {"ok": False, "error": self.payload.to_payload()}


def companion_error_from_exception(exc: Exception) -> CompanionError:
    if isinstance(exc, CompanionError):
        return exc
    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else repr(exc.detail)
        return CompanionError(
            code=_http_error_code(exc.status_code, detail),
            message=detail,
            hint=_http_error_hint(exc.status_code),
        )
    if isinstance(exc, ValueError):
        return CompanionError(code="invalid_request", message=str(exc))
    return CompanionError(code="internal_error", message=f"{type(exc).__name__}: {exc}")


def _http_error_code(status_code: int, detail: str) -> str:
    if status_code == 400:
        return "bad_request"
    if status_code == 404:
        return "node_not_found" if "node" in detail.casefold() else "not_found"
    if status_code == 409:
        return "conflict"
    if status_code == 504:
        return "timeout"
    if 400 <= status_code < 500:
        return "client_error"
    return "server_error"


def _http_error_hint(status_code: int) -> str:
    if status_code == 404:
        return "Check graph_id and node_id with list_node_status before retrying."
    if status_code == 409:
        return "Inspect node state; stop_node or wait before retrying."
    if status_code >= 500:
        return "Check the AITools server log for the backend traceback."
    return ""


__all__ = ["CompanionError", "CompanionErrorPayload", "companion_error_from_exception"]

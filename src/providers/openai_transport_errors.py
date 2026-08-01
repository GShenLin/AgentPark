import json

from src.providers.provider_errors import ProviderHttpError
from src.providers.provider_errors import ProviderTransportError


class OpenAIHttpError(ProviderHttpError):
    def __init__(
        self,
        status_code: int,
        response_body: str,
        *,
        provider_code: str = "",
        response_event_type: str = "",
        retry_scope: str = "stream",
    ):
        super().__init__(status_code, response_body)
        self.provider_code = (
            str(provider_code or "").strip().lower()
            or _provider_code_from_json_body(response_body)
        )
        self.response_event_type = str(response_event_type or "").strip().lower()
        self.retry_scope = _retry_scope(retry_scope)


class OpenAITransportError(ProviderTransportError):
    def __init__(self, message: str, *, retry_scope: str = "stream"):
        super().__init__(message)
        self.retry_scope = _retry_scope(retry_scope)


class OpenAIResponseIncompleteError(OpenAITransportError):
    def __init__(self, *, response: dict, reason: str = ""):
        self.response = dict(response)
        self.response_id = str(self.response.get("id") or "").strip()
        self.reason = str(reason or "").strip() or "unspecified"
        identity = f" {self.response_id}" if self.response_id else ""
        super().__init__(f"Responses response{identity} ended incomplete: {self.reason}")


def _provider_code_from_json_body(response_body: object) -> str:
    try:
        payload = json.loads(str(response_body or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if not isinstance(error, dict):
        return ""
    return str(error.get("code") or error.get("type") or "").strip().lower()


def _retry_scope(value: object) -> str:
    scope = str(value or "").strip().lower()
    if scope not in {"request", "stream"}:
        raise ValueError("retry scope must be 'request' or 'stream'")
    return scope

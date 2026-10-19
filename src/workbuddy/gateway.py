"""Authenticated control plane over AgentPark's shared HTTP transport."""
import json
from urllib.parse import urlsplit

from pydantic import ValidationError

from src.provider_auth.credentials import resolve_provider_api_key
from src.providers.curl_transport import CurlHttpTransport, CurlTransportError
from .contracts import AccountStatus, Catalog, ConnectionStatus, Login


class WorkBuddyError(RuntimeError):
    pass


def gateway_origin(base_url: str) -> str:
    url = urlsplit(base_url)
    if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path.rstrip("/") != "/v1"):
        raise ValueError("WorkBuddy baseUrl must be an HTTP(S) origin followed by /v1")
    if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Remote WorkBuddy gateways require HTTPS")
    return f"{url.scheme}://{url.netloc}"


def validate_config(config: dict) -> None:
    gateway_origin(str(config.get("baseUrl") or ""))
    if config.get("responsesApi") is True or config.get("authMode", "api_key") != "api_key":
        raise ValueError("WorkBuddy uses a gateway API key and Chat Completions")
    if any(mode != "chat" for mode in config.get("supportmode", [])):
        raise ValueError("WorkBuddy supports chat mode only")


class WorkBuddyGateway:
    def __init__(self, config: dict):
        validate_config(config)
        self.origin = gateway_origin(config["baseUrl"])
        self.key = resolve_provider_api_key(config)
        self.transport = CurlHttpTransport()

    def _request(self, path: str, contract, body: dict | None = None):
        try:
            response = self.transport.request(
                url=self.origin + path, method="GET" if body is None else "POST",
                headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
                body=None if body is None else json.dumps(body).encode("utf-8"),
                timeout_sec=30, follow_redirects=False, max_response_bytes=2_000_000,
            )
        except CurlTransportError as exc:
            raise WorkBuddyError("WorkBuddy 服务连接失败，请检查设置中的服务状态。") from exc
        if not 200 <= response.status_code < 300:
            raise WorkBuddyError(f"WorkBuddy gateway returned HTTP {response.status_code}")
        try:
            return contract.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise WorkBuddyError("WorkBuddy gateway returned an invalid response") from exc

    def status(self) -> AccountStatus:
        return self._request("/workbuddy/status", AccountStatus)

    def catalog(self) -> Catalog:
        return self._request("/workbuddy/models", Catalog)

    def login(self) -> Login:
        return self._request("/workbuddy/connect/start", Login, {})

    def finish(self, login_id: str) -> ConnectionStatus:
        return self._request("/workbuddy/connect/finish", ConnectionStatus, {"loginId": login_id})

    def logout(self) -> ConnectionStatus:
        return self._request("/workbuddy/logout", ConnectionStatus, {})

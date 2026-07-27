from __future__ import annotations

import base64
import hashlib
import html
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .store import get_account, save_account, update_account_credential


ISSUER = "https://auth.x.ai"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
SCOPE = "openid profile email offline_access grok-cli:access api:access"
CALLBACK_PORT = 56121
REFRESH_MARGIN_SECONDS = 300


class XaiOAuthError(RuntimeError):
    pass


def _request_json(url: str, *, data: dict[str, str] | None = None) -> dict:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode("utf-8") if data is not None else None,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise XaiOAuthError(f"xAI authorization returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise XaiOAuthError(f"xAI authorization request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise XaiOAuthError("xAI authorization returned an invalid response.")
    return payload


def _validate_endpoint(value: object) -> str:
    parsed = urllib.parse.urlparse(str(value or ""))
    host = str(parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "x.ai" or host.endswith(".x.ai")):
        raise XaiOAuthError("xAI discovery returned an endpoint outside the x.ai domain.")
    return str(value)


def _discover() -> tuple[str, str]:
    payload = _request_json(DISCOVERY_URL)
    return _validate_endpoint(payload.get("authorization_endpoint")), _validate_endpoint(payload.get("token_endpoint"))


def _claims(token: str) -> dict:
    parts = str(token or "").split(".")
    if len(parts) != 3:
        return {}
    try:
        return json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _normalize(payload: dict, refresh_fallback: str = "") -> dict:
    access = str(payload.get("access_token") or "").strip()
    refresh = str(payload.get("refresh_token") or refresh_fallback).strip()
    if not access or not refresh:
        raise XaiOAuthError("xAI token response is missing access_token or refresh_token.")
    claims = _claims(str(payload.get("id_token") or "")) or _claims(access)
    identity = str(claims.get("sub") or claims.get("email") or "").strip()
    if not identity:
        raise XaiOAuthError("xAI token does not contain a stable account identity.")
    return {
        "accessToken": access,
        "refreshToken": refresh,
        "expiresAt": int(time.time()) + int(payload.get("expires_in") or 3600),
        "identity": identity,
        "email": str(claims.get("email") or "").strip().lower(),
    }


def refresh_authorization(*, force: bool = False, account_id: str | None = None) -> dict:
    account = get_account("xai", account_id)
    if account is None:
        raise XaiOAuthError("xAI authorization is required.")
    credential = dict(account.credential)
    if not force and int(credential.get("expiresAt") or 0) > int(time.time()) + REFRESH_MARGIN_SECONDS:
        return credential
    _authorize_url, token_url = _discover()
    refreshed = _normalize(
        _request_json(
            token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": str(credential.get("refreshToken") or ""),
            },
        ),
        str(credential.get("refreshToken") or ""),
    )
    update_account_credential("xai", account.id, refreshed)
    return refreshed


class XaiLoginManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session: dict | None = None

    def start(self) -> dict:
        with self._lock:
            if self._session and self._session["thread"].is_alive():
                return {"started": False, "authUrl": self._session["auth_url"], "port": CALLBACK_PORT}
            authorization_url, token_url = _discover()
            verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("ascii").rstrip("=")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
            state = secrets.token_urlsafe(32)
            redirect_uri = f"http://127.0.0.1:{CALLBACK_PORT}/callback"
            query = urllib.parse.urlencode({
                "response_type": "code",
                "client_id": CLIENT_ID,
                "redirect_uri": redirect_uri,
                "scope": SCOPE,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
                "nonce": str(uuid.uuid4()),
            })
            auth_url = f"{authorization_url}?{query}"
            try:
                server = ThreadingHTTPServer(("127.0.0.1", CALLBACK_PORT), BaseHTTPRequestHandler)
            except OSError as exc:
                raise XaiOAuthError(f"xAI callback port {CALLBACK_PORT} is unavailable: {exc}") from exc
            manager = self

            class CallbackHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    manager._callback(self, server, token_url, redirect_uri, verifier, state)

                def log_message(self, _format, *_args):
                    return

            server.RequestHandlerClass = CallbackHandler
            thread = threading.Thread(target=server.serve_forever, name="xai-oauth-callback", daemon=True)
            self._session = {"thread": thread, "server": server, "auth_url": auth_url}
            thread.start()
            return {"started": True, "authUrl": auth_url, "port": CALLBACK_PORT}

    def _callback(self, handler, server, token_url: str, redirect_uri: str, verifier: str, state: str) -> None:
        status, message = 200, "xAI authorization completed. You can close this window."
        try:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
            if not secrets.compare_digest(str((query.get("state") or [""])[0]), state):
                raise XaiOAuthError("xAI callback state did not match.")
            code = str((query.get("code") or [""])[0])
            if not code:
                raise XaiOAuthError(str((query.get("error_description") or query.get("error") or ["Missing authorization code."])[0]))
            credential = _normalize(_request_json(token_url, data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            }))
            save_account("xai", kind="oauth", credential=credential, identity=credential["identity"])
        except XaiOAuthError as exc:
            status, message = 400, f"xAI authorization failed: {exc}"
        body = f"<!doctype html><meta charset='utf-8'><h2>{html.escape(message)}</h2>".encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        with self._lock:
            self._session = None
        threading.Thread(target=server.shutdown, daemon=True).start()


login_manager = XaiLoginManager()


__all__ = ["XaiOAuthError", "login_manager", "refresh_authorization"]

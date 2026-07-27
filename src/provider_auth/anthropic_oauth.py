from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .store import get_account, save_account, update_account_credential


CLIENT_ID = base64.b64decode("OWQxYzI1MGEtZTYxYi00NGQ5LTg4ZWQtNTk0NGQxOTYyZjVl").decode("ascii")
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"
CALLBACK_PORT = 54545
CALLBACK_PATH = "/callback"
SCOPES = "org:create_api_key user:profile user:inference"
OAUTH_BETA = "claude-code-20250219,oauth-2025-04-20"
CLAUDE_CODE_SYSTEM_INSTRUCTION = "You are a Claude agent, built on Anthropic's Claude Agent SDK."
REFRESH_MARGIN_SECONDS = 300


class AnthropicOAuthError(RuntimeError):
    pass


def _post_token(payload: dict) -> dict:
    request = urllib.request.Request(
        TOKEN_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise AnthropicOAuthError(f"Anthropic OAuth returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise AnthropicOAuthError(f"Anthropic OAuth request failed: {exc}") from exc
    if not isinstance(value, dict):
        raise AnthropicOAuthError("Anthropic OAuth returned an invalid response.")
    return value


def _normalize(payload: dict, refresh_fallback: str = "") -> dict:
    access = str(payload.get("access_token") or "").strip()
    refresh = str(payload.get("refresh_token") or refresh_fallback).strip()
    account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    identity = str(account.get("uuid") or account.get("email_address") or "").strip()
    if not access or not refresh:
        raise AnthropicOAuthError("Anthropic token response is missing access_token or refresh_token.")
    if not identity:
        raise AnthropicOAuthError("Anthropic token response is missing a stable account identity.")
    return {
        "accessToken": access,
        "refreshToken": refresh,
        "expiresAt": int(time.time()) + int(payload.get("expires_in") or 3600),
        "identity": identity,
        "email": str(account.get("email_address") or "").strip().lower(),
    }


def refresh_authorization(*, force: bool = False, account_id: str | None = None) -> dict:
    account = get_account("anthropic", account_id)
    if account is None:
        raise AnthropicOAuthError("Claude authorization is required.")
    credential = dict(account.credential)
    if not force and int(credential.get("expiresAt") or 0) > int(time.time()) + REFRESH_MARGIN_SECONDS:
        return credential
    refreshed = _normalize(
        _post_token({
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": str(credential.get("refreshToken") or ""),
        }),
        str(credential.get("refreshToken") or ""),
    )
    update_account_credential("anthropic", account.id, refreshed)
    return refreshed


class AnthropicLoginManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session: dict | None = None

    def start(self) -> dict:
        with self._lock:
            if self._session:
                return {"started": False, "authUrl": self._session["auth_url"], "port": CALLBACK_PORT, "manualCode": True}
            verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("ascii").rstrip("=")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
            state = secrets.token_urlsafe(32)
            redirect_uri = f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"
            query = urllib.parse.urlencode({
                "code": "true",
                "client_id": CLIENT_ID,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": SCOPES,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
            })
            auth_url = f"{AUTHORIZE_URL}?{query}"
            server = self._bind_server()
            manager = self

            class CallbackHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    query_values = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    code = str((query_values.get("code") or [""])[0])
                    callback_state = str((query_values.get("state") or [""])[0])
                    try:
                        manager._complete(code, callback_state)
                        manager._send_page(self, 200, "Claude authorization completed. You can close this window.")
                    except AnthropicOAuthError as exc:
                        manager._send_page(self, 400, f"Claude authorization failed: {exc}")

                def log_message(self, _format, *_args):
                    return

            server.RequestHandlerClass = CallbackHandler
            thread = threading.Thread(target=server.serve_forever, name="anthropic-oauth-callback", daemon=True)
            self._session = {
                "auth_url": auth_url,
                "verifier": verifier,
                "state": state,
                "redirect_uri": redirect_uri,
                "server": server,
                "thread": thread,
            }
            thread.start()
            return {"started": True, "authUrl": auth_url, "port": CALLBACK_PORT, "manualCode": True}

    @staticmethod
    def _bind_server() -> ThreadingHTTPServer:
        try:
            return ThreadingHTTPServer(("127.0.0.1", CALLBACK_PORT), BaseHTTPRequestHandler)
        except OSError as exc:
            raise AnthropicOAuthError(f"Claude callback port {CALLBACK_PORT} is unavailable: {exc}") from exc

    def submit_code(self, value: str) -> dict:
        raw = str(value or "").strip()
        if not raw:
            raise AnthropicOAuthError("Claude authorization code is required.")
        parsed = urllib.parse.urlparse(raw)
        if parsed.scheme and parsed.query:
            query = urllib.parse.parse_qs(parsed.query)
            code = str((query.get("code") or [""])[0])
            state = str((query.get("state") or [""])[0])
        else:
            code, separator, state = raw.partition("#")
            if not separator:
                with self._lock:
                    state = str((self._session or {}).get("state") or "")
        self._complete(code, state)
        return {"completed": True}

    def _complete(self, code: str, state: str) -> None:
        with self._lock:
            session = self._session
        if not session:
            raise AnthropicOAuthError("No Claude login is in progress.")
        if not code:
            raise AnthropicOAuthError("Claude authorization code is missing.")
        if not secrets.compare_digest(str(state or ""), str(session["state"])):
            raise AnthropicOAuthError("Claude authorization state did not match.")
        credential = _normalize(_post_token({
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "state": state,
            "redirect_uri": session["redirect_uri"],
            "code_verifier": session["verifier"],
        }))
        save_account("anthropic", kind="oauth", credential=credential, identity=credential["identity"])
        with self._lock:
            self._session = None
        threading.Thread(target=session["server"].shutdown, daemon=True).start()

    @staticmethod
    def _send_page(handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
        body = f"<!doctype html><meta charset='utf-8'><h2>{message}</h2>".encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)


login_manager = AnthropicLoginManager()


__all__ = [
    "AnthropicOAuthError",
    "CLAUDE_CODE_SYSTEM_INSTRUCTION",
    "OAUTH_BETA",
    "login_manager",
    "refresh_authorization",
]

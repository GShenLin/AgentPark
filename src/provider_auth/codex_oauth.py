from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.file_transaction import atomic_write_text, run_with_interprocess_lock


ISSUER = "https://auth.openai.com"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
RESPONSES_BASE_URL = "https://chatgpt.com/backend-api/codex"
CALLBACK_PORTS = (1455, 1457)
REFRESH_MARGIN_SECONDS = 300


class CodexOAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodexCredentials:
    access_token: str
    account_id: str
    expires_at: int | None


def codex_home() -> str:
    configured = str(os.environ.get("CODEX_HOME") or "").strip()
    return os.path.abspath(os.path.expanduser(configured or os.path.join("~", ".codex")))


def auth_json_path() -> str:
    return os.path.join(codex_home(), "auth.json")


def _decode_jwt(token: str) -> dict:
    parts = str(token or "").split(".")
    if len(parts) != 3 or not parts[1]:
        raise CodexOAuthError("OAuth token is not a valid JWT.")
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexOAuthError("OAuth token contains invalid JWT claims.") from exc
    if not isinstance(payload, dict):
        raise CodexOAuthError("OAuth token JWT claims must be an object.")
    return payload


def _token_profile(id_token: str) -> dict:
    claims = _decode_jwt(id_token)
    profile = claims.get("https://api.openai.com/profile")
    auth = claims.get("https://api.openai.com/auth")
    profile = profile if isinstance(profile, dict) else {}
    auth = auth if isinstance(auth, dict) else {}
    return {
        "email": str(claims.get("email") or profile.get("email") or "").strip(),
        "plan_type": str(auth.get("chatgpt_plan_type") or "").strip(),
        "account_id": str(auth.get("chatgpt_account_id") or "").strip(),
    }


def _read_auth() -> dict:
    path = auth_json_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise CodexOAuthError(f"OpenAI official authorization was not found at {path}.") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise CodexOAuthError(f"Failed to read OpenAI official authorization: {exc}") from exc
    if not isinstance(payload, dict):
        raise CodexOAuthError("OpenAI official authorization must be a JSON object.")
    return payload


def _validate_auth(payload: dict) -> tuple[dict, dict]:
    if str(payload.get("auth_mode") or "").strip().lower() != "chatgpt":
        raise CodexOAuthError("Codex auth.json does not contain ChatGPT OAuth authorization.")
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        raise CodexOAuthError("Codex auth.json is missing OAuth tokens.")
    for key in ("id_token", "access_token", "refresh_token"):
        if not str(tokens.get(key) or "").strip():
            raise CodexOAuthError(f"Codex auth.json is missing tokens.{key}.")
    profile = _token_profile(str(tokens["id_token"]))
    account_id = str(tokens.get("account_id") or profile["account_id"] or "").strip()
    if not account_id:
        raise CodexOAuthError("Codex auth.json is missing the ChatGPT account id.")
    tokens["account_id"] = account_id
    return tokens, profile


def _expires_at(access_token: str) -> int | None:
    value = _decode_jwt(access_token).get("exp")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _request_json(url: str, *, data: dict, form: bool = False, timeout: float = 30) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8") if form else json.dumps(data).encode("utf-8")
    content_type = "application/x-www-form-urlencoded" if form else "application/json"
    request = urllib.request.Request(url, data=body, headers={"Content-Type": content_type}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise CodexOAuthError(f"OpenAI authorization endpoint returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise CodexOAuthError(f"OpenAI authorization request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise CodexOAuthError("OpenAI authorization endpoint returned an invalid response.")
    return payload


def _write_auth(payload: dict) -> None:
    path = auth_json_path()
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(path, 0o600)


def refresh_authorization(*, force: bool = False) -> CodexCredentials:
    path = auth_json_path()

    def refresh_locked() -> CodexCredentials:
        payload = _read_auth()
        tokens, _profile = _validate_auth(payload)
        attempted_access_token = str(tokens["access_token"])
        attempted_refresh_token = str(tokens["refresh_token"])
        expires_at = _expires_at(str(tokens["access_token"]))
        if not force and (expires_at is None or expires_at > int(time.time()) + REFRESH_MARGIN_SECONDS):
            return CodexCredentials(str(tokens["access_token"]), str(tokens["account_id"]), expires_at)
        refreshed = _request_json(
            f"{ISSUER}/oauth/token",
            data={"client_id": CLIENT_ID, "grant_type": "refresh_token", "refresh_token": str(tokens["refresh_token"])},
        )
        for key in ("id_token", "access_token", "refresh_token"):
            value = str(refreshed.get(key) or "").strip()
            if value:
                tokens[key] = value
        current_payload = _read_auth()
        current_tokens, _current_profile = _validate_auth(current_payload)
        if (
            str(current_tokens["access_token"]) != attempted_access_token
            or str(current_tokens["refresh_token"]) != attempted_refresh_token
        ):
            current_expires_at = _expires_at(str(current_tokens["access_token"]))
            return CodexCredentials(
                str(current_tokens["access_token"]),
                str(current_tokens["account_id"]),
                current_expires_at,
            )
        _validate_auth(payload)
        payload["last_refresh"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _write_auth(payload)
        return CodexCredentials(str(tokens["access_token"]), str(tokens["account_id"]), _expires_at(str(tokens["access_token"])))

    return run_with_interprocess_lock(f"{path}.lock", refresh_locked)


def authorization_status() -> dict:
    try:
        payload = _read_auth()
        tokens, profile = _validate_auth(payload)
        expires_at = _expires_at(str(tokens["access_token"]))
        return {
            "authorized": True,
            "email": profile["email"],
            "planType": profile["plan_type"],
            "accountIdSuffix": str(tokens["account_id"])[-6:],
            "expiresAt": datetime.fromtimestamp(expires_at, timezone.utc).isoformat().replace("+00:00", "Z") if expires_at else "",
            "needsRefresh": expires_at is not None and expires_at <= int(time.time()) + REFRESH_MARGIN_SECONDS,
            "authPath": auth_json_path(),
            "error": "",
        }
    except CodexOAuthError as exc:
        return {"authorized": False, "email": "", "planType": "", "accountIdSuffix": "", "expiresAt": "", "needsRefresh": False, "authPath": auth_json_path(), "error": str(exc)}


class CodexOAuthLoginManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session: dict | None = None

    def start(self) -> dict:
        with self._lock:
            if self._session and self._session["thread"].is_alive():
                return {"started": False, "authUrl": self._session["auth_url"], "port": self._session["port"]}
            verifier = _base64url(secrets.token_bytes(64))
            state = _base64url(secrets.token_bytes(32))
            server = self._bind_server()
            port = int(server.server_address[1])
            redirect_uri = f"http://localhost:{port}/auth/callback"
            query = urllib.parse.urlencode({
                "response_type": "code", "client_id": CLIENT_ID, "redirect_uri": redirect_uri,
                "scope": "openid profile email offline_access api.connectors.read api.connectors.invoke",
                "code_challenge": _base64url(hashlib.sha256(verifier.encode("ascii")).digest()),
                "code_challenge_method": "S256", "id_token_add_organizations": "true",
                "codex_cli_simplified_flow": "true", "state": state, "originator": "codex_cli_rs",
            })
            auth_url = f"{ISSUER}/oauth/authorize?{query}"
            manager = self

            class CallbackHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    manager._handle_callback(self, redirect_uri, verifier, state)

                def log_message(self, _format, *_args):
                    return

            server.RequestHandlerClass = CallbackHandler
            thread = threading.Thread(target=server.serve_forever, name="openai-oauth-callback", daemon=True)
            self._session = {"server": server, "thread": thread, "auth_url": auth_url, "port": port}
            thread.start()
            return {"started": True, "authUrl": auth_url, "port": port}

    @staticmethod
    def _bind_server() -> ThreadingHTTPServer:
        last_error = None
        for port in CALLBACK_PORTS:
            try:
                return ThreadingHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
            except OSError as exc:
                last_error = exc
        raise CodexOAuthError(f"OpenAI login callback ports {CALLBACK_PORTS} are unavailable: {last_error}")

    def _handle_callback(self, handler: BaseHTTPRequestHandler, redirect_uri: str, verifier: str, state: str) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        try:
            oauth_error = str((query.get("error_description") or query.get("error") or [""])[0])
            if oauth_error:
                raise CodexOAuthError(f"OpenAI login was rejected: {oauth_error}")
            if not secrets.compare_digest(str((query.get("state") or [""])[0]), state):
                raise CodexOAuthError("OpenAI login callback state did not match.")
            code = str((query.get("code") or [""])[0])
            if not code:
                raise CodexOAuthError("OpenAI login callback did not include an authorization code.")
            tokens = _request_json(f"{ISSUER}/oauth/token", form=True, data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                "client_id": CLIENT_ID, "code_verifier": verifier,
            })
            for key in ("id_token", "access_token", "refresh_token"):
                if not str(tokens.get(key) or "").strip():
                    raise CodexOAuthError(f"OpenAI login response is missing {key}.")
            profile = _token_profile(str(tokens["id_token"]))
            if not profile["account_id"]:
                raise CodexOAuthError("OpenAI login token is missing the ChatGPT account id.")
            _write_auth({
                "auth_mode": "chatgpt", "OPENAI_API_KEY": None,
                "tokens": {"id_token": str(tokens["id_token"]), "access_token": str(tokens["access_token"]), "refresh_token": str(tokens["refresh_token"]), "account_id": profile["account_id"]},
                "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            })
            self._send_page(handler, 200, "OpenAI authorization completed. You can close this window.")
        except CodexOAuthError as exc:
            self._send_page(handler, 400, f"OpenAI authorization failed: {exc}")
        finally:
            with self._lock:
                session = self._session
                self._session = None
            if session:
                threading.Thread(target=session["server"].shutdown, daemon=True).start()

    @staticmethod
    def _send_page(handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
        escaped = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        body = f"<!doctype html><meta charset='utf-8'><title>AgentPark</title><body><h2>{escaped}</h2></body>".encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


login_manager = CodexOAuthLoginManager()

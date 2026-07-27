from __future__ import annotations

import base64
import json
import os
import platform
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from src.file_transaction import atomic_write_text
from .store import get_account, provider_auth_dir, save_account, update_account_credential


CLIENT_ID = "17e5f671-d194-4dfb-9706-5516cb48c098"
OAUTH_HOST = "https://auth.kimi.com"
REFRESH_MARGIN_SECONDS = 300
KIMI_CLI_VERSION = "0.14.0"


class KimiOAuthError(RuntimeError):
    pass


def _device_id() -> str:
    path = os.path.join(provider_auth_dir("kimi"), "device-id")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            existing = handle.read().strip()
            if existing:
                return existing
    except FileNotFoundError:
        pass
    value = uuid.uuid4().hex
    atomic_write_text(path, value + "\n", encoding="utf-8")
    return value


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": f"KimiCLI/{KIMI_CLI_VERSION}",
        "X-Msh-Platform": "kimi_code_cli",
        "X-Msh-Version": KIMI_CLI_VERSION,
        "X-Msh-Device-Name": socket.gethostname(),
        "X-Msh-Device-Model": f"{platform.system()} {platform.release()} {platform.machine()}".strip(),
        "X-Msh-Os-Version": platform.version(),
        "X-Msh-Device-Id": _device_id(),
    }


def _post(path: str, data: dict[str, str], timeout: float = 30) -> dict:
    request = urllib.request.Request(
        f"{OAUTH_HOST}{path}",
        data=urllib.parse.urlencode(data).encode("utf-8"),
        headers=_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise KimiOAuthError(f"Kimi authorization returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise KimiOAuthError(f"Kimi authorization request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise KimiOAuthError("Kimi authorization returned an invalid response.")
    return payload


def _jwt_identity(*tokens: str) -> tuple[str, str]:
    claims: list[dict] = []
    for token in tokens:
        parts = str(token or "").split(".")
        if len(parts) != 3:
            continue
        try:
            claims.append(json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    account_id = next((str(item.get("user_id")) for item in claims if item.get("user_id")), "")
    if not account_id:
        account_id = next((str(item.get("sub")) for item in claims if item.get("sub")), "")
    email = next((str(item.get("email")).lower() for item in claims if item.get("email")), "")
    return account_id or email, email


def _normalize_tokens(payload: dict, *, refresh_fallback: str = "") -> dict:
    access = str(payload.get("access_token") or "").strip()
    refresh = str(payload.get("refresh_token") or refresh_fallback).strip()
    if not access or not refresh:
        raise KimiOAuthError("Kimi token response is missing access_token or refresh_token.")
    expires_in = int(payload.get("expires_in") or 3600)
    identity, email = _jwt_identity(access, refresh)
    if not identity:
        raise KimiOAuthError("Kimi token does not contain a stable account identity.")
    return {
        "accessToken": access,
        "refreshToken": refresh,
        "expiresAt": int(time.time()) + max(60, expires_in),
        "identity": identity,
        "email": email,
    }


def refresh_authorization(*, force: bool = False, account_id: str | None = None) -> dict:
    account = get_account("kimi", account_id)
    if account is None:
        raise KimiOAuthError("Kimi authorization is required.")
    credential = dict(account.credential)
    if not force and int(credential.get("expiresAt") or 0) > int(time.time()) + REFRESH_MARGIN_SECONDS:
        return credential
    refreshed = _normalize_tokens(
        _post(
            "/api/oauth/token",
            {"grant_type": "refresh_token", "refresh_token": str(credential.get("refreshToken") or ""), "client_id": CLIENT_ID},
        ),
        refresh_fallback=str(credential.get("refreshToken") or ""),
    )
    update_account_credential("kimi", account.id, refreshed)
    return refreshed


class KimiLoginManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session: dict | None = None

    def start(self) -> dict:
        with self._lock:
            if self._session and self._session["thread"].is_alive():
                return dict(self._session["public"])
            device = _post("/api/oauth/device_authorization", {"client_id": CLIENT_ID})
            device_code = str(device.get("device_code") or "")
            user_code = str(device.get("user_code") or "")
            verify_url = str(device.get("verification_uri_complete") or device.get("verification_uri") or "")
            if not device_code or not user_code or not verify_url:
                raise KimiOAuthError("Kimi device authorization response is incomplete.")
            public = {"started": True, "authUrl": verify_url, "deviceCode": user_code}
            thread = threading.Thread(
                target=self._poll,
                args=(device_code, int(device.get("interval") or 5), int(device.get("expires_in") or 600)),
                name="kimi-oauth-device",
                daemon=True,
            )
            self._session = {"thread": thread, "public": public, "error": ""}
            thread.start()
            return public

    def _poll(self, device_code: str, interval: int, expires_in: int) -> None:
        deadline = time.monotonic() + expires_in
        error = ""
        try:
            while time.monotonic() < deadline:
                time.sleep(max(1, interval))
                try:
                    payload = _post(
                        "/api/oauth/token",
                        {"client_id": CLIENT_ID, "device_code": device_code, "grant_type": "urn:ietf:params:oauth:grant-type:device_code"},
                    )
                except KimiOAuthError as exc:
                    text = str(exc)
                    if "authorization_pending" in text:
                        continue
                    if "slow_down" in text:
                        interval += 5
                        continue
                    raise
                credential = _normalize_tokens(payload)
                save_account("kimi", kind="oauth", credential=credential, identity=credential["identity"])
                return
            error = "Kimi device authorization expired."
        except KimiOAuthError as exc:
            error = str(exc)
        finally:
            with self._lock:
                if self._session:
                    self._session["error"] = error


login_manager = KimiLoginManager()


__all__ = ["KimiOAuthError", "login_manager", "refresh_authorization"]

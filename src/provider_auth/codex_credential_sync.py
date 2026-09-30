"""Explicit, one-time import from the backend user's Codex file credential store."""

from __future__ import annotations

import json
import os
import time
import tomllib
from pathlib import Path

from src.file_transaction import run_with_interprocess_lock
from .codex_oauth import CodexOAuthError, _decode_jwt, _validate_auth, _write_auth
from .store import get_account, provider_auth_dir


def _read_local_auth() -> tuple[dict, Path]:
    configured_home = os.environ.get("CODEX_HOME", "").strip()
    codex_home = Path(configured_home).expanduser() if configured_home else Path.home() / ".codex"
    codex_home = codex_home.resolve()
    config_path = codex_home / "config.toml"
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise CodexOAuthError("无法读取本机 Codex 配置，请检查 config.toml。") from exc
    if config.get("cli_auth_credentials_store", "file") != "file":
        raise CodexOAuthError(
            "此入口仅支持 Codex 的 file 凭据存储；当前配置使用其他存储方式。"
            "请使用添加 OAuth 账号独立登录，避免读取可能过期的 auth.json 副本。"
        )
    source = codex_home / "auth.json"
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CodexOAuthError(
            f"未找到 {source}。读取位置是运行 AgentPark 服务的设备和系统用户，"
            "请确认该用户的 Codex 已登录并使用文件存储。"
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CodexOAuthError("无法读取本机 Codex auth.json，请检查文件权限和 JSON 格式。") from exc
    if not isinstance(payload, dict):
        raise CodexOAuthError("本机 Codex auth.json 必须是 JSON 对象。")
    return payload, source


def _validate_source(payload: dict) -> tuple[dict, dict]:
    # Reject malformed fields before the existing OAuth validator's coercions.
    tokens = payload.get("tokens")
    if payload.get("auth_mode") != "chatgpt" or not isinstance(tokens, dict):
        raise CodexOAuthError("本机 Codex 未使用 ChatGPT OAuth 登录，请使用添加 OAuth 账号。")
    for key in ("id_token", "access_token", "refresh_token"):
        if not isinstance(tokens.get(key), str) or not tokens[key].strip():
            raise CodexOAuthError(f"本机 Codex 凭据缺少有效的 tokens.{key}。")
    if tokens.get("account_id") is not None and not isinstance(tokens["account_id"], str):
        raise CodexOAuthError("本机 Codex 凭据的 account_id 无效。")
    tokens, profile = _validate_auth(payload)
    if profile["account_id"] and profile["account_id"] != tokens["account_id"]:
        raise CodexOAuthError("本机 Codex 凭据中的账号信息不一致。")
    claims = _decode_jwt(tokens["access_token"])
    access_auth = claims.get("https://api.openai.com/auth")
    if isinstance(access_auth, dict) and access_auth.get("chatgpt_account_id") not in (None, tokens["account_id"]):
        raise CodexOAuthError("本机 Codex 访问令牌与登录账号不一致。")
    expires_at = claims.get("exp")
    if type(expires_at) is not int:
        raise CodexOAuthError("本机 Codex 访问令牌缺少有效的过期时间。")
    if expires_at <= int(time.time()):
        raise CodexOAuthError(
            "本机 Codex 访问令牌已过期。请先在 Codex 中完成一次正常请求后重试，"
            "或在 AgentPark 添加 OAuth 账号重新登录。"
        )
    return tokens, profile


def sync_local_codex_credentials(*, account_id: str | None = None) -> dict:
    """Update the selected/default account, or import the first OAuth account.

    Codex remains untouched. This deliberately does not refresh either token,
    make a model request, change a different active account, or watch the file.
    """
    def sync_locked() -> dict:
        payload, source = _read_local_auth()
        tokens, profile = _validate_source(payload)
        current = get_account("openai", account_id)
        if account_id and current is None:
            raise CodexOAuthError("要同步的 AgentPark 账号已不存在，请重新加载账号列表。")
        if current is not None:
            if current.kind != "oauth":
                raise CodexOAuthError("当前 AgentPark 账号不是 OAuth 账号，请先选择 OAuth 账号。")
            current_tokens, current_profile = _validate_auth(current.credential)
            current_subject = _decode_jwt(current_tokens["id_token"]).get("sub")
            source_subject = _decode_jwt(tokens["id_token"]).get("sub")
            same_user = (
                current_profile["email"] == profile["email"]
                if current_profile["email"] and profile["email"]
                else isinstance(current_subject, str) and bool(current_subject) and current_subject == source_subject
            )
            if current_subject and source_subject and current_subject != source_subject:
                same_user = False
            if (
                current_tokens["account_id"] != tokens["account_id"]
                or not same_user
            ):
                raise CodexOAuthError(
                    "本机 Codex 登录账号与当前 AgentPark 账号不一致，未修改凭据。"
                    "请先选择匹配的账号，或使用添加 OAuth 账号。"
                )
        # Persist only the documented ChatGPT credential fields.
        credential = {"auth_mode": "chatgpt", "tokens": {
            key: tokens[key] for key in ("id_token", "access_token", "refresh_token", "account_id")
        }}
        if isinstance(payload.get("last_refresh"), str):
            credential["last_refresh"] = payload["last_refresh"]
        selected_id = _write_auth(credential, account_id=current.id if current else None)
        return {"accountId": selected_id, "sourcePath": str(source)}

    # Match the lock used by AgentPark's normal OAuth refresh path.
    return run_with_interprocess_lock(f"{provider_auth_dir('openai')}.lock", sync_locked)

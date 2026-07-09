from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta

from src.workspace_settings import get_workspace_root


CHANNEL_ID = "openclaw-weixin"
DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
IMAGE_CONTEXT_MAX_ITEMS = 8


def normalize_account_id(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    safe = raw.replace("@", "-").replace(".", "-")
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", safe)
    safe = re.sub(r"-+", "-", safe).strip("-")
    return safe


def state_root() -> str:
    return os.path.join(get_workspace_root(), "config", "channel_state", CHANNEL_ID)


def accounts_dir() -> str:
    return os.path.join(state_root(), "accounts")


def account_index_path() -> str:
    return os.path.join(state_root(), "accounts.json")


def default_target_path() -> str:
    return os.path.join(state_root(), "default-target.json")


def account_path(account_id: str) -> str:
    return os.path.join(accounts_dir(), f"{normalize_account_id(account_id)}.json")


def sync_path(account_id: str) -> str:
    return os.path.join(accounts_dir(), f"{normalize_account_id(account_id)}.sync.json")


def context_tokens_path(account_id: str) -> str:
    return os.path.join(accounts_dir(), f"{normalize_account_id(account_id)}.context-tokens.json")


def image_context_path(account_id: str) -> str:
    return os.path.join(accounts_dir(), f"{normalize_account_id(account_id)}.image-context.json")


def _read_json(path: str) -> object:
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, payload: object) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def list_account_ids() -> list[str]:
    parsed = _read_json(account_index_path())
    if not isinstance(parsed, list):
        return []
    output: list[str] = []
    for item in parsed:
        account_id = normalize_account_id(item)
        if account_id and account_id not in output:
            output.append(account_id)
    return output


def register_account_id(account_id: str) -> str:
    normalized = normalize_account_id(account_id)
    if not normalized:
        raise ValueError("account_id is required")
    ids = list_account_ids()
    if normalized not in ids:
        ids.append(normalized)
        _write_json(account_index_path(), ids)
    return normalized


def save_account(account_id: str, *, token: str, base_url: str = "", user_id: str = "") -> str:
    normalized = register_account_id(account_id)
    token_text = str(token or "").strip()
    if not token_text:
        raise ValueError("token is required")
    payload = load_account(normalized) or {}
    payload.update(
        {
            "token": token_text,
            "baseUrl": str(base_url or "").strip() or DEFAULT_BASE_URL,
            "savedAt": datetime.now().isoformat(),
        }
    )
    user_text = str(user_id or "").strip()
    if user_text:
        payload["userId"] = user_text
    _write_json(account_path(normalized), payload)
    return normalized


def load_account(account_id: str) -> dict | None:
    normalized = normalize_account_id(account_id)
    if not normalized:
        return None
    parsed = _read_json(account_path(normalized))
    return parsed if isinstance(parsed, dict) else None


def resolve_account_id(configured: object = "") -> str:
    configured_id = normalize_account_id(configured)
    if configured_id:
        return configured_id
    ids = list_account_ids()
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise ValueError("openclaw-weixin account is not logged in")
    raise ValueError("account_id is required because multiple openclaw-weixin accounts exist")


def load_sync_buf(account_id: str) -> str:
    parsed = _read_json(sync_path(account_id))
    if not isinstance(parsed, dict):
        return ""
    return str(parsed.get("get_updates_buf") or "")


def save_sync_buf(account_id: str, value: object) -> None:
    _write_json(sync_path(account_id), {"get_updates_buf": str(value or "")})


def save_context_token(account_id: str, user_id: str, token: str) -> None:
    safe_account_id = normalize_account_id(account_id)
    user_text = str(user_id or "").strip()
    token_text = str(token or "").strip()
    if not safe_account_id or not user_text or not token_text:
        return
    parsed = _read_json(context_tokens_path(safe_account_id))
    tokens = parsed if isinstance(parsed, dict) else {}
    tokens[user_text] = token_text
    _write_json(context_tokens_path(safe_account_id), tokens)


def load_context_token(account_id: str, user_id: str) -> str:
    parsed = _read_json(context_tokens_path(account_id))
    if not isinstance(parsed, dict):
        return ""
    return str(parsed.get(str(user_id or "").strip()) or "")


def save_default_target(account_id: str, user_id: str, context_token: str = "") -> None:
    safe_account_id = normalize_account_id(account_id)
    user_text = str(user_id or "").strip()
    if not safe_account_id or not user_text:
        return
    token_text = str(context_token or "").strip()
    payload = {
        "channel": CHANNEL_ID,
        "accountId": safe_account_id,
        "toUserId": user_text,
        "savedAt": datetime.now().isoformat(),
    }
    if token_text:
        payload["contextToken"] = token_text
    _write_json(default_target_path(), payload)


def load_default_target() -> dict:
    parsed = _read_json(default_target_path())
    if not isinstance(parsed, dict):
        return {}
    account_id = normalize_account_id(parsed.get("accountId"))
    to_user_id = str(parsed.get("toUserId") or "").strip()
    if not account_id or not to_user_id:
        return {}
    output = {
        "channel": CHANNEL_ID,
        "accountId": account_id,
        "toUserId": to_user_id,
    }
    context_token = str(parsed.get("contextToken") or "").strip()
    if context_token:
        output["contextToken"] = context_token
    return output


def save_recent_image_context(account_id: str, user_id: str, resource_parts: list[dict]) -> None:
    safe_account_id = normalize_account_id(account_id)
    user_text = str(user_id or "").strip()
    new_resources = _resource_payloads(resource_parts)
    if not safe_account_id or not user_text or not new_resources:
        return
    parsed = _read_json(image_context_path(safe_account_id))
    contexts = parsed if isinstance(parsed, dict) else {}
    existing = contexts.get(user_text)
    resources: list[dict] = []
    if isinstance(existing, dict):
        saved_at = _parse_datetime(existing.get("savedAt"))
        existing_resources = existing.get("resources")
        if saved_at is not None and datetime.now() - saved_at <= timedelta(seconds=1800):
            resources = [dict(item) for item in existing_resources if isinstance(item, dict)] if isinstance(existing_resources, list) else []
    resources.extend(new_resources)
    contexts[user_text] = {
        "savedAt": datetime.now().isoformat(),
        "resources": resources[-IMAGE_CONTEXT_MAX_ITEMS:],
    }
    _write_json(image_context_path(safe_account_id), contexts)


def load_recent_image_context(account_id: str, user_id: str, *, max_age_seconds: int = 1800) -> list[dict]:
    safe_account_id = normalize_account_id(account_id)
    user_text = str(user_id or "").strip()
    if not safe_account_id or not user_text:
        return []
    parsed = _read_json(image_context_path(safe_account_id))
    if not isinstance(parsed, dict):
        return []
    entry = parsed.get(user_text)
    if not isinstance(entry, dict):
        return []
    saved_at = _parse_datetime(entry.get("savedAt"))
    if saved_at is None or datetime.now() - saved_at > timedelta(seconds=max(1, int(max_age_seconds))):
        return []
    resources = entry.get("resources")
    if not isinstance(resources, list):
        return []
    output: list[dict] = []
    for item in resources:
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri") or "").strip()
        kind = str(item.get("kind") or "").strip().lower()
        if not uri or kind != "image":
            continue
        copied = dict(item)
        metadata = copied.get("metadata")
        copied["metadata"] = dict(metadata) if isinstance(metadata, dict) else {}
        copied["metadata"]["context"] = "recent_channel_image"
        output.append({"type": "resource", "resource": copied})
    return output


def consume_recent_image_context(account_id: str, user_id: str, *, max_age_seconds: int = 1800) -> list[dict]:
    safe_account_id = normalize_account_id(account_id)
    user_text = str(user_id or "").strip()
    resources = load_recent_image_context(safe_account_id, user_text, max_age_seconds=max_age_seconds)
    if not safe_account_id or not user_text:
        return resources
    path = image_context_path(safe_account_id)
    parsed = _read_json(path)
    if isinstance(parsed, dict) and user_text in parsed:
        parsed.pop(user_text, None)
        _write_json(path, parsed)
    return resources


def _resource_payloads(resource_parts: list[dict]) -> list[dict]:
    output: list[dict] = []
    for part in resource_parts:
        if not isinstance(part, dict) or part.get("type") != "resource":
            continue
        resource = part.get("resource")
        if not isinstance(resource, dict):
            continue
        if str(resource.get("kind") or "").strip().lower() != "image":
            continue
        uri = str(resource.get("uri") or "").strip()
        if not uri:
            continue
        output.append(dict(resource))
    return output


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None

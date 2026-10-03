from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
from typing import Any

from src.file_transaction import atomic_write_text, run_with_interprocess_lock
from src.workspace_settings import get_workspace_root


ACCESS_POLICY_RELATIVE_PATH = os.path.join(".auth", "access-control.json")
DEFAULT_NONDEVELOPER_FILTERED_TOOLS = (
    "agent_schedule_tools",
    "agent_patch_tools",
    "apply_patch_tool",
    "capability_management_tools",
    "code_edit_tools",
    "console_tools",
    "console_session_tools",
    "file_write_tools",
    "shell_tools",
    "system_tools",
)
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_USERS = 1000
_MAX_FILTERED_TOOLS = 500


class AccessPolicyError(ValueError):
    pass


def access_policy_path(workspace_root: str | None = None) -> str:
    root = os.path.abspath(workspace_root or get_workspace_root())
    return os.path.join(root, ACCESS_POLICY_RELATIVE_PATH)


def default_access_policy() -> dict[str, Any]:
    return {
        "users": [],
        "nonDeveloperFilteredTools": list(DEFAULT_NONDEVELOPER_FILTERED_TOOLS),
    }


def load_access_policy(workspace_root: str | None = None) -> dict[str, Any]:
    path = access_policy_path(workspace_root)
    if not os.path.isfile(path):
        return default_access_policy()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise AccessPolicyError(f"failed to read {path}: {exc}") from exc
    return validate_access_policy(payload)


def save_access_policy(payload: object, workspace_root: str | None = None) -> dict[str, Any]:
    path = access_policy_path(workspace_root)
    normalized = validate_access_policy(payload)

    def write() -> dict[str, Any]:
        atomic_write_text(
            path,
            json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return normalized

    return run_with_interprocess_lock(path + ".lock", write)


def register_remote_user(
    *,
    client_id: object,
    username: object,
    ip: object,
    workspace_root: str | None = None,
) -> dict[str, Any]:
    safe_client_id = _client_id(client_id)
    safe_username = _username(username)
    safe_ip = str(ip or "").strip()
    path = access_policy_path(workspace_root)

    def mutate() -> dict[str, Any]:
        policy = load_access_policy(workspace_root)
        users = list(policy["users"])
        now = _utc_now()
        client_match_index = next(
            (
                index
                for index, item in enumerate(users)
                if safe_client_id in item["clientIds"]
            ),
            None,
        )
        username_match_index = next(
            (
                index
                for index, item in enumerate(users)
                if _username_key(item["username"]) == _username_key(safe_username)
            ),
            None,
        )
        # Preserve an existing device binding, otherwise recognize the same
        # normalized username as one user across multiple devices.
        match_index = (
            client_match_index
            if client_match_index is not None
            else username_match_index
        )
        if match_index is None:
            if len(users) >= _MAX_USERS:
                raise AccessPolicyError(
                    f"users cannot contain more than {_MAX_USERS} entries"
                )
            match = {
                "clientIds": [safe_client_id],
                "username": safe_username,
                "developer": False,
                "ips": [],
                "firstSeenAt": now,
                "lastSeenAt": now,
            }
            users.append(match)
        else:
            match = dict(users[match_index])
            users[match_index] = match
            match["lastSeenAt"] = now
            if safe_client_id not in match["clientIds"]:
                match["clientIds"] = [*match["clientIds"], safe_client_id][-100:]
        if safe_ip and safe_ip not in match["ips"]:
            match["ips"] = [*match["ips"], safe_ip][-100:]
        policy["users"] = users
        atomic_write_text(
            path,
            json.dumps(policy, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return dict(match)

    return run_with_interprocess_lock(path + ".lock", mutate)


def nondeveloper_filtered_tools(workspace_root: str | None = None) -> tuple[str, ...]:
    policy = load_access_policy(workspace_root)
    return tuple(policy["nonDeveloperFilteredTools"])


def validate_access_policy(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AccessPolicyError("access policy must be an object")
    unknown = sorted(set(payload) - {"users", "nonDeveloperFilteredTools"})
    if unknown:
        raise AccessPolicyError(f"unsupported access policy fields: {', '.join(unknown)}")

    raw_users = payload.get("users", [])
    if not isinstance(raw_users, list):
        raise AccessPolicyError("users must be an array")
    if len(raw_users) > _MAX_USERS:
        raise AccessPolicyError(f"users cannot contain more than {_MAX_USERS} entries")
    users: list[dict[str, Any]] = []
    user_indexes: dict[str, int] = {}
    for index, raw_user in enumerate(raw_users):
        if not isinstance(raw_user, dict):
            raise AccessPolicyError(f"users[{index}] must be an object")
        username = _username(raw_user.get("username"))
        username_key = _username_key(username)
        client_ids = _user_client_ids(raw_user, index)
        ips = _string_list(raw_user.get("ips", []), f"users[{index}].ips", maximum=100)
        normalized_user = {
            "clientIds": client_ids,
            "username": username,
            "developer": bool(raw_user.get("developer") is True),
            "ips": ips,
            "firstSeenAt": str(raw_user.get("firstSeenAt") or "").strip(),
            "lastSeenAt": str(raw_user.get("lastSeenAt") or "").strip(),
        }
        existing_index = user_indexes.get(username_key)
        if existing_index is None:
            user_indexes[username_key] = len(users)
            users.append(normalized_user)
            continue
        users[existing_index] = _merge_same_username_users(
            users[existing_index],
            normalized_user,
        )

    client_owners: dict[str, str] = {}
    for user in users:
        for client_id in user["clientIds"]:
            owner = client_owners.get(client_id)
            if owner is not None and owner != _username_key(user["username"]):
                raise AccessPolicyError(
                    f"clientId {client_id} belongs to multiple usernames"
                )
            client_owners[client_id] = _username_key(user["username"])

    filtered = _string_list(
        payload.get("nonDeveloperFilteredTools", list(DEFAULT_NONDEVELOPER_FILTERED_TOOLS)),
        "nonDeveloperFilteredTools",
        maximum=_MAX_FILTERED_TOOLS,
    )
    return {
        "users": users,
        "nonDeveloperFilteredTools": filtered,
    }


def _client_id(value: object) -> str:
    text = str(value or "").strip()
    if not _CLIENT_ID_RE.fullmatch(text):
        raise AccessPolicyError("clientId is invalid")
    return text


def _username(value: object) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 80 or any(ord(char) < 32 for char in text):
        raise AccessPolicyError("username must contain 1 to 80 visible characters")
    return text


def _username_key(value: object) -> str:
    return _username(value).casefold()


def _user_client_ids(raw_user: dict[str, Any], index: int) -> list[str]:
    if "clientIds" not in raw_user:
        return [_client_id(raw_user.get("clientId"))]
    raw_client_ids = raw_user.get("clientIds")
    if not isinstance(raw_client_ids, list):
        raise AccessPolicyError(f"users[{index}].clientIds must be an array")
    if len(raw_client_ids) > 100:
        raise AccessPolicyError(
            f"users[{index}].clientIds cannot contain more than 100 entries"
        )
    output: list[str] = []
    seen: set[str] = set()
    for client_index, value in enumerate(raw_client_ids):
        try:
            client_id = _client_id(value)
        except AccessPolicyError as exc:
            raise AccessPolicyError(
                f"users[{index}].clientIds[{client_index}] is invalid"
            ) from exc
        if client_id in seen:
            continue
        seen.add(client_id)
        output.append(client_id)
    return output


def _merge_same_username_users(
    current: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    return {
        "clientIds": _merge_unique(current["clientIds"], incoming["clientIds"]),
        "username": current["username"],
        "developer": current["developer"] is True or incoming["developer"] is True,
        "ips": _merge_unique(current["ips"], incoming["ips"]),
        "firstSeenAt": _earliest_nonempty(
            current["firstSeenAt"],
            incoming["firstSeenAt"],
        ),
        "lastSeenAt": _latest_nonempty(
            current["lastSeenAt"],
            incoming["lastSeenAt"],
        ),
    }


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in [*left, *right]:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output[-100:]


def _earliest_nonempty(left: str, right: str) -> str:
    values = [value for value in (left, right) if value]
    return min(values) if values else ""


def _latest_nonempty(left: str, right: str) -> str:
    values = [value for value in (left, right) if value]
    return max(values) if values else ""


def _string_list(value: object, label: str, *, maximum: int) -> list[str]:
    if not isinstance(value, list):
        raise AccessPolicyError(f"{label} must be an array")
    if len(value) > maximum:
        raise AccessPolicyError(f"{label} cannot contain more than {maximum} entries")
    output: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise AccessPolicyError(f"{label}[{index}] must be a non-empty string")
        text = item.strip()
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "ACCESS_POLICY_RELATIVE_PATH",
    "AccessPolicyError",
    "DEFAULT_NONDEVELOPER_FILTERED_TOOLS",
    "access_policy_path",
    "default_access_policy",
    "load_access_policy",
    "nondeveloper_filtered_tools",
    "register_remote_user",
    "save_access_policy",
    "validate_access_policy",
]

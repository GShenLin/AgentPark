from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from src.skills.script_arguments import SkillScriptArgumentError, validate_script_arguments
from src.tool.tool_json_response import tool_json_payload


SCRIPT_MANIFEST_FILENAME = "skill.json"
MAX_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class SkillScriptDefinition:
    id: str
    name: str
    description: str
    skill_name: str
    skill_dir: str
    entry: str
    args_schema: dict[str, Any]
    cwd: str
    timeout_seconds: int
    allow_write: bool
    enabled: bool

    @property
    def should_register(self) -> bool:
        if self.allow_write:
            return self.enabled
        return self.enabled

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "entry": self.entry,
            "args_schema": copy.deepcopy(self.args_schema),
            "cwd": self.cwd,
            "timeout_seconds": self.timeout_seconds,
            "allow_write": self.allow_write,
            "enabled": self.enabled,
            "registered": self.should_register,
        }


class SkillScriptManifestError(RuntimeError):
    pass


def load_skill_script_manifest(skill_dir: str, *, skill_name: str) -> tuple[SkillScriptDefinition, ...]:
    root = _real_dir(skill_dir)
    path = os.path.join(root, SCRIPT_MANIFEST_FILENAME)
    if not os.path.isfile(path):
        return ()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise SkillScriptManifestError(
            f"skill script manifest contains invalid JSON: {path}: line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise SkillScriptManifestError(f"failed to read skill script manifest: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SkillScriptManifestError(f"skill script manifest must be an object: {path}")

    scripts = payload.get("scripts")
    if scripts in (None, ""):
        return ()
    if not isinstance(scripts, list):
        raise SkillScriptManifestError(f"skill script manifest field `scripts` must be an array: {path}")

    result: list[SkillScriptDefinition] = []
    seen: set[str] = set()
    for index, item in enumerate(scripts):
        definition = _normalize_script_definition(item, root=root, skill_name=skill_name, manifest_path=path, index=index)
        key = definition.id.casefold()
        if key in seen:
            raise SkillScriptManifestError(f"duplicate skill script id `{definition.id}`: {path}")
        seen.add(key)
        result.append(definition)
    return tuple(result)


def run_skill_script(definition: SkillScriptDefinition, arguments: dict[str, Any]) -> str:
    try:
        normalized_args = validate_script_arguments(definition.args_schema, arguments)
    except SkillScriptArgumentError as exc:
        return tool_json_payload(
            {
                "status": "error",
                "exception_type": "SkillScriptArgumentError",
                "error": str(exc),
                "script": definition.id,
            }
        )

    command = _script_command(definition.entry)
    args_payload = json.dumps(normalized_args, ensure_ascii=False)
    env = dict(os.environ)
    env["AITOOLS_SKILL_SCRIPT_ID"] = definition.id
    env["AITOOLS_SKILL_SCRIPT_ARGS"] = args_payload
    env["AITOOLS_SKILL_SCRIPT_ALLOW_WRITE"] = "1" if definition.allow_write else "0"
    try:
        completed = subprocess.run(
            command,
            input=args_payload,
            text=True,
            capture_output=True,
            cwd=definition.cwd,
            env=env,
            timeout=definition.timeout_seconds,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        return tool_json_payload(
            {
                "status": "timeout",
                "script": definition.id,
                "exit_code": None,
                "timed_out": True,
                "timeout_seconds": definition.timeout_seconds,
                "stdout": _coerce_process_text(exc.stdout),
                "stderr": _coerce_process_text(exc.stderr),
                "error": f"skill script timed out after {definition.timeout_seconds}s",
            }
        )
    except OSError as exc:
        return tool_json_payload(
            {
                "status": "error",
                "exception_type": type(exc).__name__,
                "script": definition.id,
                "exit_code": None,
                "timed_out": False,
                "stdout": "",
                "stderr": "",
                "error": str(exc),
            }
        )

    result: dict[str, Any] = {
        "status": "success" if completed.returncode == 0 else "error",
        "script": definition.id,
        "exit_code": completed.returncode,
        "timed_out": False,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
    }
    if completed.returncode != 0:
        result["error"] = f"skill script exited with code {completed.returncode}"
    return tool_json_payload(result)


def _normalize_script_definition(
    value: object,
    *,
    root: str,
    skill_name: str,
    manifest_path: str,
    index: int,
) -> SkillScriptDefinition:
    if not isinstance(value, dict):
        raise SkillScriptManifestError(f"skill script entry at index {index} must be an object: {manifest_path}")
    script_id = _required_string(value.get("id"), "id", manifest_path, index=index)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", script_id):
        raise SkillScriptManifestError(
            f"skill script id must match ^[A-Za-z0-9][A-Za-z0-9_-]*$: {script_id}: {manifest_path}"
        )
    entry = _resolve_required_path(
        value.get("entry"),
        "entry",
        root=root,
        manifest_path=manifest_path,
        index=index,
        required_prefix="scripts/",
        require_file=True,
    )
    if not _is_supported_script_entry(entry):
        raise SkillScriptManifestError(
            f"skill script entry must be a Python or JavaScript file at index {index}: {manifest_path}"
        )
    args_schema = _required_schema(value, manifest_path, index=index)
    cwd = _resolve_required_path(
        value.get("cwd"),
        "cwd",
        root=root,
        manifest_path=manifest_path,
        index=index,
        required_prefix="",
        require_file=False,
    )
    timeout_seconds = _required_timeout(value, manifest_path, index=index)
    allow_write = _required_bool(_first_present(value, "allowWrite", "allow_write"), "allowWrite", manifest_path, index)
    enabled_raw = _first_present(value, "enabled")
    enabled = (not allow_write) if enabled_raw is None else _required_bool(enabled_raw, "enabled", manifest_path, index)
    return SkillScriptDefinition(
        id=script_id,
        name=_optional_string(value.get("name"), "name", manifest_path, index=index) or script_id,
        description=_optional_string(value.get("description"), "description", manifest_path, index=index),
        skill_name=skill_name,
        skill_dir=root,
        entry=entry,
        args_schema=args_schema,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        allow_write=allow_write,
        enabled=enabled,
    )


def _required_schema(value: dict[str, Any], manifest_path: str, *, index: int) -> dict[str, Any]:
    raw = _first_present(value, "argsSchema", "args_schema")
    if raw is None:
        raise SkillScriptManifestError(f"skill script at index {index} missing field `argsSchema`: {manifest_path}")
    if not isinstance(raw, dict):
        raise SkillScriptManifestError(f"skill script argsSchema must be an object at index {index}: {manifest_path}")
    schema = copy.deepcopy(raw)
    if schema.get("type") != "object":
        raise SkillScriptManifestError(f"skill script argsSchema type must be object at index {index}: {manifest_path}")
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        raise SkillScriptManifestError(f"skill script argsSchema properties must be an object at index {index}: {manifest_path}")
    required = schema.get("required") or []
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise SkillScriptManifestError(f"skill script argsSchema required must be an array of strings at index {index}: {manifest_path}")
    return schema


def _required_timeout(value: dict[str, Any], manifest_path: str, *, index: int) -> int:
    raw = _first_present(value, "timeoutSeconds", "timeout_seconds")
    if raw is None:
        raise SkillScriptManifestError(f"skill script at index {index} missing field `timeoutSeconds`: {manifest_path}")
    if isinstance(raw, bool):
        raise SkillScriptManifestError(f"skill script timeoutSeconds must be an integer at index {index}: {manifest_path}")
    try:
        timeout = int(raw)
    except Exception as exc:
        raise SkillScriptManifestError(
            f"skill script timeoutSeconds must be an integer at index {index}: {manifest_path}"
        ) from exc
    if timeout < 1 or timeout > MAX_TIMEOUT_SECONDS:
        raise SkillScriptManifestError(
            f"skill script timeoutSeconds must be between 1 and {MAX_TIMEOUT_SECONDS} at index {index}: {manifest_path}"
        )
    return timeout


def _resolve_required_path(
    value: object,
    field: str,
    *,
    root: str,
    manifest_path: str,
    index: int,
    required_prefix: str,
    require_file: bool,
) -> str:
    raw = _required_string(value, field, manifest_path, index=index)
    if not require_file and raw.replace("\\", "/").strip() == ".":
        normalized = ""
    else:
        normalized = _normalize_relative_path(raw, field, manifest_path, index=index)
    if required_prefix and not normalized.startswith(required_prefix):
        raise SkillScriptManifestError(
            f"skill script {field} must be under {required_prefix} at index {index}: {manifest_path}"
        )
    path = os.path.realpath(os.path.join(root, *normalized.split("/"))) if normalized else root
    if os.path.commonpath([root, path]) != root:
        raise SkillScriptManifestError(f"skill script {field} escapes skill root at index {index}: {manifest_path}")
    if require_file and not os.path.isfile(path):
        raise SkillScriptManifestError(f"skill script {field} does not exist at index {index}: {path}")
    if not require_file and not os.path.isdir(path):
        raise SkillScriptManifestError(f"skill script {field} directory does not exist at index {index}: {path}")
    return path


def _script_command(entry: str) -> list[str]:
    lower = entry.lower()
    if lower.endswith(".py"):
        return [sys.executable, entry]
    if lower.endswith((".js", ".mjs", ".cjs")):
        return ["node", entry]
    raise OSError(f"unsupported skill script extension: {entry}")


def _is_supported_script_entry(entry: str) -> bool:
    return entry.lower().endswith((".py", ".js", ".mjs", ".cjs"))


def _real_dir(path: str) -> str:
    root = os.path.realpath(str(path or "").strip())
    if not root or not os.path.isdir(root):
        raise SkillScriptManifestError(f"skill directory does not exist: {path}")
    return root


def _normalize_relative_path(value: str, field: str, manifest_path: str, *, index: int) -> str:
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        raise SkillScriptManifestError(f"skill script {field} is required at index {index}: {manifest_path}")
    if os.path.isabs(text):
        raise SkillScriptManifestError(f"skill script {field} must be relative at index {index}: {manifest_path}")
    parts = [part for part in text.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise SkillScriptManifestError(f"skill script {field} must not contain . or .. at index {index}: {manifest_path}")
    return "/".join(parts)


def _first_present(payload: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload:
            return payload.get(name)
    return None


def _required_string(value: object, field: str, manifest_path: str, *, index: int) -> str:
    text = _optional_string(value, field, manifest_path, index=index)
    if not text:
        raise SkillScriptManifestError(f"skill script at index {index} missing field `{field}`: {manifest_path}")
    return text


def _optional_string(value: object, field: str, manifest_path: str, *, index: int) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise SkillScriptManifestError(f"skill script field `{field}` must be a string at index {index}: {manifest_path}")
    return value.strip()


def _required_bool(value: object, field: str, manifest_path: str, index: int) -> bool:
    if not isinstance(value, bool):
        raise SkillScriptManifestError(f"skill script field `{field}` must be a boolean at index {index}: {manifest_path}")
    return value


def _coerce_process_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


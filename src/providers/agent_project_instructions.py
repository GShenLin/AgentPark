from __future__ import annotations

import hashlib
import os
from typing import Any

from src.providers.agent_runtime_context import get_agent_runtime_context


PROJECT_INSTRUCTIONS_PREFIX = "# AGENTS.md instructions"
PROJECT_INSTRUCTIONS_SUFFIX = "</INSTRUCTIONS>"
PROJECT_INSTRUCTIONS_REPLACEMENT_NOTICE = (
    "These AGENTS.md instructions replace all previously provided AGENTS.md instructions."
)
PROJECT_INSTRUCTIONS_REMOVAL_NOTICE = "The previously provided AGENTS.md instructions no longer apply."
AGENTS_MD_FILENAME = "AGENTS.md"
LOCAL_AGENTS_MD_FILENAME = "AGENTS.override.md"
DEFAULT_PROJECT_DOC_MAX_BYTES = 32 * 1024
DEFAULT_PROJECT_ROOT_MARKERS = (".git",)


def build_agent_project_instructions_context(
    agent: object,
    *,
    environment_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _project_instructions_enabled(agent):
        return {}
    root = _resolve_context_cwd(agent, environment_context)
    if not root or not os.path.isdir(root):
        return {}

    paths = _agents_md_paths(root, agent)
    if not paths:
        return {}

    remaining = _project_doc_max_bytes(agent)
    entries = []
    for path in paths:
        if remaining <= 0:
            break
        try:
            with open(path, "rb") as handle:
                data = handle.read(remaining + 1)
        except OSError:
            continue
        if len(data) > remaining:
            data = data[:remaining]
        text = data.decode("utf-8", errors="replace")
        if not text.strip():
            continue
        entries.append({"path": os.path.normpath(os.path.abspath(path)), "text": text})
        remaining -= len(data)

    if not entries:
        return {}

    return {
        "directory": os.path.normpath(os.path.abspath(root)),
        "paths": [entry["path"] for entry in entries],
        "text": "\n\n".join(entry["text"].rstrip() for entry in entries).strip(),
    }


def format_agent_project_instructions_context(
    context: dict[str, Any],
    *,
    notice: str = "",
) -> str:
    text = str((context or {}).get("text") or "").strip()
    notice = str(notice or "").strip()
    if notice == PROJECT_INSTRUCTIONS_REMOVAL_NOTICE and not text:
        text = notice
        notice = ""
    elif notice and text:
        text = f"{notice}\n\n{text}"
    if not text:
        return ""
    directory = str((context or {}).get("directory") or "").strip()
    header = PROJECT_INSTRUCTIONS_PREFIX
    if directory:
        header = f"{header} for {directory}"
    return f"{header}\n\n<INSTRUCTIONS>\n{text}\n{PROJECT_INSTRUCTIONS_SUFFIX}"


def is_agent_project_instructions_text(value: object) -> bool:
    text = str(value or "").strip()
    return text.startswith(PROJECT_INSTRUCTIONS_PREFIX) and text.endswith(PROJECT_INSTRUCTIONS_SUFFIX)


def project_instructions_text_hash(text: object) -> str:
    value = str(text or "")
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def project_instructions_update_notice(
    previous_context_item: dict[str, Any] | None,
    current_context: dict[str, Any] | None,
) -> str:
    previous = {}
    if isinstance(previous_context_item, dict) and isinstance(previous_context_item.get("project_instructions"), dict):
        previous = dict(previous_context_item.get("project_instructions") or {})
    previous_present = _snapshot_present(previous)
    current_text = str((current_context or {}).get("text") or "").strip()
    if current_text:
        if previous_present and _snapshot_changed(previous, current_context or {}):
            return PROJECT_INSTRUCTIONS_REPLACEMENT_NOTICE
        return ""
    if previous_present:
        return PROJECT_INSTRUCTIONS_REMOVAL_NOTICE
    return ""


def _resolve_context_cwd(agent: object, environment_context: dict[str, Any] | None) -> str:
    if isinstance(environment_context, dict):
        value = str(environment_context.get("workspace_path") or "").strip()
        if value:
            return os.path.normpath(os.path.abspath(os.path.expanduser(value)))
    runtime_context = get_agent_runtime_context(agent)
    value = str(runtime_context.working_path or "").strip()
    if value:
        return os.path.normpath(os.path.abspath(os.path.expanduser(value)))
    value = str(runtime_context.workspace_root or "").strip()
    if value:
        return os.path.normpath(os.path.abspath(os.path.expanduser(value)))
    return os.getcwd()


def _project_instructions_enabled(agent: object) -> bool:
    config = getattr(agent, "config", None)
    if isinstance(config, dict) and config.get("projectInstructions") is False:
        return False
    if isinstance(config, dict) and config.get("project_instructions") is False:
        return False
    runtime_context = get_agent_runtime_context(agent)
    return bool(
        str(runtime_context.workspace_root or "").strip()
        or str(runtime_context.working_path or "").strip()
    )


def _agents_md_paths(cwd: str, agent: object = None) -> list[str]:
    root = _nearest_project_root(cwd, _project_root_markers(agent))
    search_dirs = _path_chain(root, cwd)
    paths = []
    candidate_filenames = _candidate_filenames(agent)
    for directory in search_dirs:
        for filename in candidate_filenames:
            candidate = os.path.join(directory, filename)
            if os.path.isfile(candidate):
                paths.append(candidate)
                break
    return paths


def _nearest_project_root(cwd: str, markers: tuple[str, ...] = DEFAULT_PROJECT_ROOT_MARKERS) -> str:
    if not markers:
        return os.path.normpath(os.path.abspath(cwd))
    current = os.path.normpath(os.path.abspath(cwd))
    while True:
        if any(os.path.exists(os.path.join(current, marker)) for marker in markers):
            return current
        parent = os.path.dirname(current)
        if not parent or parent == current:
            return os.path.normpath(os.path.abspath(cwd))
        current = parent


def _path_chain(root: str, cwd: str) -> list[str]:
    root = os.path.normpath(os.path.abspath(root))
    cwd = os.path.normpath(os.path.abspath(cwd))
    chain = []
    current = cwd
    while True:
        chain.append(current)
        if current == root:
            break
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent
    chain.reverse()
    return chain


def _candidate_filenames(agent: object = None) -> tuple[str, ...]:
    names = [LOCAL_AGENTS_MD_FILENAME, AGENTS_MD_FILENAME]
    config = getattr(agent, "config", None)
    candidates = []
    if isinstance(config, dict):
        raw = config.get("projectDocFallbackFilenames")
        if raw is None:
            raw = config.get("project_doc_fallback_filenames")
        if isinstance(raw, list):
            candidates = [str(item).strip() for item in raw if str(item or "").strip()]
    for candidate in candidates:
        if candidate not in names:
            names.append(candidate)
    return tuple(names)


def _project_root_markers(agent: object = None) -> tuple[str, ...]:
    config = getattr(agent, "config", None)
    if not isinstance(config, dict):
        return DEFAULT_PROJECT_ROOT_MARKERS
    raw = config.get("projectRootMarkers")
    if raw is None:
        raw = config.get("project_root_markers")
    if raw is None:
        return DEFAULT_PROJECT_ROOT_MARKERS
    if not isinstance(raw, list):
        return DEFAULT_PROJECT_ROOT_MARKERS
    return tuple(str(item).strip() for item in raw if str(item or "").strip())


def _project_doc_max_bytes(agent: object) -> int:
    config = getattr(agent, "config", None)
    raw = config.get("projectDocMaxBytes") if isinstance(config, dict) else None
    if raw is None and isinstance(config, dict):
        raw = config.get("project_doc_max_bytes")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PROJECT_DOC_MAX_BYTES
    return max(0, value)


def _snapshot_present(snapshot: dict[str, Any]) -> bool:
    if not isinstance(snapshot, dict):
        return False
    try:
        chars = int(snapshot.get("chars") or 0)
    except (TypeError, ValueError):
        chars = 0
    return chars > 0 or bool(snapshot.get("text_hash") or snapshot.get("paths") or snapshot.get("directory"))


def _snapshot_changed(previous: dict[str, Any], current_context: dict[str, Any]) -> bool:
    current = {
        "directory": str(current_context.get("directory") or "").strip(),
        "paths": [str(path).strip() for path in current_context.get("paths") or [] if str(path or "").strip()],
        "chars": len(str(current_context.get("text") or "")),
        "text_hash": project_instructions_text_hash(current_context.get("text")),
    }
    comparable_keys = [key for key in ("directory", "paths", "chars", "text_hash") if key in previous]
    if not comparable_keys:
        return True
    for key in comparable_keys:
        if previous.get(key) != current.get(key):
            return True
    return False

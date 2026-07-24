from __future__ import annotations

import ntpath
import posixpath
from dataclasses import dataclass


REMOTE_WORKSPACE_TOOL_NAMES = frozenset(
    {
        "cancer_control",
        "execute_console_command",
        "ue_remote_control",
        "read_file",
        "write_file",
        "rg_search_text",
        "rg_list_files",
        "apply_patch",
    }
)


@dataclass(frozen=True)
class RemoteWorkspaceTarget:
    worker_id: str
    working_path: str


def remote_workspace_target(agent: object, tool_name: str) -> RemoteWorkspaceTarget | None:
    if str(tool_name or "").strip() not in REMOTE_WORKSPACE_TOOL_NAMES:
        return None
    from src.providers.agent_runtime_context import get_agent_runtime_context

    context = get_agent_runtime_context(agent)
    if not context.remote_enabled:
        return None
    worker_id = str(context.remote_worker_id or "").strip()
    if not worker_id:
        raise ValueError("Remote is enabled but no remote worker is paired with this node.")
    working_path = str(context.working_path or "").strip()
    if not working_path:
        raise ValueError("Remote WorkingPath is required and must be an absolute path on the worker machine.")
    if not _is_absolute_worker_path(working_path):
        raise ValueError(f"Remote WorkingPath must be an absolute path on the worker machine: {working_path}")
    return RemoteWorkspaceTarget(worker_id=worker_id, working_path=working_path)


def _is_absolute_worker_path(path: str) -> bool:
    return ntpath.isabs(path) or posixpath.isabs(path)

from __future__ import annotations


REMOTE_FILE_SYSTEM_TOOL_NAMES = frozenset(
    {
        "apply_patch",
        "execute_console_command",
        "read_file",
        "rg_list_files",
        "rg_search_text",
        "write_file",
    }
)

REMOTE_APPLICATION_TOOL_NAMES = frozenset(
    {
        "cancer_control",
        "ue_remote_control",
    }
)

REMOTE_WORKSPACE_TOOL_NAMES = (
    REMOTE_FILE_SYSTEM_TOOL_NAMES | REMOTE_APPLICATION_TOOL_NAMES
)

REMOTE_WORKER_CONTROL_CAPABILITIES = frozenset({"select_folder"})

STANDALONE_REMOTE_CAPABILITIES = (
    REMOTE_FILE_SYSTEM_TOOL_NAMES | REMOTE_WORKER_CONTROL_CAPABILITIES
)


__all__ = [
    "REMOTE_APPLICATION_TOOL_NAMES",
    "REMOTE_FILE_SYSTEM_TOOL_NAMES",
    "REMOTE_WORKER_CONTROL_CAPABILITIES",
    "REMOTE_WORKSPACE_TOOL_NAMES",
    "STANDALONE_REMOTE_CAPABILITIES",
]

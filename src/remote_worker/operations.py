from __future__ import annotations

import json
import ntpath
import os
import posixpath
from dataclasses import dataclass
from typing import Callable

from functions.apply_patch_tool import apply_patch
from functions.console_tools import execute_console_command
from functions.file_read_tools import read_file
from functions.file_write_tools import write_file
from functions.rg_tools import rg_list_files, rg_search_text

from .protocol import ProtocolError, RemoteTask


STANDALONE_CAPABILITIES = frozenset(
    {
        "apply_patch",
        "execute_console_command",
        "read_file",
        "rg_list_files",
        "rg_search_text",
        "select_folder",
        "write_file",
    }
)


@dataclass
class _WorkspaceAgent:
    config: dict[str, object]


ToolOperation = Callable[..., str]
FolderPicker = Callable[[str], str]


class StandaloneOperationRegistry:
    """Executes the canonical AgentPark workspace functions for a remote task."""

    def __init__(self, folder_picker: FolderPicker | None = None) -> None:
        self._folder_picker = folder_picker or select_folder
        self._operations: dict[str, ToolOperation] = {
            "apply_patch": apply_patch,
            "execute_console_command": execute_console_command,
            "read_file": read_file,
            "rg_list_files": rg_list_files,
            "rg_search_text": rg_search_text,
            "write_file": write_file,
        }

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(sorted(STANDALONE_CAPABILITIES))

    def execute(self, task: RemoteTask) -> str:
        working_path = validate_working_path(task.working_path)
        if task.tool_name == "select_folder":
            return self._select_folder(task, working_path)
        operation = self._operations.get(task.tool_name)
        if operation is None:
            raise ProtocolError(f"unsupported standalone remote tool: {task.tool_name}")
        arguments = dict(task.arguments)
        if "agent" in arguments:
            raise ProtocolError("tool arguments must not contain the reserved agent field")
        if task.tool_name == "execute_console_command":
            arguments["timeout_seconds"] = task.timeout_seconds
        agent = _WorkspaceAgent(config={"working_path": working_path, "remote_enabled": False})
        result = operation(agent=agent, **arguments)
        if not isinstance(result, str):
            raise ProtocolError(f"remote tool {task.tool_name} returned a non-string result")
        return result

    def _select_folder(self, task: RemoteTask, working_path: str) -> str:
        initial = task.arguments.get("initial_path", working_path)
        if initial is not None and not isinstance(initial, str):
            raise ProtocolError("select_folder initial_path must be a string")
        initial_path = str(initial or "").strip()
        if not initial_path or not os.path.isdir(initial_path):
            initial_path = working_path
        selected = str(self._folder_picker(initial_path) or "").strip()
        if selected:
            selected = os.path.normpath(os.path.abspath(selected))
            if not os.path.isdir(selected):
                raise ProtocolError(f"selected folder does not exist: {selected}")
        return json.dumps({"path": selected}, ensure_ascii=False)


def validate_working_path(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError("Remote WorkingPath must be a non-empty absolute path")
    path = os.path.normpath(value.strip())
    if not (ntpath.isabs(path) or posixpath.isabs(path)):
        raise ProtocolError(f"Remote WorkingPath must be an absolute path: {path}")
    if not os.path.isdir(path):
        raise ProtocolError(f"Remote WorkingPath directory does not exist: {path}")
    return path


def select_folder(initial_path: str) -> str:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return str(
            filedialog.askdirectory(
                parent=root,
                title="Select remote WorkingPath",
                initialdir=initial_path,
                mustexist=True,
            )
            or ""
        )
    finally:
        root.destroy()

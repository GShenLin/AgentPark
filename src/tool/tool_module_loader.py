from __future__ import annotations

import importlib
import importlib.util
import os
import sys

from src.workspace_settings import get_workspace_root


def get_functions_dir() -> str:
    runtime_root = get_workspace_root()
    candidate = os.path.join(runtime_root, "functions")
    if os.path.isdir(candidate):
        return candidate
    meipass = getattr(sys, "_MEIPASS", None)
    if isinstance(meipass, str) and meipass:
        candidate = os.path.join(meipass, "functions")
        if os.path.isdir(candidate):
            return candidate
    return ""


def load_tool_module(tool_name: str):
    module_path = f"functions.{tool_name}"
    try:
        return importlib.import_module(module_path)
    except Exception:
        functions_dir = get_functions_dir()
        if functions_dir:
            file_path = os.path.join(functions_dir, f"{tool_name}.py")
            if os.path.isfile(file_path):
                spec = importlib.util.spec_from_file_location(module_path, file_path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_path] = module
                    spec.loader.exec_module(module)
                    return module
        raise

"""HTTP boundary for the shared toolset registry."""
from fastapi import HTTPException

from src.tool.tool_load_errors import ToolLoadError
from src.tool.toolset_registry import build_catalog, settings_document, validate_toolsets
from src.tool.tool_prompts import prompt_catalog
from src.tool.tool_task_tools import control_declarations


def read_toolsets() -> dict:
    try:
        return settings_document()
    except (OSError, ValueError, ImportError, ToolLoadError) as exc:
        raise HTTPException(status_code=500, detail=f"Unable to read toolsets: {exc}") from exc


def toolset_metadata() -> dict:
    try:
        catalog = build_catalog()
        return {"tool_catalog": catalog["tools"], "builtin_toolsets": list(catalog["defaults"]),
                "tool_prompt_catalog": prompt_catalog(catalog["tools"], list(control_declarations()))}
    except (OSError, ValueError, ImportError, ToolLoadError) as exc:
        raise HTTPException(status_code=500, detail=f"Unable to discover tools: {exc}") from exc


def validate_toolset_settings(payload: object) -> None:
    try:
        validate_toolsets(payload)
    except (ValueError, ImportError, ToolLoadError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

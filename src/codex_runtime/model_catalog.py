from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class CodexModelCatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodexRuntimeModelSelection:
    requested_model: str
    runtime_model: str
    source: str


def resolve_codex_runtime_model(
    request: Callable[..., dict[str, Any]],
    requested_model: str,
    *,
    reasoning_effort: str = "",
) -> CodexRuntimeModelSelection:
    requested = str(requested_model or "").strip()
    if not requested:
        raise ValueError("Codex requested model is required.")

    models = _read_model_catalog(request)
    exact_matches = [
        item
        for item in models
        if requested in {str(item.get("id") or "").strip(), str(item.get("model") or "").strip()}
    ]
    if exact_matches:
        selected = _require_single_runtime_model(exact_matches, label=f"requested model {requested!r}")
        source = "requested"
    else:
        defaults = [item for item in models if item.get("isDefault") is True]
        selected = _require_single_runtime_model(defaults, label="catalog default")
        source = "catalog_default"

    runtime_model = str(selected.get("model") or selected.get("id") or "").strip()
    _validate_reasoning_effort(selected, reasoning_effort)
    return CodexRuntimeModelSelection(
        requested_model=requested,
        runtime_model=runtime_model,
        source=source,
    )


def _read_model_catalog(request: Callable[..., dict[str, Any]]) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    cursor = ""
    seen_cursors: set[str] = set()
    while True:
        params: dict[str, Any] = {"limit": 100, "includeHidden": True}
        if cursor:
            params["cursor"] = cursor
        result = request("model/list", params, timeout=30.0)
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise CodexModelCatalogError("Codex app-server model/list returned invalid model data.")
        models.extend(dict(item) for item in data)
        next_cursor = str(result.get("nextCursor") or "").strip()
        if not next_cursor:
            break
        if next_cursor in seen_cursors:
            raise CodexModelCatalogError("Codex app-server model/list returned a repeated pagination cursor.")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    if not models:
        raise CodexModelCatalogError("Codex app-server model catalog is empty.")
    return models


def _require_single_runtime_model(models: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    runtime_models = {
        str(item.get("model") or item.get("id") or "").strip()
        for item in models
        if str(item.get("model") or item.get("id") or "").strip()
    }
    if len(runtime_models) != 1:
        raise CodexModelCatalogError(
            f"Codex app-server must expose exactly one {label}; found {len(runtime_models)}."
        )
    runtime_model = next(iter(runtime_models))
    return next(
        item
        for item in models
        if str(item.get("model") or item.get("id") or "").strip() == runtime_model
    )


def _validate_reasoning_effort(model: dict[str, Any], reasoning_effort: str) -> None:
    requested_effort = str(reasoning_effort or "").strip()
    if not requested_effort:
        return
    raw_efforts = model.get("supportedReasoningEfforts")
    if not isinstance(raw_efforts, list):
        raise CodexModelCatalogError("Codex app-server model catalog omitted supportedReasoningEfforts.")
    supported = {
        str(item.get("reasoningEffort") or "").strip()
        for item in raw_efforts
        if isinstance(item, dict) and str(item.get("reasoningEffort") or "").strip()
    }
    if requested_effort not in supported:
        runtime_model = str(model.get("model") or model.get("id") or "").strip()
        raise CodexModelCatalogError(
            f"Codex runtime model {runtime_model!r} does not support reasoning effort {requested_effort!r}."
        )


__all__ = [
    "CodexModelCatalogError",
    "CodexRuntimeModelSelection",
    "resolve_codex_runtime_model",
]

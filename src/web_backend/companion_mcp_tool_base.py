from __future__ import annotations

import time
from typing import Any, Callable

from fastapi import HTTPException

from .companion_mcp_errors import companion_error_from_exception


class CompanionMcpToolBase:
    core: object
    config: object
    summary: object
    _summary_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]]

    def _all_graph_ids(self) -> list[str]:
        payload = self.list_graph()
        graph_ids: list[str] = []
        for item in payload.get("graphs") or []:
            if isinstance(item, dict):
                graph_id = self._sanitize_graph_id(item.get("graph_id") or item.get("id"))
                if graph_id:
                    graph_ids.append(graph_id)
        return graph_ids or ["default"]

    def _sanitize_graph_id(self, value: object) -> str:
        return self.core.graph_runtime._sanitize_graph_id(value)

    def _sanitize_node_id(self, value: object) -> str:
        safe = self.core.graph_runtime._sanitize_node_id(value)
        if not safe:
            raise ValueError("node_id is required")
        return safe

    def _with_self_marker(
        self,
        graph_id: str,
        payload: dict[str, Any],
        caller: dict[str, str] | None,
    ) -> dict[str, Any]:
        result = dict(payload)
        result["is_self"] = self._is_self(graph_id, str(result.get("node_id") or ""), caller)
        return result

    def _is_self(self, graph_id: str, node_id: str, caller: dict[str, str] | None) -> bool:
        caller_info = self._caller(caller)
        return bool(
            caller_info["node_id"]
            and self._sanitize_graph_id(graph_id) == caller_info["graph_id"]
            and str(node_id or "").strip() == caller_info["node_id"]
        )

    def _caller(self, caller: dict[str, str] | None) -> dict[str, str]:
        data = caller if isinstance(caller, dict) else {}
        graph_id = self._sanitize_graph_id(data.get("graph_id") or "default")
        node_id = self.core.graph_runtime._sanitize_node_id(data.get("node_id") or "")
        return {"graph_id": graph_id, "node_id": node_id}

    @staticmethod
    def _version() -> str:
        try:
            from importlib.metadata import version

            return version("agentpark")
        except Exception:
            return "0.1.0"

    @staticmethod
    def _domain_call(func: Callable[[], Any]) -> Any:
        try:
            return func()
        except HTTPException as exc:
            return companion_error_from_exception(exc).to_result()
        except Exception as exc:
            return companion_error_from_exception(exc).to_result()

    @staticmethod
    def _ok(payload: object) -> bool:
        return not (isinstance(payload, dict) and payload.get("ok") is False and isinstance(payload.get("error"), dict))

    def _read_node_summary(self, graph_id: str, node_id: str) -> dict[str, Any]:
        key = (self._sanitize_graph_id(graph_id), self._sanitize_node_id(node_id))
        now = time.monotonic()
        cached = self._summary_cache.get(key)
        if cached and cached[0] > now:
            return dict(cached[1])
        payload = self.summary.read_node_summary(key[0], key[1])
        self._summary_cache[key] = (now + self.config.summary_cache_ttl_seconds, dict(payload))
        return payload

    def _invalidate_summary_cache(self, graph_id: str, node_id: str = "") -> None:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        safe_node_id = self.core.graph_runtime._sanitize_node_id(node_id or "")
        for key in list(self._summary_cache):
            if key[0] == safe_graph_id and (not safe_node_id or key[1] == safe_node_id):
                self._summary_cache.pop(key, None)


__all__ = ["CompanionMcpToolBase"]

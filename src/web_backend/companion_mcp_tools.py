from __future__ import annotations

import time
import uuid
from typing import Any

from .companion_mcp_config import read_companion_mcp_config
from .companion_mcp_errors import CompanionError
from .companion_node_summary import CompanionNodeSummarizer
from .companion_mcp_payloads import (
    EDITABLE_NODE_CONFIG_FIELDS,
    completed_request_snapshot,
    delegation_message,
    graph_metadata,
    non_negative_int,
    normalize_seq,
    page_memory_payload,
    poll_interval,
    positive_int,
    stable_self_payload,
    wait_payload,
)
from .companion_mcp_tool_base import CompanionMcpToolBase
from .node_request_tracking import find_completed_request
from .node_state_machine import parse_node_state
from src.workspace_settings import get_workspace_root


class CompanionMcpTools(CompanionMcpToolBase):
    def __init__(self, core: object) -> None:
        self.core = core
        self.summary = CompanionNodeSummarizer(core)
        self.config = read_companion_mcp_config()
        self._summary_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    def list_graph(self) -> dict[str, Any]:
        payload = self._domain_call(lambda: self.core.graph_api.list_graphs())
        if not self._ok(payload):
            return payload
        graphs = []
        for item in payload.get("graphs") or []:
            if not isinstance(item, dict):
                continue
            graph_id = self._sanitize_graph_id(item.get("id") or item.get("graph_id") or "default")
            graph_meta = graph_metadata(self.core, graph_id, self._domain_call)
            graphs.append(
                {
                    "id": graph_id,
                    "graph_id": graph_id,
                    "name": str(item.get("name") or graph_meta.get("name") or graph_id),
                    "description": str(graph_meta.get("description") or ""),
                    "node_count": int(graph_meta.get("node_count") or 0),
                    "state": str(graph_meta.get("state") or "idle"),
                    "updated_at": item.get("updated_at"),
                }
            )
        return {"ok": True, "graphs": graphs, "default_graph_id": "default", "count": len(graphs)}

    def get_companion_meta(self, *, caller: dict[str, str] | None = None) -> dict[str, Any]:
        caller_info = self._caller(caller)
        self_payload = None
        if caller_info["node_id"]:
            try:
                node = self._read_node_summary(caller_info["graph_id"], caller_info["node_id"])
                self_payload = stable_self_payload(self.summary, caller_info["graph_id"], node)
            except Exception:
                self_payload = {
                    "graph_id": caller_info["graph_id"],
                    "node_id": caller_info["node_id"],
                    "available": False,
                }
        return {
            "version": self._version(),
            "default_graph_id": "default",
            "project_root": get_workspace_root(),
            "default_timeout_seconds": self.config.default_timeout_seconds,
            "max_timeout_seconds": self.config.max_timeout_seconds,
            "self": self_payload,
        }

    def list_node(self, *, graph_id: str = "default", caller: dict[str, str] | None = None) -> dict[str, Any]:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        payload = self._domain_call(lambda: self.core.node_ops.list_node_instance_configs(graph_id=safe_graph_id))
        if not self._ok(payload):
            return payload
        nodes = payload.get("nodes")
        if isinstance(nodes, list):
            payload["nodes"] = [
                self._with_self_marker(
                    safe_graph_id,
                    self.summary.enrich_node_summary(safe_graph_id, item),
                    caller,
                )
                for item in nodes
                if isinstance(item, dict)
            ]
        return payload

    def list_node_status(self, *, graph_id: str = "default", caller: dict[str, str] | None = None) -> dict[str, Any]:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        payload = self.list_node(graph_id=safe_graph_id, caller=caller)
        if not self._ok(payload):
            return payload
        nodes = payload.get("nodes") or []
        statuses = [
            self._with_self_marker(
                safe_graph_id,
                self.summary.node_status_payload(safe_graph_id, item),
                caller,
            )
            for item in nodes
            if isinstance(item, dict)
        ]
        return {"graph_id": safe_graph_id, "nodes": statuses, "count": len(statuses)}

    def change_node_config(self, *, graph_id: str = "default", node_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(fields, dict):
            return CompanionError("invalid_request", "fields must be an object").to_result()
        rejected = sorted(str(key) for key in fields if str(key) not in EDITABLE_NODE_CONFIG_FIELDS)
        if rejected:
            return CompanionError(
                "field_not_editable",
                "change_node_config rejected non-editable fields: " + ", ".join(rejected),
                hint="Use list_node_status/list_node to inspect fields; only stable config fields can be changed.",
            ).to_result()
        safe_graph_id = self._sanitize_graph_id(graph_id)
        safe_node_id = self._sanitize_node_id(node_id)
        result = self._domain_call(
            lambda: self.core.node_ops.update_node_instance_config(
                safe_node_id,
                {"fields": dict(fields)},
                graph_id=safe_graph_id,
            )
        )
        self._invalidate_summary_cache(safe_graph_id, safe_node_id)
        return result

    def send_message_to_node(
        self,
        *,
        graph_id: str = "default",
        node_id: str,
        message: str,
        wait_until_idle: bool = True,
        timeout_seconds: float = 120,
        clear_history: bool = False,
        allow_self_recursion: bool = False,
        response_format: dict[str, Any] | str | None = None,
        working_directory: str = "",
        allowed_tools: list[str] | None = None,
        system_prompt_append: str = "",
        caller: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        safe_node_id = self._sanitize_node_id(node_id)
        if not allow_self_recursion and self._is_self(safe_graph_id, safe_node_id, caller):
            return CompanionError(
                "self_recursion_blocked",
                "send_message_to_node target is the calling node; "
                "set allow_self_recursion=true only when recursive self-dispatch is intentional",
                hint="Choose another worker node or explicitly opt into allow_self_recursion.",
            ).to_result()
        request_id = uuid.uuid4().hex
        outbound_message = delegation_message(
            message,
            response_format=response_format,
            working_directory=working_directory,
            allowed_tools=allowed_tools,
            system_prompt_append=system_prompt_append,
        )
        if clear_history:
            cleared = self._domain_call(
                lambda: self.core.node_ops.clear_node_instance_memory(safe_node_id, graph_id=safe_graph_id)
            )
            if not self._ok(cleared):
                return cleared
            self._invalidate_summary_cache(safe_graph_id, safe_node_id)
        return self._domain_call(
            lambda: self._send_and_maybe_wait(
                safe_graph_id,
                safe_node_id,
                outbound_message,
                request_id=request_id,
                wait_until_idle=wait_until_idle,
                timeout_seconds=timeout_seconds,
            )
        )

    def get_node_last_message(
        self,
        *,
        graph_id: str = "default",
        node_id: str,
        wait_until_idle: bool = False,
        timeout_seconds: float = 0,
        since_message_id: str = "",
    ) -> dict[str, Any]:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        safe_node_id = self._sanitize_node_id(node_id)
        return self._wait_for_node(
            safe_graph_id,
            safe_node_id,
            wait_until_idle=wait_until_idle,
            timeout_seconds=timeout_seconds,
            since_message_id=since_message_id,
        )

    def get_node_memory(
        self,
        *,
        graph_id: str = "default",
        node_id: str,
        max_chars: int = 20000,
        start_seq: int = 0,
        offset_chars: int = 0,
    ) -> dict[str, Any]:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        safe_node_id = self._sanitize_node_id(node_id)
        limit = positive_int(max_chars, field="max_chars", default=20000, maximum=200000)
        offset = non_negative_int(offset_chars, field="offset_chars", default=0)
        start = non_negative_int(start_seq, field="start_seq", default=0)
        payload = self._domain_call(
            lambda: self.core.node_ops.get_node_instance_memory(
                safe_node_id,
                max_chars=200000 if offset or start else limit,
                graph_id=safe_graph_id,
            )
        )
        if not self._ok(payload):
            return payload
        return page_memory_payload(payload, max_chars=limit, start_seq=start, offset_chars=offset)

    def stop_node(self, *, graph_id: str, node_id: str, reason: str = "") -> dict[str, Any]:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        safe_node_id = self._sanitize_node_id(node_id)
        before = self._read_node_summary(safe_graph_id, safe_node_id)
        stopped = self._domain_call(
            lambda: self.core.node_ops.control_node_instance(
                safe_node_id,
                {"action": "stop", "reason": str(reason or "")},
                graph_id=safe_graph_id,
            )
        )
        self._invalidate_summary_cache(safe_graph_id, safe_node_id)
        after = self._read_node_summary(safe_graph_id, safe_node_id)
        return {
            "ok": True,
            "graph_id": safe_graph_id,
            "node_id": safe_node_id,
            "reason": str(reason or ""),
            "before": self.summary.node_status_payload(safe_graph_id, before),
            "stop": stopped,
            "after": self.summary.node_status_payload(safe_graph_id, after),
        }

    def get_working_node(self, *, graph_id: str = "", caller: dict[str, str] | None = None) -> dict[str, Any]:
        if str(graph_id or "").strip():
            graph_ids = [self._sanitize_graph_id(graph_id)]
        else:
            graphs_payload = self.list_graph()
            if not self._ok(graphs_payload):
                return graphs_payload
            graph_ids = [
                self._sanitize_graph_id(item.get("graph_id") or item.get("id"))
                for item in graphs_payload.get("graphs") or []
                if isinstance(item, dict)
            ] or ["default"]
        output: list[dict[str, Any]] = []
        for current_graph_id in graph_ids:
            payload = self.list_node(graph_id=current_graph_id, caller=caller)
            if not self._ok(payload):
                return payload
            nodes = payload.get("nodes") or []
            for item in nodes:
                if not isinstance(item, dict):
                    continue
                if parse_node_state(item.get("state")) != "working":
                    continue
                output.append(
                    self._with_self_marker(
                        current_graph_id,
                        self.summary.node_status_payload(current_graph_id, item),
                        caller,
                    )
                )
        return {"nodes": output}

    def _send_and_maybe_wait(
        self,
        graph_id: str,
        node_id: str,
        message: str,
        *,
        request_id: str,
        wait_until_idle: bool,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        before = self._read_node_summary(graph_id, node_id)
        before_message_id = str(before.get("message_id") or "")
        before_seq = int(before.get("node_event_seq") or 0)
        emitted = self.core.graph_api.emit_graph(
            graph_id,
            {"from_id": node_id, "payload": message, "trace_id": request_id},
        )
        self._invalidate_summary_cache(graph_id, node_id)
        result = {"sent": emitted, "graph_id": graph_id, "node_id": node_id, "request_id": request_id}
        if not wait_until_idle:
            result["node"] = self._read_node_summary(graph_id, node_id)
            return result
        result["node"] = self._wait_for_node(
            graph_id,
            node_id,
            wait_until_idle=True,
            timeout_seconds=timeout_seconds,
            since_message_id=before_message_id,
            since_node_event_seq=before_seq,
            request_id=request_id,
        )
        return result

    def _wait_for_node(
        self,
        graph_id: str,
        node_id: str,
        *,
        wait_until_idle: bool,
        timeout_seconds: float,
        since_message_id: str = "",
        since_node_event_seq: int | None = None,
        request_id: str = "",
    ) -> dict[str, Any]:
        timeout = self._timeout_seconds(timeout_seconds)
        started = time.monotonic()
        deadline = time.monotonic() + timeout
        baseline = str(since_message_id or "").strip()
        baseline_seq = normalize_seq(since_node_event_seq)
        if baseline_seq is None and baseline.isdigit():
            baseline_seq = normalize_seq(int(baseline))
        while True:
            current = self._read_node_summary(graph_id, node_id)
            matched_request = find_completed_request(current, request_id)
            if matched_request is not None:
                snapshot = completed_request_snapshot(current, matched_request)
                snapshot["wait"] = wait_payload(
                    started,
                    timeout,
                    True,
                    True,
                    timed_out=False,
                    state=snapshot,
                    request_id=request_id,
                )
                return snapshot
            current_id = str(current.get("message_id") or "")
            current_seq = int(current.get("node_event_seq") or 0)
            idle = self.summary.is_node_idle(current)
            changed = current_seq > baseline_seq if baseline_seq is not None else (not baseline or current_id != baseline)
            if (not wait_until_idle or idle) and changed:
                current["wait"] = wait_payload(
                    started,
                    timeout,
                    idle,
                    changed,
                    timed_out=False,
                    state=current,
                    request_id=request_id,
                )
                return current
            if time.monotonic() >= deadline:
                current["wait"] = wait_payload(
                    started,
                    timeout,
                    idle,
                    changed,
                    timed_out=True,
                    state=current,
                    request_id=request_id,
                )
                return current
            time.sleep(poll_interval(time.monotonic() - started))

    def _timeout_seconds(self, value: object) -> float:
        if value in (None, ""):
            return self.config.default_timeout_seconds
        if isinstance(value, bool):
            raise ValueError("timeout_seconds must be a number")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout_seconds must be a number") from exc
        if parsed < 0:
            raise ValueError("timeout_seconds must be >= 0")
        if parsed <= 0:
            return 0.0
        return min(parsed, self.config.max_timeout_seconds)

__all__ = ["CompanionMcpTools"]

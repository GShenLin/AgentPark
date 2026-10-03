"""Durable agent wakeups delivered through the existing serialized node executor."""
from __future__ import annotations

import os

from src.agent_schedule_store import AgentScheduleStore
from . import runtime_paths, state_store
from .node_state_machine import parse_node_state
from .state_store import NodeDeletingError
from .service_host import HostBoundService
from .shared import build_text_envelope


class AgentScheduleRuntime(HostBoundService):
    def _agent_schedule_store(self) -> AgentScheduleStore:
        return AgentScheduleStore(os.path.join(runtime_paths._get_graphs_dir(), "agent-schedules.sqlite3"))

    def _manage_agent_schedule(self, context: dict, action: str, **params) -> dict:
        if context.get("node_type_id") != "agent_node":
            raise ValueError("Self-scheduling requires a graph Agent node")
        owner = {
            "graph_id": context["graph_id"],
            "node_id": context["node_instance_id"],
            "task_id": context["task_id"],
            "access_metadata": {
                "_access_" + name: str(context.get("access_" + name) or "")
                for name in ("client_id", "username", "role", "ip")
            },
        }
        result = self._agent_schedule_store().manage(owner, action, **params)
        self._scheduled_node_registry().wake()
        return result

    def _poll_agent_schedules(self) -> int:
        store = self._agent_schedule_store()
        count = 0
        for delivery in store.due():
            if delivery["status"] != "pending":
                continue
            try:
                count += self._enqueue_agent_schedule_delivery(store, delivery)
            except NodeDeletingError:
                store.finish(delivery["occurrence_id"], status="cancelled")
            except Exception as exc:
                # A corrupt/deleting node must not starve unrelated schedules.
                self._log_graph_event(delivery["graph_id"], "agent_schedule_delivery_failed",
                                      node_id=delivery["node_id"], schedule_id=delivery["schedule_id"],
                                      error=f"{type(exc).__name__}: {exc}")
        return count

    def _enqueue_agent_schedule_delivery(self, store, delivery: dict) -> int:
        graph_id, node_id = delivery["graph_id"], delivery["node_id"]
        # Targets are bound at creation, never accepted from model arguments.
        config_path = self._node_config_path(node_id, graph_id)
        cfg = state_store._read_json_dict(config_path) if os.path.isfile(config_path) else {}
        if cfg.get("type_id") != "agent_node":
            store.finish(delivery["occurrence_id"], status="failed")
            self._log_graph_event(graph_id, "agent_schedule_target_missing", node_id=node_id,
                                  schedule_id=delivery["schedule_id"])
            return 0
        if cfg.get("_delete_requested"):
            store.finish(delivery["occurrence_id"], status="cancelled")
            return 0
        if parse_node_state(cfg.get("state")) == "stop" or cfg.get("_stop_requested"):
            return 0
        occurrence_id = delivery["occurrence_id"]
        item = {
            "payload": build_text_envelope(delivery["prompt"], role="user"),
            "depth": 0, "visited": [], "trace_id": occurrence_id,
            "idempotency_key": occurrence_id, "from": node_id,
            "source": "agent_schedule", "_agent_schedule_occurrence": occurrence_id,
            "_runtime_owner_id": getattr(self.core, "runtime_owner_id", ""),
            **delivery["access_metadata"],
        }
        appended = state_store._append_node_pending(config_path, item)
        self._ensure_graph_runner(graph_id)
        self._wake_graph_runner(graph_id)
        return int(appended)

    def _run_node_with_agent_schedule(self, **kwargs) -> None:
        item = kwargs["pending_item"]
        if item.get("source") != "agent_schedule":
            self._run_single_node_iteration(**kwargs)
            return
        store = self._agent_schedule_store()
        occurrence_id = str(item.get("_agent_schedule_occurrence") or "")
        delivery = store.begin(occurrence_id, kwargs["safe_graph_id"], kwargs["entry"])
        config_path = kwargs["config_path"]
        if delivery is None:
            # A queued occurrence may have been cancelled/updated before dequeue.
            state_store._set_node_config_inflight(config_path, None)
            state_store._transition_node_config_to_idle(config_path)
            return
        try:
            cfg = state_store._read_json_dict(config_path) if os.path.isfile(config_path) else {}
            if cfg.get("type_id") != "agent_node":
                store.finish(occurrence_id, status="failed")
                state_store._set_node_config_inflight(config_path, None)
                state_store._transition_node_config_to_idle(config_path)
                return
            # Restore task identity from the durable record, not queue metadata.
            item["_agent_schedule_task_id"] = delivery["task_id"]
            item["payload"] = build_text_envelope(delivery["prompt"], role="user")
            for key, value in delivery["access_metadata"].items():
                item[key] = value
            self._run_single_node_iteration(**kwargs)
        except Exception:
            store.finish(occurrence_id, status="failed")
            raise
        else:
            # The execution method sets this only after output persistence.
            store.finish(occurrence_id, status=item.get("_agent_schedule_result", "failed"))

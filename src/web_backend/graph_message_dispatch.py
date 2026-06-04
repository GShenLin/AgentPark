import os
import uuid

from . import runtime_paths, state_store
from .service_host import HostBoundService
from .shared import _append_node_pending, _parse_node_state, envelope_preview, normalize_envelope
from .route_parser import NodeRouteParser


class GraphMessageDispatch(HostBoundService):
    def _build_outgoing_links_map(self, graph_cfg: dict) -> dict[str, list[dict]]:
        links_raw = graph_cfg.get("links") if isinstance(graph_cfg, dict) else None
        outgoing: dict[str, list[dict]] = {}
        if not isinstance(links_raw, list):
            return outgoing

        for link in links_raw:
            if not isinstance(link, dict):
                continue
            frm_raw = link.get("from")
            to_raw = link.get("to")
            frm = ""
            to = ""
            from_output_index = 0
            to_input_index = 0
            if isinstance(frm_raw, dict):
                frm = str(frm_raw.get("node") or "").strip()
                parsed = NodeRouteParser.parse_port_index(frm_raw.get("index"))
                if parsed is not None:
                    from_output_index = parsed
            else:
                frm = str(frm_raw or "").strip()
            if isinstance(to_raw, dict):
                to = str(to_raw.get("node") or "").strip()
                parsed = NodeRouteParser.parse_port_index(to_raw.get("index"))
                if parsed is not None:
                    to_input_index = parsed
            else:
                to = str(to_raw or "").strip()
            lid = str(link.get("id") or "").strip()
            if frm and to:
                outgoing.setdefault(frm, []).append(
                    {
                        "id": lid,
                        "to": to,
                        "from_output_index": from_output_index,
                        "to_input_index": to_input_index,
                    }
                )
        return outgoing

    def _collect_event_dispatch_tasks(
        self,
        source_graph_id: str,
        source_node_id: str,
        event_key: str,
        route_payload: object,
        trace_id: str,
        next_visited: list[str],
    ) -> list[dict]:
        event_key_text = str(event_key or "").strip()
        if not event_key_text:
            return []

        graphs_dir = runtime_paths._get_graphs_dir()
        graph_ids: list[str] = []
        if graphs_dir and os.path.isdir(graphs_dir):
            for entry in os.listdir(graphs_dir):
                graph_dir = os.path.join(graphs_dir, entry)
                if not os.path.isdir(graph_dir):
                    continue
                safe_entry = self._sanitize_graph_id(entry)
                if safe_entry and safe_entry not in graph_ids:
                    graph_ids.append(safe_entry)
        if self.default_graph_id not in graph_ids:
            graph_ids.append(self.default_graph_id)

        tasks: list[dict] = []
        for target_graph_id in graph_ids:
            target_graph_cfg = self._read_graph_config(target_graph_id)
            target_outgoing = self._build_outgoing_links_map(target_graph_cfg)
            if not target_outgoing:
                continue

            target_base_dir = self._graph_dir(target_graph_id)
            if not target_base_dir or not os.path.isdir(target_base_dir):
                continue

            for event_node_id in os.listdir(target_base_dir):
                if event_node_id == "agents":
                    continue
                node_dir = os.path.join(target_base_dir, event_node_id)
                if not os.path.isdir(node_dir):
                    continue
                cfg_path = os.path.join(node_dir, "config.json")
                if not os.path.exists(cfg_path):
                    continue
                cfg = state_store._read_json_dict(cfg_path)
                if not isinstance(cfg, dict) or not cfg:
                    continue
                cfg_type_id = str(cfg.get("type_id") or "").strip()
                matched = False
                if cfg_type_id == "event_node":
                    matched = str(cfg.get("EventKey") or "").strip() == event_key_text
                if not matched or (target_graph_id == source_graph_id and event_node_id == source_node_id):
                    continue
                if _parse_node_state(cfg.get("state")) == "stop":
                    continue

                for link in target_outgoing.get(event_node_id, []):
                    to_id = str((link or {}).get("to") or "").strip()
                    if not to_id:
                        continue
                    route_output_index = NodeRouteParser.parse_port_index((link or {}).get("from_output_index"))
                    if route_output_index is None:
                        route_output_index = 0
                    to_input_index = NodeRouteParser.parse_port_index((link or {}).get("to_input_index"))
                    if to_input_index is None:
                        to_input_index = 0

                    target_cfg_path = self._node_config_path(to_id, target_graph_id)
                    if not target_cfg_path or not os.path.exists(target_cfg_path):
                        self._log_graph_event(
                            source_graph_id,
                            "event_dispatch_missing_target",
                            trace_id=trace_id,
                            event_key=event_key_text,
                            event_graph_id=target_graph_id,
                            event_node_id=event_node_id,
                            to_node=to_id,
                        )
                        continue

                    target_cfg = state_store._read_json_dict(target_cfg_path)
                    if isinstance(target_cfg, dict) and _parse_node_state(target_cfg.get("state")) == "stop":
                        self._log_graph_event(
                            source_graph_id,
                            "event_dispatch_skip_target_stopped",
                            trace_id=trace_id,
                            event_key=event_key_text,
                            event_graph_id=target_graph_id,
                            event_node_id=event_node_id,
                            to_node=to_id,
                        )
                        continue

                    tasks.append(
                        {
                            "target_graph_id": target_graph_id,
                            "target_cfg_path": target_cfg_path,
                            "to_id": to_id,
                            "from_node": event_node_id,
                            "route_output_index": route_output_index,
                            "to_input_index": to_input_index,
                            "next_depth": max(1, len(next_visited)),
                            "route_payload": route_payload,
                            "link_id": str((link or {}).get("id") or "").strip(),
                            "next_visited": (next_visited + [f"{target_graph_id}:{event_node_id}"])[-50:],
                            "source": "event_dispatch",
                            "event_key": event_key_text,
                            "event_graph_id": target_graph_id,
                            "event_node_id": event_node_id,
                        }
                    )
        return tasks

    def _parse_pending_node_item(self, item: dict) -> tuple[dict, str, str, int, int, str, int, list[str]]:
        message = normalize_envelope(item.get("payload"), default_role="user")
        trace_id = str(item.get("trace_id") or "").strip() or uuid.uuid4().hex
        link_id = str(item.get("link_id") or "").strip()
        from_output_index = NodeRouteParser.parse_port_index(item.get("from_output_index"))
        if from_output_index is None:
            from_output_index = 0
        to_input_index = NodeRouteParser.parse_port_index(item.get("to_input_index"))
        if to_input_index is None:
            to_input_index = 0
        source = str(item.get("source") or "").strip()
        try:
            depth = int(float(item.get("depth") or 0))
        except Exception:
            depth = 0
        visited_raw = item.get("visited")
        visited = [str(v) for v in visited_raw if v is not None] if isinstance(visited_raw, list) else []
        return message, trace_id, link_id, from_output_index, to_input_index, source, depth, visited

    def _enqueue_graph_task(
        self,
        task: dict,
        safe_graph_id: str,
        default_from_node: str,
        trace_id: str,
        next_visited: list[str],
        wake_event,
    ) -> None:
        target_graph_id = self._sanitize_graph_id(task.get("target_graph_id") or safe_graph_id)
        from_node_for_task = str(task.get("from_node") or default_from_node).strip() or default_from_node
        task_visited = task.get("next_visited")
        if isinstance(task_visited, list):
            visited_for_task = [str(v) for v in task_visited if v is not None][-50:]
        else:
            visited_for_task = next_visited
        next_item = {
            "payload": normalize_envelope(task["route_payload"], default_role="assistant"),
            "trace_id": trace_id,
            "depth": task["next_depth"],
            "visited": visited_for_task,
            "from": from_node_for_task,
            "from_output_index": task["route_output_index"],
            "to_input_index": task["to_input_index"],
            "source": str(task.get("source") or "propagate"),
        }
        link_id = str(task.get("link_id") or "")
        if link_id:
            next_item["link_id"] = link_id
        _append_node_pending(task["target_cfg_path"], next_item)
        self._ensure_graph_runner(target_graph_id)
        if target_graph_id == safe_graph_id:
            wake_event.set()
        else:
            self._wake_graph_runner(target_graph_id)
        event_key_for_task = str(task.get("event_key") or "").strip()
        self._log_graph_event(
            safe_graph_id,
            "event_dispatch_enqueue" if event_key_for_task else "propagate_enqueue",
            trace_id=trace_id,
            from_node=from_node_for_task,
            to_node=task["to_id"],
            target_graph_id=target_graph_id,
            link_id=link_id or None,
            from_output_index=task["route_output_index"],
            to_input_index=task["to_input_index"],
            depth=task["next_depth"],
            payload_preview=state_store._preview_text(envelope_preview(task["route_payload"])),
            event_key=event_key_for_task or None,
            event_graph_id=str(task.get("event_graph_id") or "").strip() or None,
            event_node_id=str(task.get("event_node_id") or "").strip() or None,
        )

from __future__ import annotations

from .node_config_service import read_node_config_optional
from .node_event_sequence import bump_node_event_seq
from .node_state_machine import parse_node_state
from .runtime_state_memory_store import runtime_state_memory_store


class NodeOutputHoldStore:
    def complete_work(self, config_path: str, held_output: dict) -> tuple[str, int]:
        if not config_path:
            return "idle", 0
        cfg = read_node_config_optional(config_path)
        type_id = str((cfg or {}).get("type_id") or "").strip()
        final_state = "idle"
        held_count = 0

        def mutate(payload: dict) -> None:
            nonlocal final_state, held_count
            if bool(payload.get("_delete_requested")):
                final_state = "stop"
            else:
                current_state = parse_node_state(payload.get("state"))
                if current_state == "stop":
                    final_state = "stop"
                elif type_id == "clock_node" and bool(payload.get("_clock_running")):
                    final_state = "working"
                else:
                    final_state = "idle"
            if parse_node_state(payload.get("state")) != final_state:
                bump_node_event_seq(payload)
            payload["state"] = final_state
            payload.pop("_stop_requested", None)
            if final_state != "stop" or not isinstance(held_output, dict) or not held_output:
                return
            held_outputs = payload.get("held_outputs")
            if held_outputs is None:
                held_outputs = []
            if not isinstance(held_outputs, list):
                raise RuntimeError("runtime state field held_outputs must be a list")
            held_outputs.append(held_output)
            payload["held_outputs"] = held_outputs
            held_count = len(held_outputs)
            bump_node_event_seq(payload)

        runtime_state_memory_store.update(config_path, mutate)
        return final_state, held_count

    def resume(self, config_path: str) -> list[dict]:
        if not config_path:
            return []
        released: list[dict] = []

        def mutate(payload: dict) -> None:
            nonlocal released
            if bool(payload.get("_delete_requested")):
                return
            held_outputs = payload.get("held_outputs")
            if isinstance(held_outputs, list):
                released = [item for item in held_outputs if isinstance(item, dict)]
            payload.pop("held_outputs", None)
            if parse_node_state(payload.get("state")) != "idle" or released:
                bump_node_event_seq(payload)
            payload["state"] = "idle"
            payload.pop("_stop_requested", None)

        runtime_state_memory_store.update(config_path, mutate)
        return released


node_output_hold_store = NodeOutputHoldStore()

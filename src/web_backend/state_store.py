import json
import os
from src.file_transaction import append_text, run_with_interprocess_lock
from .node_config_store import NodeConfigStore, NodeDeletingError
from .node_output_hold_store import node_output_hold_store


def _preview_text(value: object, limit: int = 260) -> str:
    raw = "" if value is None else str(value)
    compact = raw.replace("\r", " ").replace("\n", " ")
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "…"


def _append_jsonl_line(file_path: str, payload: dict) -> None:
    if not file_path:
        return
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    run_with_interprocess_lock(
        file_path + ".lock",
        lambda: append_text(file_path, line, encoding="utf-8"),
    )


_NODE_CONFIG_STORE = NodeConfigStore()


def _read_json_dict(file_path: str) -> dict:
    return _NODE_CONFIG_STORE.read(file_path)


def _write_json_dict(file_path: str, data: dict) -> bool:
    return _NODE_CONFIG_STORE.write(file_path, data)


def _patch_node_config_persistent_fields(config_path: str, fields: dict) -> dict:
    return _NODE_CONFIG_STORE.patch_persistent_fields(config_path, fields)


def _update_node_config_state(config_path: str, state: str) -> None:
    _NODE_CONFIG_STORE.update_state(config_path, state)


def _transition_node_config_to_idle(config_path: str) -> None:
    _NODE_CONFIG_STORE.transition_to_idle(config_path)


def _complete_node_config_work_with_held_output(config_path: str, item: dict) -> tuple[str, int]:
    return node_output_hold_store.complete_work(config_path, item)


def _resume_node_config_with_held_outputs(config_path: str) -> list[dict]:
    return node_output_hold_store.resume(config_path)


def _append_node_pending(config_path: str, item: dict) -> None:
    _NODE_CONFIG_STORE.append_pending(config_path, item)


def _pop_node_pending(config_path: str) -> dict | None:
    return _NODE_CONFIG_STORE.pop_pending(config_path)


def _cancel_node_work(config_path: str) -> dict:
    return _NODE_CONFIG_STORE.cancel_work(config_path)


def _mark_node_delete_requested(config_path: str) -> dict:
    return _NODE_CONFIG_STORE.mark_delete_requested(config_path)


def _is_node_stop_requested(config_path: str) -> bool:
    return _NODE_CONFIG_STORE.is_stop_requested(config_path)


def _finish_node_stop_requested(config_path: str, message: str = "Stopped.") -> bool:
    return _NODE_CONFIG_STORE.finish_stop_requested(config_path, message=message)


def _dequeue_node_pending_to_working(config_path: str, runtime_owner_id: str | None = None) -> dict | None:
    return _NODE_CONFIG_STORE.dequeue_pending_to_working(config_path, runtime_owner_id=runtime_owner_id)


def _consume_node_mid_turn_user_inputs(config_path: str, limit: int = 16) -> list[dict]:
    return _NODE_CONFIG_STORE.consume_mid_turn_user_inputs(config_path, limit=limit)


def _set_node_config_last_message(config_path: str, output: str) -> None:
    _NODE_CONFIG_STORE.set_last_message(config_path, output)


def _set_node_config_runtime_event(config_path: str, event: dict | None, *, reset_history: bool = False) -> None:
    _NODE_CONFIG_STORE.set_runtime_event(config_path, event, reset_history=reset_history)


def _touch_node_config_last_run_at(config_path: str, run_at: str | None = None) -> None:
    _NODE_CONFIG_STORE.touch_last_run_at(config_path, run_at)


def _set_node_config_inflight(config_path: str, item: dict | None) -> None:
    _NODE_CONFIG_STORE.set_inflight(config_path, item)


def _recover_node_config_inflight(config_path: str) -> bool:
    return _NODE_CONFIG_STORE.recover_inflight_to_pending(config_path)


def _recover_node_config_startup_state(config_path: str) -> dict:
    return _NODE_CONFIG_STORE.recover_startup_runtime_state(config_path)


def _recover_node_config_stale_working(config_path: str, stale_seconds: int = 120) -> dict:
    return _NODE_CONFIG_STORE.recover_stale_working(config_path, stale_seconds=stale_seconds)

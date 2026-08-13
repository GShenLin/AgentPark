from __future__ import annotations

import json


def render_restart_recovery_context(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    model_state = value.get("model_state")
    if not isinstance(model_state, dict):
        return ""
    restart_id = str(value.get("restart_id") or "").strip()
    graph_id = str(value.get("graph_id") or "").strip()
    node_id = str(value.get("node_id") or "").strip()
    if not restart_id or not graph_id or not node_id:
        return ""
    return (
        "AgentPark restart recovery context. The service restarted while this node was working. "
        "Continue the interrupted task from the durable conversation and task ledger. Treat the current user "
        "message as the original interrupted input, do not repeat work already proven complete, and verify the "
        "remaining work before replying. The following state was captured immediately before restart:\n"
        + json.dumps(model_state, ensure_ascii=False, indent=2, sort_keys=True)
    )


__all__ = ["render_restart_recovery_context"]

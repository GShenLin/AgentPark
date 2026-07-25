RUNTIME_STATE_FILENAME = "runtime_state.json"

RUNTIME_STATE_DEFAULTS = {
    "state": "idle",
    "pending_count": 0,
    "node_event_seq": 0,
}

# Event and field-scoped API projections are merged into an existing client
# snapshot. Optional flags therefore need explicit tombstones when absent from
# the in-memory store; omitting them would preserve stale client values.
RUNTIME_PROJECTION_DEFAULTS = {
    **RUNTIME_STATE_DEFAULTS,
    "inflight": None,
    "_stop_requested": False,
}

RUNTIME_STATE_FIELDS = {
    "state",
    "pending",
    "pending_count",
    "held_outputs",
    "inflight",
    "inflight_at",
    "_stop_requested",
    "_delete_requested",
    "node_event_seq",
    "last_message",
    "last_run_at",
    "last_runtime_event",
    "runtime_events",
    "runtime_tool_calls",
    "provider_request_summaries",
    "provider_request_totals",
    "completed_requests",
    "last_completed_request",
    "goal",
    "goal_state",
    "_clock_running",
    "_clock_next_fire_at",
    "_clock_remaining_seconds",
    "_clock_trigger_count",
}

NODE_EVENT_RUNTIME_FIELDS = {
    "state",
    "pending_count",
    "inflight",
    "_stop_requested",
    "node_event_seq",
    "last_run_at",
    "goal",
    "goal_state",
    "provider_request_totals",
}

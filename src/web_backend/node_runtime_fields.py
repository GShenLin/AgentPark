RUNTIME_STATE_FILENAME = "runtime_state.json"

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
    "_stop_requested",
    "node_event_seq",
    "last_run_at",
    "goal",
    "goal_state",
    "provider_request_totals",
}

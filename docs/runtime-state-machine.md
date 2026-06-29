# Runtime State Machine

Node runtime state is persisted in each node config file under:

```text
memories/<graph_id>/<node_id>/config.json
```

The persisted node states are:

- `idle`: the runner may dequeue pending work.
- `working`: a node has active work, represented by `inflight`.
- `stop`: user-held stop state; startup recovery must not rewrite it.

Runtime control fields:

- `pending`: queued work items.
- `pending_count`: derived from `pending`.
- `inflight`: the work item currently owned by a runner.
- `_stop_requested`: active cancellation flag for a running `inflight`.

## Recovery Rules

Startup recovery uses `src.web_backend.node_state_machine` and logs `startup_node_state_recovered` graph events with `before_state`, `after_state`, `reason`, `inflight_requeued`, and `pending_count`.

Rules:

- `stop` is preserved, including `pending`, `inflight`, and `_stop_requested`.
- `working` with `inflight` requeues `inflight` to the front of `pending`, clears `inflight`, clears `_stop_requested`, and returns to `idle`.
- `working` without `inflight` returns to `idle` and preserves `pending`.
- `idle` with stale `inflight` requeues `inflight` to `pending` and stays runnable.
- Clock nodes with `_clock_running` and no `inflight` stay `working`.

During runner polling, stale `working` nodes without `inflight` return to `idle` and preserve `pending`; `working` nodes with `inflight` are not requeued by timeout because the active operation may still be running.

## Stop Semantics

Stopping a non-clock node:

- clears `pending`;
- if `inflight` exists, keeps state `working`, sets `_stop_requested`, and asks the active cancellation registry to cancel;
- if no `inflight` exists, clears runtime work fields and returns to `idle`.

Successful cancellation clears `inflight`, clears `_stop_requested`, returns to `idle`, and writes a final stopped message.

Capability changes such as disabling tools, MCP servers, skills, or plugins use `effective: "next_agent_run"` and do not mutate an already-running `inflight`.

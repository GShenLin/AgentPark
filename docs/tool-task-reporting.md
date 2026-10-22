# Tool task reporting

AgentPark reporting deadlines are non-destructive. Built-in, plugin and MCP calls
share the same Agent-owned task registry. A tool is invoked exactly once. When
the first reporting interval expires, the model receives `status: running`, a
`task_id`, elapsed time, cancellation state and available progress. Exceptions
and completed results retain their existing result contracts.

The three task controls are always registered:

| Tool | Behavior |
|---|---|
| `read_tool_task(task_id)` | Return state or the final result immediately. |
| `wait_tool_task(task_id, wait_seconds)` | The model chooses 0–3600 seconds until the next report. Return early if execution finishes. |
| `stop_tool_task(task_id)` | Explicitly request cancellation; a running response means cancellation has not completed. |

`wait_seconds` and the UTC `next_report_at` timestamp record the interval chosen
for that wait. They are a blocking wait/report contract, not a scheduled future
Agent turn. After a running response, the model must choose another wait or stop.
Repeating the original invocation would create a second operation and must not be
used as continuation.

Existing `toolExecutionTimeout*` and tool-specific timeout settings now control
reporting. Zero disables the timed report, not explicit cancellation. Console
command and pytest no-progress budgets publish progress instead of killing the
process. Console sessions retain their session IDs and cursor tools; their
`timeout_seconds` is only a suggested reporting interval. Running snapshots also
include the latest output tails, separate from the lossless cursor stream.

Workspace programs remain a single task. Reporting does not complete a stage:
dependent stages and result references wait for actual completion. Remote
execution uses explicit `execute`/`wait` requests with the same task ID; a report
does not dequeue or cancel work. Both remote hosts and workers must run the new
version. Scan, skill-script and curl CLI execution also use soft reporting.

Parallel dispatch has no second batch deadline that discards running tasks.
`ask_user.timeout_sec` reports pending input without expiring the dialog. Native
desktop operations retain their serialization lock while reporting; do not repeat
an input action before reading its final result. MCP `readTimeoutSeconds` controls
tool reporting, with no local session/stream read deadline during `tools/call`.
Discovery and connection failures remain errors.

Explicit node/call Stop, explicit task cancellation, process failure and Agent
run cleanup remain terminal. Tasks and console sessions are scoped to a running
Agent invocation; they do not survive normal run completion, provider failure or
server restart. Models must keep waiting while the requested work is unfinished.
Device switching stays blocked while a background tool owns the execution device.

Transport connection failures, third-party service deadlines, command flags such
as a user-supplied `curl --max-time`, and resource limits remain real failures.
AgentPark does not replay side effects after such failures or claim that a remote
service can be kept alive after that service ends its request.

Validation covers reporting without cancellation, exactly-once invocation,
selected wait intervals, final output, explicit stop, workspace dependencies,
remote task polling and retained console output.

See [the per-tool timer audit](tool-timeout-audit.md) for the checked inventory,
remaining SDK/request limits, and live integration verification gaps.

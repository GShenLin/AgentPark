# Tool timer audit (2026-10-21)

This is a source-level inventory of this checkout, not a claim that every tool was exercised against its real service. The built-in catalog has 53 callable references (52 distinct names: the two apply_patch contracts are separate). Three task controls are installed separately. Plugin and local script inventories are below. Dynamic MCP servers and future extensions cannot be certified by this snapshot.

## Contract and fixes

Execution/reporting deadlines must return an owned running task without cancelling or replaying its operation. The model chooses the next wait_seconds; the result records next_report_at. Completion, explicit cancellation and run cleanup remain distinct terminal events.

The follow-up audit found and fixed: the parallel dispatcher's 20-second failure deadline; MCP session/stream read deadlines during tools/call; ask_user expiry and the UI countdown; native capture/activation/UIA deadlines and UIA context propagation; remote workspace inspection failing to wait for a running response. Obsolete console timeout-result code was removed.

## Built-in exports, checked individually

For the rows without an independent execution timer, the common ToolTask tests verify reporting/exactly-once execution; that is not an individual live integration test.

| Export | Timer behavior / boundary | Evidence |
|---|---|---|
| `skill_activation_tools:activate_skill` | 60-second report interval; MCP discovery can fail independently before a remote tool starts. | Tool/skill tests |
| `computer_use_tools:activate_window` | Native calls report; capture, activation and UIA timers preserve the operation. Observation freshness and size limits remain. | Native adapter + service tests; no live desktop exercise |
| `node_memory_tools:add_node_memory_note` | Common task reports; SQLite lock acquisition limits remain. | Code review + common task tests |
| `agent_patch_tools:apply_patch` | No independent execution deadline found in the entry point/dependencies inspected; common task reporting applies. File/DB resource limits remain. | Code review + common task tests |
| `apply_patch_tool:apply_patch` | No independent execution deadline found in the entry point/dependencies inspected; common task reporting applies. File/DB resource limits remain. | Code review + common task tests |
| `user_interaction_tools:ask_user` | ask_user reports at timeout_sec and keeps one dialog pending; tips returns immediately. | Real store/thread lifecycle tests |
| `computer_use_tools:click` | Native calls report; capture, activation and UIA timers preserve the operation. Observation freshness and size limits remain. | Native adapter + service tests; no live desktop exercise |
| `cron_tools:cron_create` | Common task reports; schedule times and SQLite lock limits are not execution deadlines. | Code review + common task tests |
| `cron_tools:cron_delete` | Common task reports; schedule times and SQLite lock limits are not execution deadlines. | Code review + common task tests |
| `cron_tools:cron_list` | Common task reports; schedule times and SQLite lock limits are not execution deadlines. | Code review + common task tests |
| `cron_tools:cron_update` | Common task reports; schedule times and SQLite lock limits are not execution deadlines. | Code review + common task tests |
| `skill_activation_tools:deactivate_skill` | 60-second report interval; MCP discovery can fail independently before a remote tool starts. | Tool/skill tests |
| `computer_use_tools:drag` | Native calls report; capture, activation and UIA timers preserve the operation. Observation freshness and size limits remain. | Native adapter + service tests; no live desktop exercise |
| `console_tools:execute_console_command` | Command and no-progress intervals publish status; process continues. | Real subprocess + watchdog tests |
| `curl_tools:execute_curl_command` | CLI reporting interval does not inject --max-time or kill curl. Explicit command flags still apply. | CLI adapter tests; no live download |
| `analysis_tools:finalize_analysis_report` | No independent execution deadline found in the entry point/dependencies inspected; common task reporting applies. File/DB resource limits remain. | Code review + common task tests |
| `node_memory_tools:forget_node_memory` | Common task reports; SQLite lock acquisition limits remain. | Code review + common task tests |
| `analysis_tools:get_task_direction` | No independent execution deadline found in the entry point/dependencies inspected; common task reporting applies. File/DB resource limits remain. | Code review + common task tests |
| `computer_use_tools:get_window` | Native calls report; capture, activation and UIA timers preserve the operation. Observation freshness and size limits remain. | Native adapter + service tests; no live desktop exercise |
| `computer_use_tools:get_window_state` | Native calls report; capture, activation and UIA timers preserve the operation. Observation freshness and size limits remain. | Native adapter + service tests; no live desktop exercise |
| `execution_device_tools:inspect_execution_workspace` | Inspection polls the same remote task; switching waits for its final result. Catalog/connect failures remain errors. | Device + mocked remote polling tests |
| `computer_use_tools:launch_app` | Native calls report; capture, activation and UIA timers preserve the operation. Observation freshness and size limits remain. | Native adapter + service tests; no live desktop exercise |
| `computer_use_tools:list_apps` | Native calls report; capture, activation and UIA timers preserve the operation. Observation freshness and size limits remain. | Native adapter + service tests; no live desktop exercise |
| `execution_device_tools:list_execution_devices` | Inspection polls the same remote task; switching waits for its final result. Catalog/connect failures remain errors. | Device + mocked remote polling tests |
| `peer_network_tools:list_peer_devices` | Common task reports; HTTP/RPC delivery budgets remain bounded and may return uncertain delivery errors. | Code review |
| `skill_resource_tools:list_skill_resources` | No independent execution deadline found in the entry point/dependencies inspected; common task reporting applies. File/DB resource limits remain. | Code review + common task tests |
| `computer_use_tools:list_windows` | Native calls report; capture, activation and UIA timers preserve the operation. Observation freshness and size limits remain. | Native adapter + service tests; no live desktop exercise |
| `capability_management_tools:manage_agent_capabilities` | Common task reports; discovery/cache/connection limits remain. | Code review + common task tests |
| `peer_network_tools:peer_request` | Common task reports; HTTP/RPC delivery budgets remain bounded and may return uncertain delivery errors. | Code review |
| `computer_use_tools:perform_secondary_action` | Native calls report; capture, activation and UIA timers preserve the operation. Observation freshness and size limits remain. | Native adapter + service tests; no live desktop exercise |
| `computer_use_tools:press_key` | Native calls report; capture, activation and UIA timers preserve the operation. Observation freshness and size limits remain. | Native adapter + service tests; no live desktop exercise |
| `console_session_tools:read_console_session` | start/read return immediately; wait reports at the chosen interval; only stop explicitly terminates. | Real subprocess session tests |
| `file_read_tools:read_file` | No independent execution deadline found in the entry point/dependencies inspected; common task reporting applies. File/DB resource limits remain. | Code review + common task tests |
| `node_memory_tools:read_node_memory` | Common task reports; SQLite lock acquisition limits remain. | Code review + common task tests |
| `skill_resource_tools:read_skill_resource` | No independent execution deadline found in the entry point/dependencies inspected; common task reporting applies. File/DB resource limits remain. | Code review + common task tests |
| `analysis_tools:replace_task_direction` | No independent execution deadline found in the entry point/dependencies inspected; common task reporting applies. File/DB resource limits remain. | Code review + common task tests |
| `rg_tools:rg_list_files` | Native rg and Python scan deadlines report; result-count limits may end a bounded search. | Search tests |
| `rg_tools:rg_search_text` | Native rg and Python scan deadlines report; result-count limits may end a bounded search. | Search tests |
| `analysis_tools:run_analysis_verification` | Nested commands report through the owning task; dependent stages/gates wait for actual completion. | Code review of console delegation |
| `computer_use_tools:scroll` | Native calls report; capture, activation and UIA timers preserve the operation. Observation freshness and size limits remain. | Native adapter + service tests; no live desktop exercise |
| `memory_tools:search_memory` | No independent execution deadline found in the entry point/dependencies inspected; common task reporting applies. File/DB resource limits remain. | Code review + common task tests |
| `node_memory_tools:search_node_memory` | Common task reports; SQLite lock acquisition limits remain. | Code review + common task tests |
| `computer_use_tools:set_value` | Native calls report; capture, activation and UIA timers preserve the operation. Observation freshness and size limits remain. | Native adapter + service tests; no live desktop exercise |
| `console_session_tools:start_console_session` | start/read return immediately; wait reports at the chosen interval; only stop explicitly terminates. | Real subprocess session tests |
| `console_session_tools:stop_console_session` | start/read return immediately; wait reports at the chosen interval; only stop explicitly terminates. | Real subprocess session tests |
| `execution_device_tools:switch_execution_device` | Inspection polls the same remote task; switching waits for its final result. Catalog/connect failures remain errors. | Device + mocked remote polling tests |
| `user_interaction_tools:tips` | ask_user reports at timeout_sec and keeps one dialog pending; tips returns immediately. | Real store/thread lifecycle tests |
| `computer_use_tools:type_text` | Native calls report; capture, activation and UIA timers preserve the operation. Observation freshness and size limits remain. | Native adapter + service tests; no live desktop exercise |
| `analysis_tools:update_task_direction` | No independent execution deadline found in the entry point/dependencies inspected; common task reporting applies. File/DB resource limits remain. | Code review + common task tests |
| `image_tools:view_image` | No independent execution deadline found in the entry point/dependencies inspected; common task reporting applies. File/DB resource limits remain. | Code review + common task tests |
| `console_session_tools:wait_console_session` | start/read return immediately; wait reports at the chosen interval; only stop explicitly terminates. | Real subprocess session tests |
| `system_tools:workspace_exec` | Nested commands report through the owning task; dependent stages/gates wait for actual completion. | Workspace dependency tests |
| `file_write_tools:write_file` | No independent execution deadline found in the entry point/dependencies inspected; common task reporting applies. File/DB resource limits remain. | Code review + common task tests |

## Always-present controls

| Tool | Timer behavior |
|---|---|
| `read_tool_task` | No waiting; current state or final result. |
| `wait_tool_task` | Model-selected 0–3600 seconds; no cancellation on expiry. |
| `stop_tool_task` | Explicit cancellation; 0.5-second wait checks acknowledgement, not proof the task has stopped. |

## Plugins

| Tool | Timer behavior / boundary | Evidence |
|---|---|---|
| `tickflow_get_quotes` | Common 60-second reporting; TickFlow SDK request timeout is still 30 seconds with configured retries, and SQLite waits remain bounded. A real SDK timeout is an error. | Code review; no live market API call |
| `tickflow_get_klines` | Common 60-second reporting; TickFlow SDK request timeout is still 30 seconds with configured retries, and SQLite waits remain bounded. A real SDK timeout is an error. | Code review; no live market API call |
| `tickflow_get_intraday` | Common 60-second reporting; TickFlow SDK request timeout is still 30 seconds with configured retries, and SQLite waits remain bounded. A real SDK timeout is an error. | Code review; no live market API call |
| `tickflow_get_financials` | Common 60-second reporting; TickFlow SDK request timeout is still 30 seconds with configured retries, and SQLite waits remain bounded. A real SDK timeout is an error. | Code review; no live market API call |
| `tickflow_get_instruments` | Common 60-second reporting; TickFlow SDK request timeout is still 30 seconds with configured retries, and SQLite waits remain bounded. A real SDK timeout is an error. | Code review; no live market API call |
| `tickflow_list_universes` | Common 60-second reporting; TickFlow SDK request timeout is still 30 seconds with configured retries, and SQLite waits remain bounded. A real SDK timeout is an error. | Code review; no live market API call |
| `tickflow_get_universe` | Common 60-second reporting; TickFlow SDK request timeout is still 30 seconds with configured retries, and SQLite waits remain bounded. A real SDK timeout is an error. | Code review; no live market API call |
| `tickflow_get_depth` | Common 60-second reporting; TickFlow SDK request timeout is still 30 seconds with configured retries, and SQLite waits remain bounded. A real SDK timeout is an error. | Code review; no live market API call |
| `ue_remote_control` | Common reporting and remote execute/wait retention; game action durations and external Unreal implementation are separate. | Host code reviewed; Unreal endpoint not exercised |
| `cancer_control` | Common reporting and remote execute/wait retention; game action durations and external Unreal implementation are separate. | Host code reviewed; Unreal endpoint not exercised |

core-dev re-exports built-in system_tools; it introduces no separate timer.

## Local script manifests

The launcher's timeoutSeconds is a reporting interval, verified with a real slow subprocess. It cannot erase deadlines programmed inside a child script or a third-party service. Script source was read, not modified or executed against production services.

| Script | Launcher report interval | Internal boundary inspected |
|---|---|---|
| `imagegen_gpt_official:image_gen` | 300 s | HTTP response wait of 290 seconds in the script remains; not a guaranteed resumable remote image job. |
| `knowledge:list` | 30 s | SQLite lock waits and configured embedding HTTP request timeouts remain; list/read/table have no separate script execution timer. |
| `knowledge:search` | 300 s | SQLite lock waits and configured embedding HTTP request timeouts remain; list/read/table have no separate script execution timer. |
| `knowledge:read` | 180 s | SQLite lock waits and configured embedding HTTP request timeouts remain; list/read/table have no separate script execution timer. |
| `knowledge:table` | 300 s | SQLite lock waits and configured embedding HTTP request timeouts remain; list/read/table have no separate script execution timer. |
| `qwen-turbo-image-edit:submit` | 180 s | HTTP 20 seconds/connect 5 seconds remain; result wait_seconds returns job state without resubmitting or cancelling the ComfyUI job. |
| `qwen-turbo-image-edit:result` | 120 s | HTTP 20 seconds/connect 5 seconds remain; result wait_seconds returns job state without resubmitting or cancelling the ComfyUI job. |
| `UISplite:inspect_images` | 60 s | No additional timer found; local image inspection. |
| `wechat-article:read` | 60 s | Fetch/redirect HTTP budget is 45 seconds and can fail before the launcher report; no resumable remote fetch API. |

## MCP and remote execution

All materialized MCP callables use the common task registry. readTimeoutSeconds is the tool reporting interval (default 5 seconds); tools/call sessions and SSE/streamable-HTTP reads have no local execution expiry. Connection/write/pool limits and tool discovery limits remain. The server can still reject, disconnect or enforce its own deadline, including an explicit timeout argument forwarded unchanged.

Unit contracts cover stdio, SSE and streamable HTTP for both discovery and execution. In this Windows sandbox, real asyncio/MCP integration tests block while creating the event loop socket pair, before tool code; they have not passed here. Remote broker, worker and same-ID polling are tested separately. The full asynchronous peer chain and an actual Unreal host have not been verified.

Remote desktop_screen has no additional execution timer. desktop_annotations uses bounded IPC startup/acknowledgement waits; it is a remote UI support capability, not a registered model tool. Standalone worker polling, peer readiness, authentication and HTTP/RPC delivery waits remain transport/liveness limits.

## Timers intentionally not converted

- Real connection/read/SDK service failures above are errors, not fictitious running states; uncertain mutations are not replayed.
- Cache TTL, cron schedules, pointer/keypress duration, observation validity, DB/file lock acquisition and finite result limits retain their contracts.
- Explicit stop, node/run shutdown and post-exit process-tree cleanup remain terminal. A tool task does not survive the owning run or server restart.
- Antigravity/other external CLI harness node runtimes and process-subtask scheduler deadlines are separate node execution mechanisms, not AgentPark callable tools; this patch does not claim to convert them.

## Verification

Focused regression run: **355 passed, 6 deselected**. The exclusions are the remote
async executor integration, MCP cache/stdio/SSE/HTTP integration paths blocked by
event-loop socket-pair creation in this environment, and an unrelated pre-existing
empty built-in GPT prompt assertion. The remote broker and mocked polling contracts
did run. Frontend `vue-tsc -b --pretty false` passed. Live external services were
not invoked merely to verify timer semantics.

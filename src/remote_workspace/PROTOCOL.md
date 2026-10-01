# AgentPark Remote Workspace Protocol v2

## Registration and device selection

AgentParkRemote starts from saved settings in `%LOCALAPPDATA%/AgentParkRemote/settings.json`.
On Linux, settings and identity use `$XDG_CONFIG_HOME/AgentParkRemote`, defaulting to
`~/.config/AgentParkRemote`. Native Linux packaging and startup instructions are in
`deploy/remote-worker/README-linux.md`.
The settings window allows editing the device name, server address and default workspace.
`--headless` starts without the window. `--server` and `--workspace` override saved values.

For a host/IP, the worker probes `http://HOST:8788/api/remote-workers/service`.
A complete URL explicitly selects the runtime origin/port. The response must be:

```json
{"service":"agentpark-runtime","remote_protocol":2}
```

A missing endpoint (404) or unavailable connection selects the same host's HTTPS
coordinator. Its service response identifies `agentpark-coordinator`. Authentication
errors, HTTP server errors, malformed responses and unsupported protocol versions
are reported rather than silently selecting another endpoint.

There is no browser-local discovery listener or browser-IP pairing. The browser
lists registered workers from `GET /api/remote-workers`. Settings -> Device
interconnection displays this catalog; a node's LinkToRemote action stores the
selected worker ID and its own absolute WorkingPath. Offline bindings never switch
to another worker or to server-local execution.

## Runtime registration

A directly registered worker uses these HTTP endpoints:

- POST `/api/remote-workers/register`
- POST `/api/remote-workers/{worker_id}/poll`
- POST `/api/remote-workers/{worker_id}/cancellations/poll`
- POST `/api/remote-workers/{worker_id}/heartbeat`
- POST `/api/remote-workers/{worker_id}/tasks/{task_id}/result`

Registration contains `protocol_version: 2`, persistent `worker_id` and `token`,
`display_name`, `host_kind`, `workspace_path`, and `capabilities`. The response is
`{ok, worker_id, token, protocol_version}`. Tokens are never returned in device lists.
Same-identity reconnection updates connection metadata while preserving queued
and active tasks and their synchronization owner. Conflicting credentials are rejected.

## Authentication center and shared directory

Cloud workers use the existing `/connect` WebSocket endpoint with persistent
Ed25519 identity proof. First admission is confirmed in the authentication center,
just like an AgentPark runtime. Only admitted devices can publish or receive a
remote directory. Browser sessions access it through their selected AgentPark Board.

After the existing ready acknowledgement, capable devices send:

```json
{"kind":"remote_publish","remote_workers":[
  {"worker_id":"worker-id","display_name":"Workstation","host_kind":"standalone",
   "workspace_path":"D:/Projects/Game","capabilities":["read_file"],"online":true}
]}
```

A runtime publishes itself (`host_kind: runtime`) and its directly registered workers.
A standalone cloud worker publishes itself. The coordinator binds each publication to the authenticated
connection's identity and broadcasts:

```json
{"kind":"remote_directory","hosts":[
  {"peer_id":"64-hex-host-identity","remote_workers":[]}
]}
```

Directory worker IDs exposed by a runtime are `peer:HOST_ID:WORKER_ID`, preserving
host ownership even when two different hosts use the same local worker ID. All
participating devices admitted by the same center may use the published remote
execution capabilities. This does not grant ordinary Board access or Agent
collaboration privileges; those still require their own per-call grants.

Task traffic uses the existing authenticated WebRTC data channel with STUN/TURN.
The coordinator only carries discovery and signaling, not workspace file content.
A runtime's own endpoint executes through the same workspace executor as a standalone
Remote. Requests for workers registered beneath that runtime dispatch into its local
Remote broker. It must never redirect a peer request to an unrelated third host.

The peer RPC operation is `remote_workspace`, with a strictly validated `remote`
request containing `action` (`execute` or `cancel`), `worker_id`, `task_id`,
`tool_name`, `arguments`, `working_path`, and `timeout_seconds`. The recipient binds
task cancellation to the calling runtime identity. Disconnects and response
uncertainty never automatically replay a command or file mutation.

## Workspace operations

Standalone capabilities: `read_file`, `write_file`, `view_image`, `rg_list_files`,
`rg_search_text`, `apply_patch`, `execute_console_command`, and `list_directories`.
Directory browsing returns `current_path`, `parent_path`, directory-only `files`,
and filesystem `roots` from the execution host. The initiating browser renders the
shared folder picker. No remote native dialog is opened. The browser requests
`POST /api/remote-workers/directories` with `{worker_id, path}`; old workers without
this capability receive an explicit update-required error.
Application-hosted workers may advertise their own additional capabilities.
Missing, relative or nonexistent WorkingPath values are explicit errors.

`workspace_exec` orchestration remains in the AgentPark runtime. Each filesystem
operation inside it goes through the remote router; server-owned task-state
operations remain on the runtime.

An HTTP task envelope is:

```json
{"task_id":"task-id","tool_name":"read_file","arguments":{"file_path":"Source/App.cpp"},
 "working_path":"D:/Projects/Game","timeout_seconds":3600}
```

The worker submits `{token, result: {ok: true, result: "tool-result-string"}}` or
`{token, result: {ok: false, error: "explicit message"}}`. Cancellation polling stays
active during tool execution. Child-process operations terminate their process tree
before returning a stopped result. A queued task that times out is removed, while
an active timed-out task receives a cancellation request.

The packaged Windows worker has no console window. It opens its connection settings
window unless `--headless` is used. Its default workspace is the executable directory.
Identity files, settings and rotating `AgentParkRemote.log` live in the state directory.

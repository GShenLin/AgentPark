# AgentPark Remote Workspace Protocol v1

The remote workspace protocol is host-neutral. Current worker implementations are:

- the standalone Windows `AgentParkRemote.exe`;
- the AgentPark Remote Unreal Editor plugin.

Only one worker should be online from a browser machine while the user enables a node's `Remote` checkbox. Enabling the checkbox pairs the node with that worker immediately. No second confirmation handshake is required.

## Worker lifecycle

1. Register with `POST /api/remote-workers/register`.
2. Long-poll `POST /api/remote-workers/{worker_id}/poll`.
3. Submit results to `POST /api/remote-workers/{worker_id}/tasks/{task_id}/result`.
4. Send heartbeats to `POST /api/remote-workers/{worker_id}/heartbeat`.

Registration fields:

```json
{
  "protocol_version": 1,
  "worker_id": "persistent-worker-id",
  "token": "persistent-secret-token",
  "display_name": "Alice-PC / ProjectName",
  "host_kind": "unreal_editor",
  "workspace_path": "D:\\Projects\\ProjectName",
  "capabilities": [
    "execute_console_command",
    "read_file",
    "write_file",
    "rg_search_text",
    "rg_list_files",
    "apply_patch",
    "select_folder"
  ]
}
```

`host_kind` is descriptive and must not affect protocol behavior. The Unreal plugin reports `unreal_editor`; the standalone process reports `standalone` while keeping the same task and result contracts. Only one protocol host should be open on a browser machine while pairing.

The standalone worker and Unreal plugin use the same browser discovery endpoint. They listen only on
`127.0.0.1:18766` for `POST /agentpark/discover`. The request must contain the current AgentPark page
origin as `server_url`, and its HTTP `Origin` header must match that value exactly. The worker persists
the accepted server origin and its protocol identity, then registers through the lifecycle above.

`AgentParkRemote.exe` advertises only standalone workspace capabilities. Unreal-only tools such as
`ue_remote_control` and `cancer_control` remain exclusive to workers that actually host those operations.

## Workspace semantics

When a node has `Remote` enabled, its `WorkingPath` is an absolute path on the paired worker. Every workspace tool is routed through the same central AgentPark tool dispatcher. Workers must reject missing, relative, or nonexistent WorkingPath values and must never silently execute on the AgentPark server.

## Task envelope

```json
{
  "task_id": "task-id",
  "tool_name": "read_file",
  "arguments": {"file_path": "Source/App.cpp"},
  "working_path": "D:\\Projects\\ProjectName",
  "timeout_seconds": 3600
}
```

Successful result:

```json
{
  "token": "persistent-secret-token",
  "result": {
    "ok": true,
    "result": "{\"status\":\"success\"}"
  }
}
```

Failed result:

```json
{
  "token": "persistent-secret-token",
  "result": {
    "ok": false,
    "error": "explicit failure message"
  }
}
```

## Standalone process behavior

The Windows executable is built with the GUI subsystem (`console=False`) and runs without a visible
console window. Its default workspace is the directory containing the executable; `--workspace` can set
a different initial workspace. Browser pairing may subsequently invoke `select_folder` to choose the
node's remote WorkingPath. Identity and rotating diagnostic logs are stored under
`%LOCALAPPDATA%\AgentParkRemote`.

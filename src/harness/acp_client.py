"""ACP JSON-RPC contract over an owned resident JSONL process."""
from __future__ import annotations

from .jsonl_process import JsonlProcess


class AcpClient(JsonlProcess):
    def __init__(self, argv, *, on_update, **kwargs):
        super().__init__(argv, **kwargs)
        self.on_update = on_update
        self.sequence = 0

    def _write(self, value):
        self.send({"jsonrpc": "2.0", **value})

    def request(self, method: str, params: dict) -> dict:
        self.sequence += 1
        request_id = self.sequence
        self._write({"id": request_id, "method": method, "params": params})
        while True:
            message = self.receive()
            if message.get("jsonrpc") != "2.0":
                raise ValueError("ACP stdout must contain JSON-RPC 2.0 objects.")
            if "method" in message:
                if message["method"] == "session/update" and "id" not in message:
                    params = message.get("params")
                    if not isinstance(params, dict):
                        raise ValueError("ACP session/update requires params.")
                    self.on_update(params)
                elif "id" in message:
                    if message["method"] == "session/request_permission":
                        self._write({"id": message["id"], "result": {"outcome": {"outcome": "cancelled"}}})
                        raise RuntimeError("ACP runtime requested interactive permission; this node supports unattended execution only.")
                    self._write({"id": message["id"], "error": {"code": -32601, "message": "Client method not supported"}})
                    raise RuntimeError(f"Unsupported ACP client request: {message['method']}")
                continue
            if message.get("id") != request_id:
                raise ValueError("Unexpected ACP response id.")
            if "error" in message:
                raise RuntimeError(f"ACP {method} failed: {message['error']}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise ValueError(f"ACP {method} result must be an object.")
            return result

"""Exercise the embedded MCP endpoint through non-loopback HTTP addresses."""

import json
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from src.web_backend.companion_mcp import build_companion_mcp


@pytest.mark.parametrize("base_url", ["http://192.168.34.15:8788", "http://agentpark.internal:8788"])
def test_companion_mcp_accepts_remote_host_and_origin(base_url):
    mcp = build_companion_mcp(object())

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/mcp", mcp.streamable_http_app())
    headers = {"Accept": "application/json, text/event-stream", "Origin": "http://client.internal:3000"}
    with TestClient(app, base_url=base_url) as client:
        response = client.post("/mcp/", headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "transport-test", "version": "1.0"},
            },
        })
        assert response.status_code == 200, response.text
        payload = json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith("data: ")))
        assert payload["result"]["serverInfo"]["name"] == "agentpark-companion"

        invalid = client.post("/mcp/", headers={**headers, "Content-Type": "text/plain"}, content="invalid")
        assert invalid.status_code == 400
        assert invalid.text == "Invalid Content-Type header"

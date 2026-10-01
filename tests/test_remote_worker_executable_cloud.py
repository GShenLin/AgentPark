import asyncio
import json
import os
import socket
import subprocess
from pathlib import Path

import pytest

from src.peer_network.contracts import NetworkSettings
from src.peer_network.enrollment import DeviceAdmissions
from src.peer_network.identity import DeviceIdentity
from src.peer_network.remote_contracts import RemoteRequest
from src.peer_network.service import PeerNetworkService
from src.peer_network.signaling import create_signaling_app


def test_packaged_remote_registers_with_center_and_executes_over_webrtc(tmp_path):
    executable = os.environ.get("AGENTPARK_REMOTE_EXE", "")
    if not executable:
        pytest.skip("set AGENTPARK_REMOTE_EXE to test the packaged cloud worker")
    import uvicorn

    async def wait_for(predicate, timeout=35):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(.05)

    async def scenario():
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        admissions = DeviceAdmissions()
        server = uvicorn.Server(uvicorn.Config(create_signaling_app(admissions=admissions), log_level="error"))
        server_task = asyncio.create_task(server.serve(sockets=[sock]))
        async def reject(grant, call):
            raise PermissionError("not granted")
        runtime = PeerNetworkService(tmp_path / "runtime", reject)
        remote_state = tmp_path / "remote"
        identity = DeviceIdentity.load(remote_state / "peer-network" / "identity.json")
        for peer in [identity.peer_id, runtime.identity.peer_id]:
            admissions.request(peer, "Packaged test", "127.0.0.1")
            admissions.decide(peer, "approved")
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "cloud.txt").write_text("packaged-cloud-ok", encoding="utf-8")
        process = None
        try:
            await wait_for(lambda: server.started)
            await runtime.configure(NetworkSettings(enabled=True, signaling_url=f"ws://127.0.0.1:{port}/connect", stun_urls=[]))
            process = subprocess.Popen([str(Path(executable).resolve()), "--headless", "--server",
                                        f"http://127.0.0.1:{port}", "--workspace", str(workspace),
                                        "--state-directory", str(remote_state)])
            await wait_for(lambda: bool(runtime.remote.workers()))
            worker_id = runtime.remote.workers()[0]["worker_id"]
            response = await runtime.remote.call(worker_id, RemoteRequest(
                action="execute", worker_id=worker_id, task_id="packaged-cloud-read", tool_name="read_file",
                arguments={"file_path": "cloud.txt"}, working_path=str(workspace), timeout_seconds=10.0,
            ))
            assert json.loads(response["result"])["content"] == "packaged-cloud-ok"
        finally:
            if process is not None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                else:
                    process.terminate()
                process.wait(timeout=10)
            await runtime.stop()
            server.should_exit = True
            await asyncio.wait_for(server_task, 10)
            sock.close()
    asyncio.run(scenario())

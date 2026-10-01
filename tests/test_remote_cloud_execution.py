"""Real coordinator and WebRTC endpoints: discovery, execution and cancellation."""
import asyncio
import json
import socket
import threading
from types import SimpleNamespace

import pytest

from src.peer_network.contracts import NetworkSettings, PeerCall
from src.peer_network.enrollment import DeviceAdmissions
from src.peer_network.remote_contracts import RemoteRequest
from src.peer_network.service import PeerNetworkService
from src.peer_network.signaling import create_signaling_app
from src.remote_worker.cloud import CloudRemoteWorker
from src.remote_workspace.operations import WorkspaceOperationRegistry
from src.remote_workspace.broker import RemoteWorkspaceBroker
from src.remote_workspace.peer_bridge import RemotePeerBridge


def test_shared_remote_directory_execution_and_cancellation_without_pairing(tmp_path):
    pytest.importorskip("aiortc")
    import uvicorn

    async def wait_for(predicate):
        async with asyncio.timeout(25):
            while not predicate():
                await asyncio.sleep(.02)

    async def scenario():
        admissions = DeviceAdmissions()
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_signaling_app(admissions=admissions), log_level="error"))
        server_task = asyncio.create_task(server.serve(sockets=[sock]))
        async def denied(grant, call):
            raise PermissionError("ordinary peer operations are not granted")
        a = PeerNetworkService(tmp_path / "a", denied)
        b = PeerNetworkService(tmp_path / "b", denied)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "hello.txt").write_text("remote data", encoding="utf-8")
        operations = WorkspaceOperationRegistry()
        remote = CloudRemoteWorker(tmp_path / "remote", f"http://127.0.0.1:{port}", "Remote PC",
                                   str(workspace), operations, lambda text: None)
        # No external STUN is needed for this real local WebRTC exchange.
        remote.service.store.settings = remote.service.store.settings.model_copy(update={"stun_urls": []})
        services = [a, b, remote.service]
        try:
            await wait_for(lambda: server.started)
            for service in services:
                admissions.request(service.identity.peer_id, "test", "127.0.0.1")
                admissions.decide(service.identity.peer_id, "approved")
            settings = NetworkSettings(enabled=True, signaling_url=f"ws://127.0.0.1:{port}/connect", stun_urls=[])
            await a.configure(settings)
            await b.configure(settings)
            await remote.service.start()
            await wait_for(lambda: len(a.remote.workers()) == len(b.remote.workers()) == 1)
            worker_id = a.remote.workers()[0]["worker_id"]
            assert b.remote.workers()[0]["worker_id"] == worker_id
            assert not a.store.grants and not b.store.grants
            # A Remote registered directly on runtime B is published by B and
            # can be executed by A without making it a local filesystem call.
            broker = RemoteWorkspaceBroker()
            bridge = RemotePeerBridge(SimpleNamespace(service=b), broker)
            bridge.install(b, str(workspace))
            broker.register({"protocol_version": 2, "worker_id": "hosted-worker", "token": "test-secret",
                             "workspace_path": str(workspace), "display_name": "Hosted remote",
                             "host_kind": "standalone", "capabilities": ["read_file"]}, "10.0.0.8")
            await b.remote.publish()
            await wait_for(lambda: len(a.remote.workers()) == 3)
            # Full runtimes execute locally without starting a separate Remote.
            runtime_id = next(w["worker_id"] for w in a.remote.workers() if w["host_kind"] == "runtime")
            runtime_read = RemoteRequest(
                action="execute", worker_id=runtime_id, task_id="runtime-read", tool_name="read_file",
                arguments={"file_path": "hello.txt"}, working_path=str(workspace), timeout_seconds=10.0,
            )
            assert json.loads((await a.remote.call(runtime_id, runtime_read))["result"])["content"] == "remote data"
            (workspace / "remote-only-folder").mkdir()
            for target in [runtime_id, worker_id]:
                result = await a.remote.call(target, RemoteRequest(
                    action="execute", worker_id=target, task_id="browse-folders", tool_name="list_directories",
                    arguments={"path": str(workspace)}, working_path=str(workspace), timeout_seconds=10.0,
                ))
                listing = json.loads(result["result"])
                assert listing["current_path"] == str(workspace)
                assert [entry["name"] for entry in listing["files"]] == ["remote-only-folder"]
            with pytest.raises(RuntimeError, match="revoked"):
                await a.connections.links[b.identity.peer_id].channel.call(PeerCall(operation="graphs"))
            hosted_id = next(w["worker_id"] for w in a.remote.workers() if w["display_name"] == "Hosted remote")
            def hosted_worker():
                task = broker.poll("hosted-worker", "test-secret", 10)
                assert task is not None
                assert task["working_path"] == str(workspace)
                broker.submit_result("hosted-worker", "test-secret", task["task_id"],
                                     {"ok": True, "result": "hosted-result"})
            worker_thread = threading.Thread(target=hosted_worker)
            worker_thread.start()
            hosted_result = await a.remote.call(hosted_id, RemoteRequest(
                action="execute", worker_id=hosted_id, task_id="hosted-read", tool_name="read_file",
                arguments={"file_path": "hello.txt"}, working_path=str(workspace), timeout_seconds=10.0,
            ))
            worker_thread.join(1)
            assert hosted_result == {"result": "hosted-result"}
            assert not worker_thread.is_alive()
            request = RemoteRequest(action="execute", worker_id=worker_id, task_id="read-one", tool_name="read_file",
                                    arguments={"file_path": "hello.txt"}, working_path=str(workspace), timeout_seconds=10.0)
            response = await a.remote.call(worker_id, request)
            assert json.loads(response["result"])["content"] == "remote data"
            response = await b.remote.call(worker_id, request.model_copy(update={"task_id": "read-two"}))
            assert json.loads(response["result"])["content"] == "remote data"
            # Directory trust does not authorize ordinary Board/Agent operations.
            link = a.connections.links[remote.service.identity.peer_id]
            with pytest.raises(RuntimeError, match="revoked"):
                await link.channel.call(PeerCall(operation="graphs"))

            entered = asyncio.Event()
            loop = asyncio.get_running_loop()
            def blocking_read(*, agent, **kwargs):
                loop.call_soon_threadsafe(entered.set)
                assert agent.cancel_event.wait(10)
                return json.dumps({"status": "stopped"})
            operations._operations["read_file"] = blocking_read
            request = request.model_copy(update={"task_id": "cancel-one"})
            pending = asyncio.create_task(a.remote.call(worker_id, request))
            await asyncio.wait_for(entered.wait(), 5)
            await a.remote.call(worker_id, RemoteRequest(action="cancel", worker_id=worker_id,
                                                         task_id="cancel-one", timeout_seconds=5.0))
            assert json.loads((await pending)["result"])["status"] == "stopped"

            await remote.service.stop()
            await wait_for(lambda: len(a.remote.workers()) == 2 and not b.remote.workers())
            await remote.service.start()
            await wait_for(lambda: len(a.remote.workers()) == 3)
            assert worker_id in {w["worker_id"] for w in a.remote.workers()}
        finally:
            for service in services:
                await service.stop()
            server.should_exit = True
            await asyncio.wait_for(server_task, 10)
            sock.close()
    asyncio.run(scenario())

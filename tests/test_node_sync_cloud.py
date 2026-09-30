"""Real portal login + signed tickets + two WebRTC devices + durable sync jobs."""
import asyncio
import json
import socket
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request

from src.peer_network.contracts import NetworkSettings, PeerCall, PeerGrant
from src.peer_network.enrollment import DeviceAdmissions
from src.peer_network.service import PeerNetworkService
from src.peer_network.signaling import create_signaling_app
from src.web_backend.access_api import AccessApiDomain
from src.web_backend.peer_board_http import PeerBoardHttp
from src.web_backend.peer_operations import PeerOperations
from src.web_backend.node_sync.jobs import SyncJobs
from src.web_backend.node_sync.contracts import SyncRequest
from src.web_backend.node_sync.routes import register_node_sync_routes
from src.web_backend.node_sync.service import SyncService
from src.web_backend.node_memory_records import write_jsonl_records, read_jsonl_records
from tests.test_node_sync import core_for, make_node, record


def local_request():
    return Request({'type': 'http', 'headers': [(b'host', b'127.0.0.1')], 'client': ('127.0.0.1', 9999)})


def test_cloud_sync_two_real_devices_incremental_and_permissions(tmp_path):
    import uvicorn
    async def wait_for(predicate):
        async with asyncio.timeout(25):
            while not predicate():
                await asyncio.sleep(.05)

    async def scenario():
        admissions = DeviceAdmissions()
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        server = uvicorn.Server(uvicorn.Config(create_signaling_app(admissions=admissions,
            portal_password='test-sync-password'), log_level='error'))
        server_task = asyncio.create_task(server.serve(sockets=[sock]))
        settings = NetworkSettings(enabled=True, signaling_url=origin.replace('http:', 'ws:') + '/connect', stun_urls=[])
        roots = [tmp_path / 'a', tmp_path / 'b']
        nodes = [make_node(roots[0], 'source', 'Agent'), make_node(roots[1], 'target', 'Worker')]
        picture = nodes[0] / 'picture.png'
        picture.write_bytes(b'chunked-attachment' * 42000)
        user = record('user1', 'user', '云端同步测试')
        user['parts'].append({'type': 'resource', 'resource': {'id': 'p', 'uri': str(picture), 'kind': 'image', 'name': picture.name}})
        write_jsonl_records(str(nodes[0] / 'archive/2026-09-27/messages.jsonl'),
                            [user, record('process1', 'assistant_progress'), record('answer1', 'assistant')])
        cores, peers, services = [], [], []
        for i, root in enumerate(roots):
            core = core_for(root)
            core.access_api = AccessApiDomain()
            app = FastAPI()
            sync = SyncService(core, root / '.sync')
            register_node_sync_routes(app, core, service=sync)
            services.append(sync)
            peer = PeerNetworkService(root / '.peer', PeerOperations(core, None))
            peer.board_dispatch = PeerBoardHttp(core, app)
            admissions.request(peer.identity.peer_id, f'Device {i}', '127.0.0.1')
            admissions.decide(peer.identity.peer_id, 'approved')
            cores.append(core); peers.append(peer)
        host_core = core_for(tmp_path / 'host')
        host_core.access_api = AccessApiDomain()
        host_core.peer_api = SimpleNamespace(service=SimpleNamespace(store=SimpleNamespace(settings=settings)))
        host_core.remote_api = SimpleNamespace(list_remotes=lambda request: {'remotes': [
            {'id': 'default', 'name': 'Local', 'host': '127.0.0.1', 'port': 8788},
            {'id': 'lan', 'name': 'LAN', 'host': '192.0.2.1', 'port': 8788}]})
        jobs = SyncJobs(SyncService(host_core, tmp_path / 'jobs'))
        request = local_request()
        try:
            await wait_for(lambda: server.started)
            for peer in peers:
                await peer.configure(settings)
            await wait_for(lambda: all(p.socket for p in peers))
            # An ordinary paired peer must still be unable to use Board administrator operations.
            with pytest.raises(PermissionError):
                PeerOperations(cores[0], None).execute(PeerGrant(peer_id='a' * 64, name='ordinary', view=True),
                                                       PeerCall(operation='board_http'))
            with pytest.raises(ValueError, match='密码错误'):
                await asyncio.to_thread(jobs.cloud.login, request, 'wrong-password')
            assert not jobs.cloud.sessions
            await asyncio.to_thread(jobs.cloud.login, request, 'test-sync-password')
            listing = await asyncio.to_thread(jobs.remotes, request)
            assert [r['kind'] for r in listing['remotes']] == ['local', 'lan', 'cloud', 'cloud']
            remote_ids = [jobs.cloud.prefix(origin) + p.identity.peer_id for p in peers]
            payload = SyncRequest.model_validate({
                'source': {'remote_id': remote_ids[0], 'graph_id': 'source', 'node_id': 'Agent'},
                'target': {'remote_id': remote_ids[1], 'graph_id': 'target', 'node_id': 'Worker'}})
            catalog = await asyncio.to_thread(jobs.call, remote_ids[0], 'catalog', {}, request)
            assert catalog['graphs'][0]['id'] == 'source'
            job = await asyncio.to_thread(jobs.create, payload, request)
            await wait_for(lambda: jobs.get(job['id'], request)['state'] not in {'preparing', 'applying'})
            ready = jobs.get(job['id'], request)
            assert ready['state'] == 'ready' and ready['result']['added'] == 2, ready
            assert not (nodes[1] / 'archive/2026-09-27/messages.jsonl').exists()
            await asyncio.to_thread(jobs.launch, job['id'], 'commit', request)
            await wait_for(lambda: jobs.get(job['id'], request)['state'] not in {'preparing', 'applying'})
            assert jobs.get(job['id'], request)['state'] == 'complete'
            records = read_jsonl_records(str(nodes[1] / 'archive/2026-09-27/messages.jsonl'))
            assert [r['id'] for r in records] == ['user1', 'answer1']
            assert next((nodes[1] / 'sync_attachments').rglob('*.png')).read_bytes() == picture.read_bytes()
            again = await asyncio.to_thread(jobs.create, payload, request)
            await wait_for(lambda: jobs.get(again['id'], request)['state'] != 'preparing')
            assert jobs.get(again['id'], request)['result']['added'] == 0
            whole = SyncRequest.model_validate({
                'source': {'remote_id': remote_ids[0], 'graph_id': 'source'},
                'target': {'remote_id': remote_ids[1], 'graph_id': 'target'}})
            graph_job = await asyncio.to_thread(jobs.create, whole, request)
            await wait_for(lambda: jobs.get(graph_job['id'], request)['state'] != 'preparing')
            assert jobs.get(graph_job['id'], request)['state'] == 'ready'
            await asyncio.to_thread(jobs.launch, graph_job['id'], 'commit', request)
            await wait_for(lambda: jobs.get(graph_job['id'], request)['state'] != 'applying')
            assert jobs.get(graph_job['id'], request)['state'] == 'complete'
            assert (roots[1] / 'target/Agent/config.json').exists()
            assert (roots[1] / 'target/Worker/config.json').exists()
            # A failure after a durable chunk must be visible and resumable.
            write_jsonl_records(str(nodes[0] / 'messages.jsonl'), [record('u2', 'user'), record('a2', 'assistant')])
            write = services[1].blobs.write
            def lost_response(sha, chunk):
                write(sha, chunk)
                services[1].blobs.write = write
                raise ValueError('test response lost after durable chunk')
            services[1].blobs.write = lost_response
            failed = await asyncio.to_thread(jobs.create, payload, request)
            await wait_for(lambda: jobs.get(failed['id'], request)['state'] != 'preparing')
            assert 'response lost' in jobs.get(failed['id'], request)['error']
            await asyncio.to_thread(jobs.launch, failed['id'], 'preview', request)
            await wait_for(lambda: jobs.get(failed['id'], request)['state'] != 'preparing')
            assert jobs.get(failed['id'], request)['result']['added'] == 2
            # A LAN developer cannot use another administrator's portal login or job.
            remote_request = Request({'type': 'http', 'headers': [(b'host', b'127.0.0.1')], 'client': ('192.0.2.2', 9999)})
            assert jobs.cloud.remotes(remote_request) == []
            with pytest.raises(HTTPException):
                jobs.get(job['id'], remote_request)
            # Disconnect then establish a fresh signed connection; completed writes are not replayed.
            client = jobs.cloud.get(request)
            await asyncio.to_thread(jobs.cloud.run, lambda: client.connections[peers[0].identity.peer_id].close())
            assert (await asyncio.to_thread(jobs.call, remote_ids[0], 'catalog', {}, request))['graphs']
            disk = ''.join(p.read_text(encoding='utf-8') for p in (tmp_path / 'jobs').rglob('*.json'))
            assert 'test-sync-password' not in disk and 'agentpark_portal_session' not in disk
            await asyncio.to_thread(jobs.cloud.logout, request)
            assert not jobs.cloud.status(request)['connected']
            assert len((await asyncio.to_thread(jobs.remotes, request))['remotes']) == 2
        finally:
            await asyncio.to_thread(jobs.cloud.close)
            for peer in peers:
                await peer.stop()
            server.should_exit = True
            await asyncio.wait_for(server_task, 10)
            sock.close()
    asyncio.run(scenario())


def test_cloud_admin_identity_survives_board_reconnect(tmp_path):
    from src.peer_network.principal import CloudBoardAdministrator, PeerPrincipal
    from src.web_backend.node_sync.cloud import CloudDevices
    cloud = CloudDevices(core_for(tmp_path))
    def request(principal):
        return Request({'type': 'http', 'headers': [], 'client': ('portal:remote', 0),
                        'state': {'peer_principal': principal}})
    assert cloud.owner(request(CloudBoardAdministrator('a' * 64, 'admin'))) == cloud.owner(
        request(CloudBoardAdministrator('b' * 64, 'admin')))
    with pytest.raises(HTTPException):
        cloud.owner(request(PeerPrincipal('a' * 64, 'peer')))

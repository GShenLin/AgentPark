"""Two HTTP servers: chunk transfer, response loss, retry, persisted result."""
import socket
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from src.web_backend.node_sync.routes import register_node_sync_routes
from src.web_backend.node_sync.service import SyncService
from src.web_backend.node_sync.blobs import read_json, CHUNK_SIZE
from src.web_backend.node_sync.jobs import SyncJobs
from src.web_backend.node_sync.contracts import SyncConflict
from src.web_backend.node_memory_records import write_jsonl_records, read_jsonl_records
from tests.test_node_sync import core_for, make_node, record


@contextmanager
def serve(core, service):
    app = FastAPI()
    register_node_sync_routes(app, core, service=service)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(.02)
    assert server.started
    try:
        yield f'http://127.0.0.1:{port}', port
    finally:
        server.should_exit = True
        thread.join(5)
        sock.close()


def test_two_http_endpoints_resume_response_loss(tmp_path, monkeypatch):
    root_a, root_b = tmp_path / 'a', tmp_path / 'b'
    a, b = make_node(root_a, 'source', 'Agent'), make_node(root_b, 'target', 'Worker')
    cores = [core_for(root_a), core_for(root_b)]
    services = [SyncService(cores[0], root_a / '.sync'), SyncService(cores[1], root_b / '.sync')]
    attachment = a / 'image.png'
    attachment.write_bytes(b'0123456789' * 70000)
    user = record('u', 'user')
    user['parts'].append({'type': 'resource', 'resource': {'id': 'r', 'uri': str(attachment),
                         'kind': 'image', 'name': 'image.png'}})
    write_jsonl_records(str(a / 'archive/2026-09-27/messages.jsonl'), [user, record('f', 'assistant')])
    with serve(cores[1], services[1]) as (url_b, port_b):
        remotes = [{'id': 'default', 'name': 'local', 'host': '127.0.0.1', 'port': 8788},
                   {'id': 'b', 'name': 'B', 'host': '127.0.0.1', 'port': port_b}]
        cores[0].remote_api = SimpleNamespace(list_remotes=lambda request: {'remotes': remotes})
        with serve(cores[0], services[0]) as (url_a, _), httpx.Client(trust_env=False, timeout=20) as client:
            def post(path, data=None):
                response = client.post(url_a + path, json=data or {}, timeout=20)
                response.raise_for_status()
                return response.json()
            def wait(id):
                for _ in range(250):
                    result = client.get(url_a + '/api/node-sync/jobs/' + id).json()
                    if result['state'] not in ('preparing', 'applying'):
                        return result
                    time.sleep(.02)
                raise AssertionError('timeout')
            original = services[1].blobs.write
            lost = False
            def lossy_write(sha, chunk):
                nonlocal lost
                result = original(sha, chunk)
                if not lost and chunk.total > CHUNK_SIZE:
                    lost = True
                    raise ValueError('simulated response lost after durable chunk')
                return result
            monkeypatch.setattr(services[1].blobs, 'write', lossy_write)
            payload = {'source': {'remote_id': 'default', 'graph_id': 'source', 'node_id': 'Agent'},
                       'target': {'remote_id': 'b', 'graph_id': 'target', 'node_id': 'Worker'}}
            job = post('/api/node-sync/jobs', payload)
            failed = wait(job['id'])
            assert failed['state'] == 'failed' and 'simulated response lost' in failed['error']
            assert not (b / 'messages.jsonl').exists()
            post(f"/api/node-sync/jobs/{job['id']}/preview")
            ready = wait(job['id'])
            assert ready['state'] == 'ready' and ready['result']['added'] == 2, ready
            post(f"/api/node-sync/jobs/{job['id']}/commit")
            done = wait(job['id'])
            assert done['state'] == 'complete', done
            assert [r['id'] for r in read_jsonl_records(str(b / 'archive/2026-09-27/messages.jsonl'))] == ['u', 'f']
            assert read_json(services[0].root / 'jobs' / (job['id'] + '.json'))['state'] == 'complete'


@pytest.mark.parametrize('status,content_type,body,error', [
    (200, 'application/json', '{"ok":true}', None),
    (403, 'application/json', '{}', '开发者权限'),
    (404, 'application/json', '{}', '尚不支持节点同步'),
    (405, 'application/json', '{}', '尚不支持节点同步'),
    (500, 'text/plain', 'server failed', 'HTTP 500 server failed'),
    (302, 'text/html', 'redirect', '非同步协议内容'),
    (200, 'text/html', 'login page', '非同步协议内容'),
])
def test_lan_transport_contract(tmp_path, monkeypatch, status, content_type, body, error):
    remote = {'id': 'lan', 'name': 'LAN', 'host': '::1', 'port': 8788}
    core = SimpleNamespace(remote_api=SimpleNamespace(list_remotes=lambda _: {'remotes': [remote]}))
    jobs = SyncJobs(SimpleNamespace(root=tmp_path, core=core))
    incoming = SimpleNamespace(headers={
        'x-agentpark-client-id': 'client', 'x-agentpark-username': 'user',
        'authorization': 'must-not-forward',
    })
    calls = []

    def request(self, **kwargs):
        from src.providers.curl_transport import CurlResponse
        import json
        calls.append(kwargs)
        assert kwargs['url'] == 'http://[::1]:8788/api/node-sync/protocol/catalog'
        assert kwargs['method'] == 'POST' and json.loads(kwargs['body']) == {'graph_id': 'g'}
        assert kwargs['headers']['x-agentpark-client-id'] == 'client'
        assert kwargs['headers']['x-agentpark-username'] == 'user'
        assert 'authorization' not in kwargs['headers']
        assert kwargs['connect_timeout'] == 10 and kwargs['timeout_sec'] == 180
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return CurlResponse(body, status, {'content-type': content_type, 'location': '/redirected'})

    monkeypatch.setattr('src.web_backend.node_sync.jobs.CurlHttpTransport.request', request)
    if error:
        with pytest.raises(SyncConflict, match=error):
            jobs.call('lan', 'catalog', {'graph_id': 'g'}, incoming)
    else:
        assert jobs.call('lan', 'catalog', {'graph_id': 'g'}, incoming) == {'ok': True}
    assert len(calls) == 1

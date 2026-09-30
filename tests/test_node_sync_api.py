"""Exercise real graph/node APIs and asynchronous synchronization jobs."""
import time
from pathlib import Path

from fastapi.testclient import TestClient

from src.web_backend.node_memory_records import write_jsonl_records, read_jsonl_records
from src.web_backend.node_sync.blobs import write_json


def wait_job(client, id):
    for _ in range(200):
        response = client.get('/api/node-sync/jobs/' + id)
        assert response.status_code == 200, response.text
        job = response.json()
        if job['state'] not in ('preparing', 'applying'):
            return job
        time.sleep(.02)
    raise AssertionError('sync timed out')


def test_real_routes_graph_sync_and_no_execution(monkeypatch, tmp_path):
    from src.web_backend import create_app
    from src.web_backend.runtime_paths import _get_graphs_dir
    monkeypatch.setattr('src.web_backend.node_sync.service._get_runtime_root', lambda: str(tmp_path))
    client = TestClient(create_app(), client=('127.0.0.1', 50000))
    for graph in ('sync_source', 'sync_target'):
        response = client.post('/api/graphs/' + graph, json={'graph': {'id': graph, 'name': graph}})
        assert response.status_code == 200, response.text
    response = client.post('/api/nodes/instances', json={'graph_id': 'sync_source', 'node_id': 'Agent',
        'type_id': 'agent_node', 'ui': {'grid_x': 1, 'grid_y': 0}})
    assert response.status_code == 200, response.text
    source = Path(_get_graphs_dir()) / 'sync_source' / 'Agent'
    target = Path(_get_graphs_dir()) / 'sync_target' / 'Agent'
    records = [{'id': 'api-user', 'role': 'user', 'parts': [{'type': 'text', 'text': 'test'}],
                'created_at': '2026-09-29 10:00:00'},
               {'id': 'api-final', 'role': 'assistant', 'parts': [{'type': 'text', 'text': 'done'}],
                'created_at': '2026-09-29 10:01:00'}]
    write_jsonl_records(str(source / 'messages.jsonl'), records)
    catalog = client.get('/api/node-sync/catalog/default?graph_id=sync_source')
    assert catalog.status_code == 200 and catalog.json()['nodes'][0]['id'] == 'Agent'
    payload = {'source': {'remote_id': 'default', 'graph_id': 'sync_source'},
               'target': {'remote_id': 'default', 'graph_id': 'sync_target'}}
    response = client.post('/api/node-sync/jobs', json=payload)
    assert response.status_code == 200, response.text
    job = wait_job(client, response.json()['id'])
    assert job['state'] == 'ready', job
    assert job['result']['added'] == 2
    response = client.post(f"/api/node-sync/jobs/{job['id']}/commit")
    assert response.status_code == 200, response.text
    done = wait_job(client, job['id'])
    assert done['state'] == 'complete', done
    assert read_jsonl_records(str(target / 'messages.jsonl')) == records
    actual = client.get('/api/nodes/instances/configs?graph_id=sync_target').json()['nodes']
    assert len(actual) == 1 and actual[0]['pending_count'] == 0 and actual[0]['state'] == 'idle'
    repeated = client.post('/api/node-sync/jobs', json=payload).json()
    repeated = wait_job(client, repeated['id'])
    assert repeated['state'] == 'ready' and repeated['result']['added'] == 0, repeated


def test_sync_requires_developer_permission(monkeypatch, tmp_path):
    from src.web_backend import create_app
    monkeypatch.setattr('src.web_backend.node_sync.service._get_runtime_root', lambda: str(tmp_path))
    client = TestClient(create_app(), client=('192.0.2.1', 50000))
    assert client.get('/api/node-sync/remotes').status_code == 403
    assert client.post('/api/node-sync/protocol/catalog', json={}).status_code == 403
    assert client.post('/api/node-sync/jobs', json={
        'source': {'remote_id': 'default', 'graph_id': 'g1'},
        'target': {'remote_id': 'default', 'graph_id': 'g2'}}).status_code == 403

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from src.web_backend.harness_api import HarnessApiDomain
from src.harness.process_manager import HarnessProcesses


@pytest.fixture
def api(tmp_path, monkeypatch):
    path = tmp_path / 'node' / 'config.json'
    path.parent.mkdir()
    path.write_text(json.dumps({'type_id': 'pi_node'}), encoding='utf8')
    calls = []
    class Manager:
        state = 'stopped'
        def list(self, kind):
            calls.append(('list', kind))
            return [{'harness_id': kind, 'node_id': 'node', 'graph_id': 'g', 'state': self.state, 'error': ''}]
        def status(self, directory):
            assert Path(directory) == path.parent
            return {'state': self.state, 'error': ''}
        def execute(self, kind, context):
            assert kind == 'pi' and context.config_path == str(path)
            assert context.values['node_instance_id'] == 'node'
            self.state = 'ready'
        def stop(self, directory):
            assert Path(directory) == path.parent
            self.state = 'stopped'
    manager = Manager()
    monkeypatch.setattr(HarnessProcesses, 'instance', lambda: manager)
    def resolve(graph, node):
        if node != 'node':
            raise HTTPException(404)
        return node
    graph = SimpleNamespace(_sanitize_graph_id=lambda _: 'g', _resolve_existing_node_id=resolve,
        _node_config_path=lambda node, graph: str(path))
    domain = HarnessApiDomain(SimpleNamespace(graph_runtime=graph))
    app = FastAPI()
    app.get('/api/harnesses/{harness_id}/processes')(domain.list_processes)
    app.get('/api/nodes/instances/{node_id}/harness-process')(domain.process_status)
    app.post('/api/nodes/instances/{node_id}/harness-process')(domain.control_process)
    return app, path, calls


def test_node_start_stop_and_type_list_contract(api):
    app, path, calls = api
    client = TestClient(app, client=('127.0.0.1', 123))
    url = '/api/nodes/instances/node/harness-process?graph_id=g'
    assert client.get(url).json()['state'] == 'stopped'
    result = client.post(url, json={'action': 'start'})
    assert result.status_code == 200
    assert result.json() == {'harness_id': 'pi', 'node_id': 'node', 'graph_id': 'g', 'state': 'ready', 'error': ''}
    assert client.get('/api/harnesses/pi/processes').json()['processes'][0]['harness_id'] == 'pi'
    assert calls == [('list', 'pi')]
    assert client.post(url, json={'action': 'stop'}).json()['state'] == 'stopped'
    assert path.exists()
    assert client.post(url, json={'action': 'start', 'command': 'arbitrary'}).status_code == 422
    assert client.get('/api/harnesses/unknown/processes').status_code == 404


def test_process_management_requires_owner_and_harness_node(api):
    app, path, _ = api
    url = '/api/nodes/instances/node/harness-process'
    remote = TestClient(app, client=('203.0.113.7', 123))
    assert remote.post(url, json={'action': 'start'}).status_code == 403
    assert remote.get('/api/harnesses/pi/processes').status_code == 403
    path.write_text(json.dumps({'type_id': 'agent_node'}), encoding='utf8')
    assert TestClient(app, client=('127.0.0.1', 123)).get(url).status_code == 400

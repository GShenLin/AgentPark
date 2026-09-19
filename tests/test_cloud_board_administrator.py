import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from fastapi import FastAPI, HTTPException, Request
from starlette.requests import Request as StarletteRequest

from src.peer_network.contracts import BoardHttpRequest, PeerCall, PeerGrant
from src.peer_network.principal import CloudBoardAdministrator, PeerPrincipal
from src.web_backend.access_api import AccessApiDomain
from src.web_backend.peer_board_http import PeerBoardHttp
from src.web_backend.peer_operations import PeerOperations
from src.web_backend.request_access import has_owner_access, is_local_request
from src.web_backend.graph_visibility import GraphVisibilityService


def request_for(principal=None):
    return StarletteRequest({'type': 'http', 'client': ('198.51.100.1', 1234),
        'headers': [(b'x-agentpark-role', b'developer'), (b'x-agentpark-client-id', b'local')],
        'state': {'peer_principal': principal} if principal else {}})


def test_only_verified_board_administrator_receives_owner_permissions():
    admin = request_for(CloudBoardAdministrator('a' * 64, 'Cloud admin'))
    assert has_owner_access(admin)
    assert not is_local_request(admin)
    assert AccessApiDomain().message_access_metadata(admin)['_access_role'] == 'developer'
    peer = request_for(PeerPrincipal('b' * 64, 'Other device'))
    assert not has_owner_access(peer)
    assert AccessApiDomain().get_status(peer)['is_developer'] is False
    assert not has_owner_access(request_for())
    assert AccessApiDomain().get_status(request_for())['is_developer'] is False


def test_board_config_save_and_message_metadata_use_admin_identity():
    app = FastAPI()
    @app.post('/api/nodes/instances/agent/config')
    async def save(payload: dict, request: Request):
        AccessApiDomain().require_developer(request)
        return {'saved': payload, 'metadata': AccessApiDomain().message_access_metadata(request)}
    bridge = PeerBoardHttp(None, app)
    reply = asyncio.run(bridge('a' * 64, BoardHttpRequest(method='POST',
        path='/api/nodes/instances/agent/config', headers={'content-type': 'application/json'},
        body=base64.b64encode(json.dumps({'tools': ['terminal']}).encode()).decode())))
    assert reply['status'] == 200
    payload = json.loads(base64.b64decode(reply['body']))
    assert payload['saved']['tools'] == ['terminal']
    assert payload['metadata']['_access_role'] == 'developer'


def test_ordinary_peer_cannot_use_the_admin_http_dispatcher():
    operations = PeerOperations(None, None)
    grant = PeerGrant(peer_id='b' * 64, name='Peer', view=True, control=True, collaborate=True)
    with pytest.raises(PermissionError):
        operations.execute(grant, PeerCall(operation='board_http', http=BoardHttpRequest(method='GET', path='/api/settings')))


def test_private_graph_visibility_is_granted_to_admin_but_not_ordinary_peer():
    host = SimpleNamespace(graph_runtime=SimpleNamespace(_sanitize_graph_id=lambda value: value),
        _graph_is_private=lambda graph_id: True)
    admin = request_for(CloudBoardAdministrator('a' * 64, 'Admin'))
    GraphVisibilityService.require_graph_visible(host, 'private-graph', admin)
    with pytest.raises(HTTPException) as error:
        GraphVisibilityService.require_graph_visible(host, 'private-graph', request_for(PeerPrincipal('b' * 64, 'Peer')))
    assert error.value.status_code == 404


def test_admin_bridge_still_rejects_external_urls_and_path_traversal():
    bridge = PeerBoardHttp(None, FastAPI())
    for path in ['https://example.com/api/settings', '//example.com/api/settings', '/api/../secret', '/api/%2e%2e/secret', '/etc/passwd']:
        reply = asyncio.run(bridge('a' * 64, BoardHttpRequest(method='GET', path=path)))
        assert reply['status'] == 403

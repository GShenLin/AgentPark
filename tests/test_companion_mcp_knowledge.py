"""Knowledge discovery and access through the real AgentPark MCP protocol."""
import json
import sqlite3
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from openpyxl import Workbook
from starlette.testclient import TestClient

from src.knowledge.catalog import Catalog
from src.knowledge.contracts import LibraryConfig, LibraryUpdate
from src.knowledge.database import Database
from src.knowledge.indexer import embed_pending
from src.knowledge.parser import parse_pending
from src.knowledge.scanner import begin_scan, scan
from src.knowledge.skill import execute
from src.web_backend.companion_mcp import build_companion_mcp


@pytest.fixture
def endpoint(tmp_path):
    folder = tmp_path / 'notes'
    folder.mkdir()
    (folder / 'cats.md').write_text('Cats enjoy sunshine.\n', encoding='utf-8')
    book = Workbook()
    book.active.append([2])
    book.active.append([3])
    book.save(folder / 'numbers.xlsx')
    book.close()
    catalog = Catalog(tmp_path)
    config = LibraryConfig(name='Public notes', folder=str(folder),
                           embedding_url='http://localhost:1/v1', embedding_model='test',
                           dimensions=8, allow_mcp=True, api_key_alias='private-key-alias')
    public = catalog.create(config)['id']
    private = catalog.create(config.model_copy(update={'name': 'Private notes', 'allow_mcp': False}))['id']
    store = Database(catalog.directory(public))
    store.initialize()
    begin_scan(store)
    stop = threading.Event()
    scan(store, folder, stop)
    parse_pending(store, config, stop)
    class Embedder:
        def embed(self, texts):
            return [[1.0] * 8 for _ in texts]

    embed_pending(store, config, stop, Embedder())
    mcp = build_companion_mcp(SimpleNamespace(knowledge_service=SimpleNamespace(catalog=catalog)))

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount('/mcp', mcp.streamable_http_app())
    with TestClient(app) as client:
        def rpc(method, params):
            response = client.post('/mcp/', headers={'Accept': 'application/json, text/event-stream'},
                                   json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
            assert response.status_code == 200, response.text
            return json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith('data: ')))['result']

        rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                           'clientInfo': {'name': 'knowledge-test', 'version': '1.0'}})
        yield catalog, public, private, rpc


def call(rpc, request=None):
    result = rpc('tools/call', {'name': 'get_knowledge', 'arguments': {} if request is None else {'request': request}})
    assert not result.get('isError'), result
    return result['structuredContent']


def test_discovery_schema_and_read_operations(endpoint):
    catalog, public, private, rpc = endpoint
    tool = next(t for t in rpc('tools/list', {})['tools'] if t['name'] == 'get_knowledge')
    schemas = tool['inputSchema']['$defs']
    assert schemas['SearchLibrary']['properties']['mode']['enum'] == ['hybrid', 'semantic', 'keyword']
    assert schemas['TableQuery']['additionalProperties'] is False
    discovered = call(rpc)
    assert discovered['libraries'] == [{'id': public, 'name': 'Public notes', 'access': 'read_only'}]
    assert private not in json.dumps(discovered)
    assert 'private-key-alias' not in json.dumps(discovered)
    assert str(catalog.workspace) not in json.dumps(discovered)
    docs = call(rpc, {'action': 'list', 'library_id': public, 'limit': 1})
    assert len(docs['items']) == 1 and docs['next_cursor'] is not None
    next_docs = call(rpc, {'action': 'list', 'library_id': public, 'after': docs['next_cursor']})
    assert len(next_docs['items']) == 1
    hit = call(rpc, {'action': 'search', 'library_id': public, 'query': 'cats', 'mode': 'keyword'})['matches'][0]
    assert hit['path'] == 'cats.md' and hit['line'] == 1
    passage = call(rpc, {'action': 'read', 'library_id': public, 'chunk_id': hit['chunk_id']})
    assert passage['text'] == hit['text']
    document = call(rpc, {'action': 'read', 'library_id': public, 'document_id': hit['document_id']})
    assert 'Cats enjoy sunshine' in json.dumps(document)
    sheet = next(doc for doc in docs['items'] + next_docs['items'] if doc['path'].endswith('.xlsx'))
    result = call(rpc, {'action': 'table', 'library_id': public, 'document_id': sheet['id'],
                        'sheet': 'Sheet', 'metrics': [{'name': 'total', 'op': 'sum', 'column': 'A'}]})
    assert result['groups'][0]['metrics']['total']['value'] == '5'


@pytest.mark.parametrize('operation', [
    {'action': 'list'}, {'action': 'search', 'query': 'cats', 'mode': 'keyword'},
    {'action': 'read', 'chunk_id': 1},
    {'action': 'table', 'document_id': 1, 'sheet': 'Sheet', 'metrics': [{'name': 'rows', 'op': 'count_rows'}]},
])
def test_visibility_checked_on_every_call_and_independent_of_nodes(endpoint, operation):
    catalog, public, private, rpc = endpoint
    call(rpc)  # Discovery grants no lasting permission after the setting is disabled.
    for key in (private, 'unknown'):
        assert call(rpc, {**operation, 'library_id': key})['error']['code'] == 'knowledge_not_available'
    config = catalog.get(public)
    updated = catalog.update(public, LibraryUpdate(**{**config.model_dump(), 'allow_mcp': False}))
    assert updated['index_changed'] is False
    assert call(rpc)['libraries'] == []
    assert call(rpc, {**operation, 'library_id': public})['error']['code'] == 'knowledge_not_available'
    assert execute(catalog.workspace, {'action': 'list'}, library_ids=(public,))['libraries'][0]['id'] == public
    assert execute(catalog.workspace, {'action': 'list', 'library_id': public}, library_ids=(public,))['items']


@pytest.mark.parametrize('payload', [
    {'action': 'delete', 'library_id': 'id'},
    {'action': 'search', 'library_id': 'id'},
    {'action': 'read', 'library_id': 'id', 'chunk_id': True},
    {'action': 'read', 'library_id': 'id', 'chunk_id': 1, 'document_id': 1},
    {'action': 'list', 'library_id': 'id', 'allow_mcp': True},
])
def test_invalid_requests_fail_at_protocol_boundary(endpoint, payload):
    result = endpoint[3]('tools/call', {'name': 'get_knowledge', 'arguments': {'request': payload}})
    assert result['isError'] is True


@pytest.mark.parametrize('allowed', [True, False])
def test_visibility_migration_preserves_setting_and_index(tmp_path, allowed):
    catalog = Catalog(tmp_path)
    catalog.path.parent.mkdir()
    raw = LibraryConfig(name='Existing', folder=str(tmp_path), embedding_url='http://localhost:1/v1',
                        embedding_model='test', dimensions=8).model_dump()
    raw['allow_agents'] = allowed
    del raw['allow_mcp']
    with sqlite3.connect(catalog.path) as db:
        db.execute('CREATE TABLE libraries(id TEXT PRIMARY KEY,config TEXT NOT NULL,generation INTEGER NOT NULL)')
        db.execute('CREATE TABLE index_configs(library_id TEXT,generation INTEGER,config TEXT)')
        db.execute('INSERT INTO libraries VALUES(?,?,?)', ('old', json.dumps(raw), 3))
        db.execute('INSERT INTO index_configs VALUES(?,?,?)', ('old', 2, json.dumps(raw)))
    for _ in range(2):
        assert catalog.get('old').allow_mcp is allowed
        assert catalog.directory('old') == tmp_path / 'data/knowledge/old/generations/3'
    with sqlite3.connect(catalog.path) as db:
        for table in ('libraries', 'index_configs'):
            config = json.loads(db.execute(f'SELECT config FROM {table}').fetchone()[0])
            assert 'allow_agents' not in config
            assert config['allow_mcp'] is allowed

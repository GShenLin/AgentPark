import base64
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.web_backend.node_sync.blobs import BlobStore, digest, read_json, write_json, CHUNK_SIZE
from src.web_backend.node_sync.contracts import Chunk, Prepare, Selection, SyncRequest, SyncConflict
from src.web_backend.node_sync.service import SyncService
from src.web_backend.node_sync import memory, journal
from src.web_backend.node_memory_store import load_recent_node_memory_records
from src.web_backend.node_memory_records import write_jsonl_records, read_jsonl_records
from src.web_backend.runtime_state_memory_store import runtime_state_memory_store
from src.agent_groups.contracts import AgentGroup, GroupMember, GroupBounds
from src.agent_groups.repository import GroupRepository


def record(id, role, text='hello'):
    return {'id': id, 'role': role, 'parts': [{'type': 'text', 'text': text}],
            'created_at': '2026-09-27 10:00:00.000000'}


def core_for(root):
    def visible(graph, request):
        if not (root / graph / 'config.json').exists():
            raise HTTPException(404, 'graph not found')
    def nodes(graph, request=None):
        return {'nodes': [read_json(p) for p in (root / graph).glob('*/config.json')]}
    runtime = SimpleNamespace(_sanitize_graph_id=lambda v: v, _sanitize_node_id=lambda v: v,
        _graph_dir=lambda g: str(root / g),
        _node_config_path=lambda n, g: str(root / g / n / 'config.json'),
        _node_messages_path=lambda n, g: str(root / g / n / 'messages.jsonl'))
    return SimpleNamespace(graph_runtime=runtime, graph_api=SimpleNamespace(require_graph_visible=visible,
        list_graphs=lambda request: {'graphs': [{'id': p.parent.name, 'name': p.parent.name} for p in root.glob('*/config.json')]}),
        node_ops=SimpleNamespace(list_node_instance_configs=nodes),
        access_api=SimpleNamespace(require_developer=lambda request: None))


def make_node(root, graph, node):
    write_json(root / graph / 'config.json', {'id': graph, 'name': graph, 'output_routes': {}})
    directory = root / graph / node
    write_json(directory / 'config.json', {'schemaVersion': 1, 'node_id': node, 'name': node,
               'graph_id': graph, 'type_id': 'agent_node', 'tools': ['system_tool']})
    return directory


@pytest.fixture
def pair(tmp_path):
    roots = [tmp_path / 'host-a', tmp_path / 'host-b']
    directories = [make_node(roots[0], 'source', 'Agent'), make_node(roots[1], 'target', 'Worker')]
    services = [SyncService(core_for(root), root / '.sync') for root in roots]
    return roots, directories, services


def transfer(source, target, selected, destination):
    exported = source.export(selected, None)
    for sha in [exported['manifest'], *exported['blobs']]:
        state = target.blobs.status(sha)
        while not state['complete']:
            chunk = Chunk.model_validate(source.blobs.read(sha, state['offset']))
            state = target.blobs.write(sha, chunk)
    return target.prepare(Prepare(manifest=exported['manifest'], target=destination), None)


def finish(target, preview):
    target.apply(preview['ticket'], -1, None)
    for index in range(preview['nodes']):
        target.apply(preview['ticket'], index, None)


def test_archive_resources_repeat_edits_conflicts_and_roundtrip(pair):
    roots, (a, b), (source, target) = pair
    attachment = roots[0] / 'image.png'
    attachment.write_bytes(b'image' * 90000)
    user = record('u1', 'user')
    user['parts'].append({'type': 'resource', 'resource': {'id': 'image1', 'uri': str(attachment),
                          'kind': 'image', 'name': 'image.png'}})
    archived = a / 'archive/2026-09-27/messages.jsonl'
    write_jsonl_records(str(archived), [user, record('p1', 'assistant_progress'),
                        record('t1', 'tool'), record('f1', 'assistant'), record('m1', 'metadata')])
    write_jsonl_records(str(a / 'messages.jsonl'), [record('u2', 'user'), record('f2', 'assistant')])
    write_jsonl_records(str(b / 'messages.jsonl'), [record('native-u', 'user'), record('native-f', 'assistant')])
    src, dst = Selection(graph_id='source', node_id='Agent'), Selection(graph_id='target', node_id='Worker')
    first = transfer(source, target, src, dst)
    assert first['added'] == 4 and first['attachments'] == 1
    assert not (b / 'archive/2026-09-27/messages.jsonl').exists()  # preview does not write history
    finish(target, first)
    saved = [r for rows in memory.files(b).values() for r in rows]
    assert {r['id'] for r in saved} == {'u1', 'f1', 'u2', 'f2', 'native-u', 'native-f'}
    moved_image = Path(next(r for r in saved if r['id'] == 'u1')['parts'][1]['resource']['uri'])
    assert moved_image.read_bytes() == attachment.read_bytes() and moved_image != attachment
    second = transfer(source, target, src, dst)
    assert second['added'] == 0 and second['updated'] == 0 and second['unchanged'] == 4
    finish(target, second)
    roundtrip = transfer(target, source, dst, src)
    assert roundtrip['added'] == 2 and not roundtrip['conflicts']
    finish(source, roundtrip)
    updated = read_jsonl_records(str(archived))
    next(r for r in updated if r['id'] == 'f1')['parts'][0]['text'] = 'corrected'
    write_jsonl_records(str(archived), updated)
    change = transfer(source, target, src, dst)
    assert change['updated'] == 1
    finish(target, change)
    imported_archive = b / 'archive/2026-09-27/messages.jsonl'
    local = read_jsonl_records(str(imported_archive))
    next(r for r in local if r['id'] == 'f1')['parts'][0]['text'] = 'local edit'
    write_jsonl_records(str(imported_archive), local)
    conflict = transfer(source, target, src, dst)
    assert len(conflict['conflicts']) == 1
    with pytest.raises(SyncConflict):
        finish(target, conflict)


def test_late_reply_stays_in_original_turn_and_archive_move_is_not_new(pair):
    _, (a, b), (source, target) = pair
    src, dst = Selection(graph_id='source', node_id='Agent'), Selection(graph_id='target', node_id='Worker')
    write_jsonl_records(str(a / 'messages.jsonl'), [record('u1', 'user')])
    finish(target, transfer(source, target, src, dst))
    with (b / 'messages.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record('other', 'user')) + '\n')
    write_jsonl_records(str(a / 'messages.jsonl'), [])
    write_jsonl_records(str(a / 'archive/2026-09-27/messages.jsonl'), [record('u1', 'user'), record('f1', 'assistant')])
    delta = transfer(source, target, src, dst)
    assert delta['added'] == 1 and delta['unchanged'] == 1
    finish(target, delta)
    assert [r['id'] for r in read_jsonl_records(str(b / 'messages.jsonl'))] == ['u1', 'f1', 'other']


def test_busy_destination_does_not_change_memory_and_can_retry(pair):
    _, (a, b), (source, target) = pair
    write_jsonl_records(str(a / 'messages.jsonl'), [record('u1', 'user'), record('f1', 'assistant')])
    preview = transfer(source, target, Selection(graph_id='source', node_id='Agent'),
                       Selection(graph_id='target', node_id='Worker'))
    runtime_state_memory_store.replace(str(b / 'config.json'), {'state': 'working', 'inflight': {}})
    with pytest.raises(ValueError, match='正在执行'):
        finish(target, preview)
    assert not (b / 'messages.jsonl').exists()
    runtime_state_memory_store.replace(str(b / 'config.json'), {'state': 'idle'})
    finish(target, preview)
    assert len(read_jsonl_records(str(b / 'messages.jsonl'))) == 2


def test_complete_graph_structure_and_groups_without_dispatch(pair):
    roots, (a, b), (source, target) = pair
    second = make_node(roots[0], 'source', 'Animation')
    write_jsonl_records(str(second / 'messages.jsonl'), [record('anim-u', 'user'), record('anim-f', 'assistant')])
    config = read_json(a / 'config.json')
    config['WorkingDirectory'] = 'C:\\Project\\BBQ'
    config['state'] = 'working'
    config['pending'] = [{'payload': 'must not replay'}]
    write_json(a / 'config.json', config)
    repo = GroupRepository(a.parent)
    group = AgentGroup(id='team', name='Team', bounds=GroupBounds(x=0, y=0, width=600, height=320),
        members=[GroupMember(node_id='Agent'), GroupMember(node_id='Animation')],
        created_at='2026-09-27', updated_at='2026-09-27')
    with repo.transaction() as db:
        repo.save(db, group, bump=False)
        db.executemany('INSERT INTO members VALUES(?,?)', [('Agent', 'team'), ('Animation', 'team')])
    preview = transfer(source, target, Selection(graph_id='source'), Selection(graph_id='target'))
    assert preview['nodes'] == 2 and preview['structure_files'] == 3 and preview['groups_changed'] == 1
    finish(target, preview)
    imported = read_json(b.parent / 'Agent/config.json')
    assert imported['graph_id'] == 'target' and 'pending' not in imported and 'state' not in imported
    assert (b / 'config.json').is_file()  # target-only nodes preserved
    target_repo = GroupRepository(b.parent)
    assert len(target_repo.get('team').members) == 2
    assert target_repo.pending_deliveries() == []
    repeat = transfer(source, target, Selection(graph_id='source'), Selection(graph_id='target'))
    assert repeat['structure_files'] == 0 and repeat['groups_changed'] == 0 and repeat['added'] == 0


def test_blob_resume_and_checksum(tmp_path):
    store = BlobStore(tmp_path)
    import hashlib
    data = b'x' * (CHUNK_SIZE + 10)
    sha = hashlib.sha256(data).hexdigest()
    first = Chunk(offset=0, total=len(data), data=base64.b64encode(data[:CHUNK_SIZE]).decode())
    assert store.write(sha, first)['offset'] == CHUNK_SIZE
    fresh = BlobStore(tmp_path)
    assert fresh.status(sha)['offset'] == CHUNK_SIZE
    last = Chunk(offset=CHUNK_SIZE, total=len(data), data=base64.b64encode(data[CHUNK_SIZE:]).decode())
    assert fresh.write(sha, last)['complete']
    assert fresh.write(sha, last)['complete']  # response lost: retry is harmless
    with pytest.raises(ValueError, match='checksum'):
        store.write('0' * 64, Chunk(offset=0, total=3, data=base64.b64encode(b'bad').decode()))


def test_interrupted_memory_commit_recovered_by_normal_reader(tmp_path):
    directory = tmp_path / 'node'
    changes = {'messages.jsonl': json.dumps(record('u', 'user')) + '\n', 'memory.md': 'rendered'}
    write_json(directory / journal.JOURNAL, changes)
    result = load_recent_node_memory_records(str(directory / 'memory.md'), str(directory / 'messages.jsonl'), limit=None)
    assert result[0]['id'] == 'u' and not (directory / journal.JOURNAL).exists()


def test_scope_validation():
    with pytest.raises(ValueError):
        SyncRequest.model_validate({'source': {'remote_id': 'a', 'graph_id': 'g', 'node_id': 'n'},
                                    'target': {'remote_id': 'b', 'graph_id': 'g'}})


def test_missing_id_and_missing_attachment_are_explicit_errors(pair):
    _, (a, _), (source, _) = pair
    bad = record('u1', 'user')
    del bad['id']
    write_jsonl_records(str(a / 'messages.jsonl'), [bad])
    with pytest.raises(SyncConflict, match='稳定 ID'):
        source.export(Selection(graph_id='source', node_id='Agent'), None)
    user = record('u1', 'user')
    user['parts'].append({'type': 'resource', 'resource': {'uri': str(a / 'missing.png'), 'kind': 'image'}})
    write_jsonl_records(str(a / 'messages.jsonl'), [user])
    with pytest.raises(SyncConflict, match='附件不存在'):
        source.export(Selection(graph_id='source', node_id='Agent'), None)


def test_structure_preserves_private_target_and_rejects_stale_preview(pair):
    roots, (a, b), (source, target) = pair
    target_agent = make_node(roots[1], 'target', 'Agent')
    config = read_json(target_agent / 'config.json')
    config['private'] = True
    write_json(target_agent / 'config.json', config)
    graph = read_json(b.parent / 'config.json')
    graph['private'] = True
    write_json(b.parent / 'config.json', graph)
    preview = transfer(source, target, Selection(graph_id='source'), Selection(graph_id='target'))
    finish(target, preview)
    assert read_json(target_agent / 'config.json')['private']
    assert read_json(b.parent / 'config.json')['private']
    source_config = read_json(a / 'config.json')
    source_config['instruction'] = 'source change'
    write_json(a / 'config.json', source_config)
    preview = transfer(source, target, Selection(graph_id='source'), Selection(graph_id='target'))
    config = read_json(target_agent / 'config.json')
    config['instruction'] = 'target edited after preview'
    write_json(target_agent / 'config.json', config)
    with pytest.raises(SyncConflict, match='预览后'):
        finish(target, preview)
    assert read_json(target_agent / 'config.json')['instruction'] == 'target edited after preview'


def test_execution_claim_cannot_cross_import_transaction(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from src.web_backend.runtime_state_memory_store import RuntimeStateMemoryStore
    store = RuntimeStateMemoryStore()
    path = str(tmp_path / 'config.json')
    entered, release, claim_started, claim_done = [threading.Event() for _ in range(4)]
    def operation():
        entered.set()
        assert release.wait(2)
    def claim():
        claim_started.set()
        store.update(path, lambda state: state.update(state='working'))
        claim_done.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        imported = pool.submit(store.while_quiescent, [path], operation)
        assert entered.wait(1)
        claimed = pool.submit(claim)
        assert claim_started.wait(1)
        assert not claim_done.wait(.05)
        release.set()
        imported.result(2)
        claimed.result(2)
    assert store.snapshot(path)['state'] == 'working'


def test_explicit_clear_resets_sync_relationship_for_fresh_import(pair):
    from src.web_backend.node_memory_store import clear_node_memory
    _, (a, b), (source, target) = pair
    write_jsonl_records(str(a / 'messages.jsonl'), [record('u', 'user'), record('a', 'assistant')])
    src, dst = Selection(graph_id='source', node_id='Agent'), Selection(graph_id='target', node_id='Worker')
    finish(target, transfer(source, target, src, dst))
    clear_node_memory(str(b / 'memory.md'), str(b / 'messages.jsonl'))
    assert read_json(b / '.sync-index.json') == {}
    repeat = transfer(source, target, src, dst)
    assert repeat['added'] == 2 and not repeat['conflicts']

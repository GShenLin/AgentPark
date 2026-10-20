import json

import pytest

from src.agent_groups.contracts import CreateGroup, GroupConflict, PublishMessage
from src.agent_groups.membership import GroupMembership
from src.agent_groups.messages import GroupMessages
from src.agent_groups.node_lifecycle import node_departure, node_rename
from src.agent_groups.deletion_restore import restore_deleted_member
from src.agent_groups.repository import GroupRepository
from src.agent_groups.spatial_membership import SpatialMember


@pytest.fixture
def team(tmp_path):
    repo = GroupRepository(tmp_path)
    membership = GroupMembership(repo)
    group = membership.create(CreateGroup(name='Team', members=[{'node_id': 'first'}, {'node_id': 'second'}],
        bounds={'x': 0, 'y': 0, 'width': 600, 'height': 320}))
    return repo, membership, group


def targets(repo, event):
    return {d['node_id'] for d in repo.pending_deliveries() if d['seq'] == event['seq']}


def test_default_first_member_switch_and_retry_keep_original_recipient(team):
    repo, membership, group = team
    messages = GroupMessages(repo)
    assert group.leader_id == 'first'
    command = PublishMessage(text='Review attachment', request_id='original', attachments=[
        {'uri': 'C:/test/proof.txt', 'kind': 'doc'}])
    original = messages.publish(group.id, command, None)
    assert targets(repo, original) == {'first'}
    assert original['payload']['recipient_id'] == 'first'
    updated = membership.set_leader(group.id, expected_leader_id='first', leader_id='second')
    assert GroupRepository(repo.path.parent).get(group.id).leader_id == 'second'
    assert targets(repo, repo.events(group.id)['events'][-1]) == set()
    assert messages.publish(group.id, command, None) == original
    next_event = messages.publish(group.id, PublishMessage(text='Next request', request_id='next'), None)
    assert targets(repo, next_event) == {'second'}
    assert updated.members == group.members
    with pytest.raises(GroupConflict):
        membership.set_leader(group.id, expected_leader_id='first', leader_id='first')


def test_explicit_broadcast_direct_and_shared_updates_preserve_routing(team):
    repo, _, group = team
    messages = GroupMessages(repo)
    broadcast = messages.publish(group.id, PublishMessage(text='All act', request_id='all', broadcast_reason='User chose all'), None)
    assert targets(repo, broadcast) == {'first', 'second'}
    direct = messages.publish(group.id, PublishMessage(text='Direct', request_id='direct', recipient_id='second'), None)
    assert targets(repo, direct) == {'second'}
    update = messages.publish(group.id, PublishMessage(text='Status', request_id='status', intent='update'), None)
    assert targets(repo, update) == set()


def test_leader_rename_departure_empty_group_and_rejoin(team):
    repo, membership, group = team
    with node_rename(str(repo.path.parent), 'first', 'renamed'):
        pass
    assert repo.get(group.id).leader_id == 'renamed'
    membership.move('renamed', None, expected_source=group.id)
    assert repo.get(group.id).leader_id == 'second'
    membership.move('second', None, expected_source=group.id)
    assert repo.get(group.id).leader_id is None
    with pytest.raises(GroupConflict, match='组长'):
        GroupMessages(repo).publish(group.id, PublishMessage(text='No members', request_id='empty'), None)
    membership.move('renamed', group.id, expected_source=None)
    assert repo.get(group.id).leader_id == 'renamed'


def test_resize_and_delete_restore_never_leave_stale_leader(team):
    repo, membership, group = team
    membership.configure(group.id, group.revision, bounds=group.bounds, layout=[SpatialMember('second', 50, 50)])
    assert repo.get(group.id).leader_id == 'second'
    with node_departure(str(repo.path.parent), 'second', reason='deleted') as snapshot:
        pass
    assert repo.get(group.id).leader_id is None
    with restore_deleted_member(str(repo.path.parent), snapshot):
        pass
    assert repo.get(group.id).leader_id == 'second'


def test_upgrade_persists_first_member_once_without_retargeting_old_messages(team):
    repo, membership, group = team
    old = GroupMessages(repo).publish(group.id, PublishMessage(text='Old broadcast', request_id='old', broadcast_reason='All'), None)
    with repo.transaction() as db:
        document = group.model_dump()
        del document['leader_id']
        db.execute('UPDATE groups SET document=? WHERE id=?', (json.dumps(document), group.id))
        db.execute('PRAGMA user_version=4')
    upgraded = GroupRepository(repo.path.parent)
    assert upgraded.get(group.id).leader_id == 'first'
    assert targets(upgraded, old) == {'first', 'second'}
    membership.set_leader(group.id, expected_leader_id='first', leader_id='second')
    assert GroupRepository(repo.path.parent).get(group.id).leader_id == 'second'
    with repo.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 5

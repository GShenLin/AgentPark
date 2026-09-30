import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from src.agent_groups.agent_tools import GroupAgentTools
from src.agent_groups.contracts import CreateGroup, CreateTask, GroupConflict, PublishMessage, UpdateTask
from src.agent_groups.delivery import GroupDelivery
from src.agent_groups.membership import GroupMembership
from src.agent_groups.messages import GroupMessages
from src.agent_groups.repository import GroupRepository
from src.agent_groups.tasks import GroupTasks


class GroupRoutingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = GroupRepository(Path(temp.name))
        self.members = GroupMembership(self.repo)
        self.group = self.members.create(CreateGroup(name='Team',
            members=[{'node_id': node} for node in ['UI', 'Character', 'Animation', 'PCG', 'VFX', 'Gameplay']],
            bounds={'x': 0, 'y': 0, 'width': 900, 'height': 640}))
        self.tasks = GroupTasks(self.repo)
        self.tools = GroupAgentTools(self.repo, self.group.id, 'UI')

    def targets(self):
        event = self.repo.events(self.group.id)['events'][-1]
        return {d['node_id'] for d in self.repo.pending_deliveries() if d['seq'] == event['seq']}

    def test_shared_update_persists_without_any_wakeup(self):
        event = self.tools.post_update(text='HUD implementation ready; waiting for PIE', request_id='update')
        self.assertEqual(event['kind'], 'update')
        self.assertEqual(self.targets(), set())
        self.assertIn(event, self.repo.events(self.group.id, 'VFX')['events'])
        self.assertEqual(self.tools.post_update(text='HUD implementation ready; waiting for PIE', request_id='update'), event)
        with self.assertRaises(GroupConflict):
            self.tools.message(text='HUD implementation ready; waiting for PIE', request_id='update', recipient_id='Gameplay')

    def test_direct_action_and_explicit_broadcast_are_distinct_contracts(self):
        with self.assertRaises(ValidationError):
            self.tools.message(text='do something', request_id='missing-target')
        with self.assertRaises(GroupConflict):
            GroupMessages(self.repo).publish(self.group.id, PublishMessage(text='implicit broadcast', request_id='bad'), 'UI')
        self.tools.message(text='Integrate HUD', recipient_id='Gameplay', request_id='direct')
        self.assertEqual(self.targets(), {'Gameplay'})
        with self.assertRaises(ValidationError):
            self.tools.broadcast(text='Stop editor writes', broadcast_reason=' ', request_id='empty-reason')
        self.tools.broadcast(text='Stop editor writes', broadcast_reason='Shared editor is restarting; all members must stop writes', request_id='broadcast')
        self.assertEqual(self.targets(), {'Character', 'Animation', 'PCG', 'VFX', 'Gameplay'})

    def test_note_cannot_smuggle_action_and_user_broadcast_is_preserved(self):
        with self.assertRaises(ValidationError):
            PublishMessage(text='note', request_id='invalid', intent='update', recipient_id='PCG')
        GroupMessages(self.repo).publish(self.group.id, PublishMessage(text='New project goal', request_id='user'), None)
        self.assertEqual(len(self.targets()), 6)

    def test_progress_and_plan_edits_are_silent_assignment_is_targeted(self):
        task = self.tasks.create(self.group.id, CreateTask(title='HUD', owner_id='UI'), None)
        self.assertEqual(self.targets(), {'UI'})
        task = self.tasks.update(self.group.id, task.id, UpdateTask(expected_revision=1, status='in_progress'), 'UI')
        self.assertEqual(self.targets(), set())
        task = self.tasks.update(self.group.id, task.id, UpdateTask(expected_revision=task.revision, evidence='tests passed'), 'UI')
        self.assertEqual(self.targets(), set())
        self.tasks.update(self.group.id, task.id, UpdateTask(expected_revision=task.revision, description='Also handle widescreen'), None)
        self.assertEqual(self.targets(), {'UI'})
        group = self.repo.get(self.group.id)
        self.members.configure(group.id, group.revision, objective='Updated shared reference')
        self.assertEqual(self.targets(), set())
        self.tasks.create(self.group.id, CreateTask(title='Unassigned backlog'), None)
        self.assertEqual(self.targets(), set())

    def test_dependency_completion_wakes_only_ready_downstream_owner(self):
        first = self.tasks.create(self.group.id, CreateTask(title='Body', owner_id='Character'), 'Character')
        second = self.tasks.create(self.group.id, CreateTask(title='Interface', owner_id='Gameplay'), 'Gameplay')
        dependent = self.tasks.create(self.group.id, CreateTask(title='Animation', owner_id='Animation',
            dependencies=[first.id, second.id]), 'Character')
        self.assertEqual(self.targets(), set())
        self.tasks.update(self.group.id, first.id, UpdateTask(expected_revision=1, status='done', evidence='Body asset verified'), 'Character')
        self.assertEqual(self.targets(), set())
        self.tasks.update(self.group.id, second.id, UpdateTask(expected_revision=1, status='done', evidence='Interfaces tested'), 'Gameplay')
        self.assertEqual(self.targets(), {'Animation'})
        self.assertEqual(len(GroupDelivery(self.repo).batches()), 1)
        self.tasks.update(self.group.id, dependent.id, UpdateTask(expected_revision=1, status='done', evidence='Actions verified'), 'Animation')
        self.assertEqual(self.targets(), set())

    def test_reassignment_and_dependency_removal_notify_new_ready_owner(self):
        dependency = self.tasks.create(self.group.id, CreateTask(title='Source', owner_id='Character'), 'Character')
        task = self.tasks.create(self.group.id, CreateTask(title='Review', owner_id='Animation', dependencies=[dependency.id]), None)
        task = self.tasks.update(self.group.id, task.id, UpdateTask(expected_revision=1, dependencies=[]), None)
        self.assertEqual(self.targets(), {'Animation'})
        self.tasks.update(self.group.id, task.id, UpdateTask(expected_revision=task.revision, owner_id='Gameplay'), None)
        self.assertEqual(self.targets(), {'Gameplay'})

    def test_title_only_edit_notifies_owner_but_unchanged_save_does_not_duplicate(self):
        task = self.tasks.create(self.group.id, CreateTask(title='Old question', owner_id='Animation'), None)
        task = self.tasks.update(self.group.id, task.id, UpdateTask(expected_revision=1, title='New question'), None)
        self.assertEqual(self.targets(), {'Animation'})
        before = self.repo.events(self.group.id)['events']
        same = self.tasks.update(self.group.id, task.id, UpdateTask(expected_revision=task.revision, title='New question'), None)
        self.assertEqual(same.revision, task.revision)
        self.assertEqual(self.repo.events(self.group.id)['events'], before)

    def test_fork_join_and_same_owner_successor(self):
        source = self.tasks.create(self.group.id, CreateTask(title='Body', owner_id='Character'), 'Character')
        animation = self.tasks.create(self.group.id, CreateTask(title='Motion', owner_id='Animation', dependencies=[source.id]), 'Character')
        appearance = self.tasks.create(self.group.id, CreateTask(title='LOD', owner_id='Character', dependencies=[source.id]), 'Character')
        ui = self.tasks.create(self.group.id, CreateTask(title='Independent HUD', owner_id='UI'), None)
        self.assertEqual(self.targets(), {'UI'})
        join = self.tasks.create(self.group.id, CreateTask(title='Integration', owner_id='Gameplay',
            dependencies=[animation.id, appearance.id, ui.id]), None)
        self.assertEqual(self.targets(), set())
        self.tasks.update(self.group.id, source.id, UpdateTask(expected_revision=1, status='done', evidence='Body ready'), 'Character')
        self.assertEqual(self.targets(), {'Animation', 'Character'})
        for task in [ui, animation]:
            self.tasks.update(self.group.id, task.id, UpdateTask(expected_revision=1, status='done', evidence='Verified'), task.owner_id)
            self.assertEqual(self.targets(), set())
        self.tasks.update(self.group.id, appearance.id, UpdateTask(expected_revision=1, status='done', evidence='LOD verified'), 'Character')
        self.assertEqual(self.targets(), {'Gameplay'})
        self.assertEqual(self.repo.get(self.group.id).tasks[-1].id, join.id)

    def test_queued_task_revalidates_ownership_and_completion_before_waking(self):
        delivery = GroupDelivery(self.repo)
        task = self.tasks.create(self.group.id, CreateTask(title='Review', owner_id='UI'), None)
        original = delivery.batches()[0]['reference']
        task = self.tasks.update(self.group.id, task.id, UpdateTask(expected_revision=1, owner_id='Gameplay'), None)
        self.assertEqual(delivery.resolve('UI', original), [])
        new_reference = next(b['reference'] for b in delivery.batches() if b['node_id'] == 'Gameplay')
        self.tasks.update(self.group.id, task.id, UpdateTask(expected_revision=task.revision, status='done', evidence='Already handled'), 'Gameplay')
        self.assertEqual(delivery.resolve('Gameplay', new_reference), [])
        self.assertEqual(delivery.batches(), [])

    def test_upgrade_preserves_real_assignments_and_cancels_old_broadcast_recipients(self):
        task = self.tasks.create(self.group.id, CreateTask(title='Review', owner_id='UI'), None)
        message = GroupMessages(self.repo).publish(self.group.id,
            PublishMessage(text='User request', request_id='preserve'), None)
        with self.repo.transaction() as db:
            row = db.execute("SELECT seq,payload FROM events WHERE kind='task_created'").fetchone()
            payload = json.loads(row['payload'])
            del payload['action_tasks']
            db.execute('UPDATE events SET payload=? WHERE seq=?', (json.dumps(payload), row['seq']))
            for node in ['PCG', 'VFX']:
                db.execute('INSERT INTO deliveries(event_seq,node_id) VALUES(?,?)', (row['seq'], node))
            db.execute('PRAGMA user_version=3')
        upgraded = GroupRepository(self.repo.path.parent)
        pending = upgraded.pending_deliveries()
        self.assertEqual({d['node_id'] for d in pending if d['seq'] == row['seq']}, {'UI'})
        self.assertEqual(len([d for d in pending if d['seq'] == message['seq']]), 6)
        payload = upgraded.events(self.group.id)['events'][1]['payload']
        self.assertEqual(payload['action_tasks'], {'UI': [task.id]})
        GroupRepository(self.repo.path.parent)
        self.assertEqual(upgraded.pending_deliveries(), pending)


if __name__ == '__main__':
    unittest.main()

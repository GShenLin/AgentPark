import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.agent_groups.contracts import CreateGroup, GroupBounds, GroupMember, PublishMessage
from src.agent_groups.delivery import GroupDelivery
from src.agent_groups.membership import GroupMembership
from src.agent_groups.messages import GroupMessages
from src.agent_groups.repository import GroupRepository
from src.message_protocol import envelope_text
from src.web_backend.group_delivery import GroupDeliveryService, GroupNotificationRun


class GroupDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.graph = Path(self.temp.name) / "game"
        self.graph.mkdir()
        self.repo = GroupRepository(self.graph)
        self.members = GroupMembership(self.repo)
        self.group = self.members.create(CreateGroup(name="Team",
            bounds=GroupBounds(x=0, y=0, width=100, height=100),
            members=[GroupMember(node_id="engine"), GroupMember(node_id="story")]))
        GroupMessages(self.repo).publish(self.group.id,
            PublishMessage(text="Start the assigned work", request_id="initial-work"), None)
        self.delivery = GroupDelivery(self.repo)
        self.queued = {}
        self.events = []
        self.enqueue_error = None

        def enqueue(node, item, *, graph_id):
            if self.enqueue_error:
                raise RuntimeError(self.enqueue_error)
            self.queued.setdefault((graph_id, node, item["idempotency_key"]), item)
            return {"ok": True}

        self.core = SimpleNamespace(node_ops=SimpleNamespace(enqueue_node_instance_pending=enqueue),
                                    graph_events=SimpleNamespace(publish=lambda graph, event: self.events.append((graph, event))))
        self.service = GroupDeliveryService(self.core)

    def queued_for(self, node):
        return next(item for (_, target, _), item in self.queued.items() if target == node)

    def run_for(self, node):
        return GroupNotificationRun(config_path=str(self.graph / node / "config.json"),
                                    node_id=node, envelope=self.queued_for(node)["payload"])

    def test_repeated_create_dissolve_is_audit_only_and_broadcast_still_wakes(self):
        self.members.dissolve(self.group.id, self.repo.get(self.group.id).revision)
        for _ in range(20):
            team = self.members.create(CreateGroup(name="G toggle", bounds=self.group.bounds,
                members=self.group.members))
            self.service.poll_graph(self.graph)
            self.assertEqual(self.queued, {})
            self.members.dissolve(team.id, team.revision)
            self.service.poll_graph(self.graph)
            self.assertEqual(self.queued, {})
        team = self.members.create(CreateGroup(name="Ready", bounds=self.group.bounds, members=self.group.members))
        event = GroupMessages(self.repo).publish(team.id,
            PublishMessage(text="Actual broadcast", request_id="real-work"), None)
        self.service.poll_graph(self.graph)
        self.assertEqual(len(self.queued), 2)
        self.assertEqual([e['seq'] for e in self.run_for('engine').events], [event['seq']])
        self.assertEqual([e['seq'] for e in self.run_for('story').events], [event['seq']])

    def test_upgrade_cancels_old_structural_notices_but_preserves_real_work(self):
        from src.agent_groups.delivery import DeliveryReference
        with self.repo.transaction() as db:
            seq = db.execute("SELECT seq FROM events WHERE kind='group_created'").fetchone()[0]
            db.execute("INSERT INTO deliveries(event_seq,node_id) VALUES(?,?)", (seq, 'engine'))
            db.execute("PRAGMA user_version=1")
        old_reference = DeliveryReference(group_id=self.group.id, event_seqs=[seq])
        upgraded = GroupRepository(self.graph)
        self.assertEqual(GroupDelivery(upgraded).resolve('engine', old_reference), [])
        self.assertEqual({e['kind'] for e in upgraded.pending_deliveries()}, {'message'})
        self.assertEqual(len(upgraded.pending_deliveries()), 2)
        self.assertEqual(len(upgraded.events(self.group.id)['events']), 2)

    def test_user_followup_joins_current_run_and_final_reply_never_wakes_peers(self):
        self.service.poll_graph(self.graph)
        run = self.run_for('engine')
        initial = [event['seq'] for event in run.events]
        self.assertTrue(next(d for d in self.delivery.status(self.group.id) if d['node_id']=='engine')['started_at'])
        followup = GroupMessages(self.repo).publish(self.group.id,
            PublishMessage(text='Please answer my question first', request_id='followup'), None)
        peer = GroupMessages(self.repo).publish(self.group.id,
            PublishMessage(text='Peer work', recipient_id='engine', request_id='peer'), 'story')
        injected = run.consume_followups()
        self.assertEqual(len(injected), 1)
        self.assertIn('Please answer my question first', envelope_text(injected[0]))
        self.assertNotIn('Peer work', envelope_text(injected[0]))
        self.assertEqual(run.consume_followups(), [])
        run.complete(reply='Here is your answer')
        run.complete(reply='Do not duplicate')
        replies = [e for e in self.repo.events(self.group.id)['events'] if e['kind']=='reply']
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]['payload']['request_seqs'], initial+[followup['seq']])
        self.assertEqual(replies[0]['actor_id'], 'engine')
        self.assertFalse(any(d['event_seq']==replies[0]['seq'] for d in self.delivery.status(self.group.id)))
        self.assertTrue(any(d['seq']==peer['seq'] for d in self.repo.pending_deliveries()))

    def test_followup_cannot_cross_access_role_or_revoked_membership(self):
        self.service.poll_graph(self.graph)
        run = self.run_for('engine')
        limited = GroupRepository(self.graph, access_role='nondeveloper')
        GroupMessages(limited).publish(self.group.id, PublishMessage(text='restricted', request_id='followup'), None)
        self.assertEqual(run.consume_followups(), [])
        self.members.move('engine', None, expected_source=self.group.id)
        self.assertEqual(run.consume_followups(), [])
        run.complete(reply='Do not leak after leaving')
        self.assertFalse(any(e['kind']=='reply' for e in self.repo.events(self.group.id)['events']))

    def test_user_task_final_reply_is_visible_once_without_notifying_peers(self):
        from src.agent_groups.contracts import CreateTask, UpdateTask
        from src.agent_groups.tasks import GroupTasks
        # Remove the setup message, so this run is triggered solely by saving a task.
        for node in ('engine', 'story'):
            self.service.poll_graph(self.graph)
            self.run_for(node).complete()
        task_service = GroupTasks(self.repo)
        task = task_service.create(self.group.id, CreateTask(title='Has the animation replacement finished?'), None)
        task_service.update(self.group.id, task.id, UpdateTask(expected_revision=1, owner_id='engine'), None)
        reference = next(b['reference'] for b in self.delivery.batches() if b['node_id'] == 'engine')
        events = self.delivery.resolve('engine', reference)
        self.assertEqual(len(events), 1)
        self.delivery.complete('engine', events, reply='Replacement is not complete; here is the evidence.')
        self.delivery.complete('engine', events, reply='Must not duplicate')
        replies = [e for e in self.repo.events(self.group.id)['events'] if e['kind'] == 'reply']
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]['payload']['task_ids'], [task.id])
        self.assertEqual(replies[0]['payload']['request_seqs'], [events[0]['seq']])
        self.assertFalse(self.repo.pending_deliveries())

    def test_peer_assigned_task_and_failed_user_task_do_not_publish_success_reply(self):
        from src.agent_groups.contracts import CreateTask
        from src.agent_groups.tasks import GroupTasks
        for node in ('engine', 'story'):
            self.service.poll_graph(self.graph)
            self.run_for(node).complete()
        task_service = GroupTasks(self.repo)
        task_service.create(self.group.id, CreateTask(title='Peer assignment', owner_id='engine'), 'story')
        events = self.delivery.resolve('engine', self.delivery.batches()[0]['reference'])
        self.delivery.complete('engine', events, reply='Peer-only completion')
        task_service.create(self.group.id, CreateTask(title='User assignment', owner_id='engine'), None)
        events = self.delivery.resolve('engine', self.delivery.batches()[0]['reference'])
        self.delivery.complete('engine', events, error='Provider failed', reply='Incomplete reply')
        self.assertFalse(any(e['kind'] == 'reply' for e in self.repo.events(self.group.id)['events']))

    def test_latest_history_and_older_pages_have_no_gaps(self):
        for index in range(225):
            with self.repo.transaction() as db:
                self.repo.event(db, self.group, 'reply', 'engine', {'text': str(index)}, recipients=[])
        latest = self.repo.events(self.group.id, latest=True, limit=100)
        self.assertEqual(latest['events'][-1]['payload']['text'], '224')
        self.assertTrue(latest['has_older'])
        older = self.repo.events(self.group.id, before=latest['events'][0]['seq'], limit=100)
        self.assertEqual(older['events'][-1]['seq']+1, latest['events'][0]['seq'])
        self.assertEqual(self.repo.events(self.group.id, after=latest['cursor'])['events'], [])

    def test_attachment_broadcast_survives_restart_and_reaches_each_member_as_resources(self):
        import base64
        from nodes.agent_message_adapter import build_agent_user_content
        image_bytes = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
        image = self.graph / "sample.png"
        image.write_bytes(image_bytes)
        document = self.graph / "brief.txt"
        document.write_text("Group attachment acceptance", encoding="utf-8")
        command = PublishMessage(text="Inspect attached files", request_id="resources", attachments=[
            {"uri": str(image), "name": "sample.png", "kind": "image", "mime": "image/png"},
            {"uri": str(document), "name": "brief.txt", "kind": "doc", "mime": "text/plain"},
        ])
        event = GroupMessages(self.repo).publish(self.group.id, command, None)
        self.assertEqual(len(event["payload"]["attachments"]), 2)
        # Reopen the database/service instead of reusing in-memory payloads.
        self.repo = GroupRepository(self.graph)
        GroupDeliveryService(self.core).poll_graph(self.graph)
        ids = []
        for node in ("engine", "story"):
            run = self.run_for(node)
            resources = [p["resource"] for p in run.message["parts"] if p["type"] == "resource"]
            self.assertEqual([r["uri"] for r in resources], [str(image), str(document)])
            self.assertEqual(resources[0]["metadata"]["event_seq"], event["seq"])
            ids.append([r["id"] for r in resources])
            content = build_agent_user_content("GPT_Official", "chat", run.message)
            self.assertEqual(content[-1], {"type": "image_url", "image_url": {
                "url": "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")}})
            self.assertIn(str(document), content[0]["text"])
            run.complete()
        self.assertEqual(ids[0], ids[1])
        self.assertFalse(self.repo.pending_deliveries())

    def test_private_attachment_is_not_delivered_to_other_member_or_after_leaving(self):
        command = PublishMessage(request_id="private-resource", recipient_id="engine", attachments=[
            {"uri": "C:/private/story.txt", "name": "story.txt", "kind": "doc"}])
        GroupMessages(self.repo).publish(self.group.id, command, "story")
        self.service.poll_graph(self.graph)
        self.assertFalse(any(p["type"] == "resource" for p in self.run_for("story").message["parts"]))
        self.members.move("engine", None, expected_source=self.group.id)
        self.assertFalse(any(p["type"] == "resource" for p in self.run_for("engine").message["parts"]))

    def test_queue_retry_is_stable_and_outbox_survives_lost_memory_queue(self):
        self.service.poll_graph(self.graph)
        self.service.poll_graph(self.graph)
        self.assertEqual(len(self.queued), 2)
        self.assertEqual(len(self.repo.pending_deliveries()), 2)
        original_keys = set(self.queued)
        self.queued.clear()  # Simulate runtime restart losing its in-memory queue.
        GroupDeliveryService(self.core).poll_graph(self.graph)
        self.assertEqual(set(self.queued), original_keys)
        run = self.run_for("engine")
        self.assertIn("Start the assigned work", envelope_text(run.message))
        run.complete()
        self.assertEqual([item["node_id"] for item in self.repo.pending_deliveries()], ["story"])
        self.assertEqual(self.run_for("engine").events, [])

    def test_busy_member_queues_new_tasks_without_replaying_consumed_batch(self):
        from src.agent_groups.contracts import CreateTask
        from src.agent_groups.tasks import GroupTasks
        self.service.poll_graph(self.graph)
        active = self.run_for('engine')
        old_sequences = {e['seq'] for e in active.events}
        tasks = GroupTasks(self.repo)
        for title in ['Independent UI review', 'Second review queued for same member']:
            tasks.create(self.group.id, CreateTask(title=title, owner_id='engine'), None)
        self.service.poll_graph(self.graph)
        self.assertEqual(len(self.queued), 2)  # One anchor per member, even while busy.
        self.assertEqual({e['seq'] for e in active.events}, old_sequences)
        active.complete()
        self.service.poll_graph(self.graph)
        new_batches = [batch for batch in self.delivery.batches() if batch['node_id'] == 'engine']
        self.assertEqual(len(new_batches), 1)
        pending = self.delivery.resolve('engine', new_batches[0]['reference'])
        self.assertEqual(len(pending), 2)
        self.assertTrue(all(e['kind'] == 'task_created' for e in pending))
        self.assertFalse(old_sequences & {e['seq'] for e in pending})

    def test_queue_contains_reference_only_and_leaving_revokes_queued_content(self):
        GroupMessages(self.repo).publish(self.group.id, PublishMessage(text="private plot draft", request_id="story", recipient_id="engine"), "story")
        self.service.poll_graph(self.graph)
        self.assertNotIn("private plot draft", str(self.queued_for("engine")))
        self.members.move("engine", None, expected_source=self.group.id)
        self.assertEqual(self.run_for("engine").events, [])

    def test_batches_coalesce_events_but_private_messages_only_reach_target(self):
        for index in range(5):
            GroupMessages(self.repo).publish(self.group.id,
                PublishMessage(text=f"draft {index}", recipient_id="engine", request_id=str(index)), "story")
        self.service.poll_graph(self.graph)
        self.assertEqual(len(self.queued), 2)
        self.assertEqual(len(self.run_for("engine").events), 6)
        self.assertEqual(len(self.run_for("story").events), 1)
        self.assertEqual(self.events[0][1], {"event": "groups_changed"})

    def test_enqueue_error_remains_retryable_and_terminal_execution_error_is_visible(self):
        self.enqueue_error = "queue unavailable"
        with self.assertLogs("src.web_backend.group_delivery", level="ERROR"):
            self.service.poll_graph(self.graph)
        pending = self.repo.pending_deliveries()
        self.assertEqual(len(pending), 2)
        self.assertTrue(all("queue unavailable" in item["last_error"] for item in pending))
        self.enqueue_error = None
        self.service.retry_at.clear()
        self.service.poll_graph(self.graph)
        self.run_for("engine").complete(error="Provider rejected request")
        row = next(item for item in self.delivery.status(self.group.id) if item["node_id"] == "engine")
        self.assertEqual(row["state"], "delivered")
        self.assertEqual(row["last_error"], "Provider rejected request")
        self.assertEqual(self.run_for("engine").events, [])

    def test_dissolution_cancels_pending_work_without_notifying_former_members(self):
        self.members.dissolve(self.group.id, self.group.revision)
        self.service.poll_graph(self.graph)
        self.assertEqual(self.queued, {})
        self.assertEqual(self.repo.pending_deliveries(), [])

    def test_restricted_sender_does_not_gain_developer_tools_through_teammates(self):
        limited = GroupRepository(self.graph, access_role="nondeveloper")
        GroupMessages(limited).publish(self.group.id, PublishMessage(text="request", request_id="restricted", recipient_id="engine"), "story")
        self.service.poll_graph(self.graph)
        items = [item for (_, node, _), item in self.queued.items() if node == "engine"]
        self.assertEqual(len(items), 2)  # Separate batches for separate access contexts.
        restricted = next(item for item in items if item["_access_role"] == "nondeveloper")
        run = GroupNotificationRun(config_path=str(self.graph / "engine" / "config.json"),
                                  node_id="engine", envelope=restricted["payload"])
        self.assertEqual(run.access_role, "nondeveloper")

    def test_busy_recipient_backlog_does_not_starve_another_recipient(self):
        for batch in self.delivery.batches():
            self.delivery.complete(batch['node_id'], self.delivery.resolve(batch['node_id'], batch['reference']))
        for index in range(8):
            GroupMessages(self.repo).publish(self.group.id,
                PublishMessage(text=f'engine work {index}', recipient_id='engine', request_id=f'engine-{index}'), 'story')
        GroupMessages(self.repo).publish(self.group.id,
            PublishMessage(text='review ready', recipient_id='story', request_id='review'), 'engine')
        limited = self.repo.pending_deliveries(limit=2)
        self.assertEqual({item['node_id'] for item in limited}, {'engine', 'story'})

    def test_updates_while_waiting_use_one_wakeup_and_resolve_current_batch(self):
        self.service.poll_graph(self.graph)
        original_keys = set(self.queued)
        for index in range(8):
            GroupMessages(self.repo).publish(self.group.id,
                PublishMessage(text=f'handoff {index}', recipient_id='engine', request_id=f'burst-{index}'), 'story')
            self.service.poll_graph(self.graph)
        self.assertEqual(set(self.queued), original_keys)
        run = self.run_for('engine')
        self.assertEqual(len(run.events), 9)
        run.complete()
        self.assertEqual(self.run_for('engine').events, [])

    def test_batch_is_bounded_and_updates_during_execution_remain_pending(self):
        self.service.poll_graph(self.graph)
        for index in range(105):
            GroupMessages(self.repo).publish(self.group.id,
                PublishMessage(text=f'work {index}', recipient_id='engine', request_id=f'bounded-{index}'), 'story')
        run = self.run_for('engine')
        self.assertEqual(len(run.events), 100)
        GroupMessages(self.repo).publish(self.group.id,
            PublishMessage(text='arrived during execution', recipient_id='engine', request_id='during'), 'story')
        run.complete()
        self.assertEqual(self.run_for('engine').events, [])
        self.queued.clear()
        self.service.poll_graph(self.graph)
        next_run = self.run_for('engine')
        self.assertEqual(len(next_run.events), 7)
        self.assertIn('arrived during execution', envelope_text(next_run.message))
        next_run.complete()
        self.assertFalse(any(item['node_id'] == 'engine' for item in self.repo.pending_deliveries()))

    def test_current_batch_never_merges_access_roles(self):
        self.service.poll_graph(self.graph)
        limited = GroupRepository(self.graph, access_role='nondeveloper')
        GroupMessages(limited).publish(self.group.id,
            PublishMessage(text='restricted handoff', recipient_id='engine', request_id='restricted-late'), 'story')
        self.service.poll_graph(self.graph)
        developer_run = self.run_for('engine')
        self.assertEqual(developer_run.access_role, 'developer')
        self.assertNotIn('restricted handoff', envelope_text(developer_run.message))
        developer_run.complete()
        self.assertTrue(any(item['payload'].get('text') == 'restricted handoff' for item in self.repo.pending_deliveries()))


if __name__ == "__main__":
    unittest.main()

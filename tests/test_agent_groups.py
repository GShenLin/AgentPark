import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import ValidationError

from src.agent_groups.contracts import (
    CreateGroup, CreateTask, GroupBounds, GroupConflict, GroupMember,
    GroupNotFound, GroupPermissionError, PublishMessage, UpdateTask,
)
from src.agent_groups.spatial_membership import SpatialMember
from src.agent_groups.membership import GroupMembership
from src.agent_groups.messages import GroupMessages
from src.agent_groups.repository import GroupRepository
from src.agent_groups.tasks import GroupTasks


class AgentGroupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.repo = GroupRepository(self.directory)
        self.members = GroupMembership(self.repo)
        self.tasks = GroupTasks(self.repo)
        self.messages = GroupMessages(self.repo)
        self.group = self.members.create(CreateGroup(
            name="Game team", bounds=GroupBounds(x=0, y=0, width=600, height=400),
            members=[GroupMember(node_id=node) for node in ("engine", "story", "qa")],
        ))

    def create_task(self, **kwargs):
        return self.tasks.create(self.group.id, CreateTask(title="Build level", **kwargs), "engine")

    def test_persistent_membership_and_board_do_not_touch_graph_config(self):
        config = self.directory / "config.json"
        config.write_text('{"name":"existing graph"}', encoding="utf-8")
        task = self.create_task()
        reopened = GroupRepository(self.directory)
        self.assertEqual(reopened.member_group("story").id, self.group.id)
        self.assertEqual(reopened.get(self.group.id).tasks[0].id, task.id)
        self.assertEqual(config.read_text(), '{"name":"existing graph"}')

    def test_duplicate_membership_creation_rolls_back(self):
        with self.assertRaises(GroupConflict):
            self.members.create(CreateGroup(name="Duplicate", bounds=self.group.bounds,
                                members=[GroupMember(node_id="new"), GroupMember(node_id="engine")]))
        self.assertEqual(len(self.repo.list()), 1)
        self.assertIsNone(self.repo.member_group("new"))

    def test_role_edit_is_audit_only_and_ignores_unrelated_task_revisions(self):
        self.create_task(owner_id="qa")
        updated = self.members.update_role(self.group.id, "story", expected_role="", role="Narrative")
        self.assertEqual(next(m.role for m in updated.members if m.node_id == "story"), "Narrative")
        events = self.repo.events(self.group.id)["events"]
        event = events[-1]
        self.assertEqual(event["kind"], "member_role_updated")
        self.assertEqual(event["payload"]["member"], {"node_id": "story", "role": "Narrative"})
        recipients = {d["node_id"] for d in self.repo.pending_deliveries() if d["seq"] == event["seq"]}
        self.assertEqual(recipients, set())
        self.members.update_role(self.group.id, "story", expected_role="Narrative", role="Narrative")
        self.assertEqual(len(self.repo.events(self.group.id)["events"]), len(events))
        with self.assertRaises(GroupConflict):
            self.members.update_role(self.group.id, "story", expected_role="", role="Overwrite")
        self.members.move("story", None, expected_source=self.group.id)
        with self.assertRaises(GroupConflict):
            self.members.update_role(self.group.id, "story", expected_role="Narrative", role="Returned")

    def test_concurrent_claim_has_one_winner_and_one_event(self):
        task = self.create_task()

        def claim(node_id):
            try:
                return self.tasks.update(self.group.id, task.id, UpdateTask(
                    expected_revision=1, owner_id=node_id, status="in_progress"), node_id).owner_id
            except GroupConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ["engine", "story"]))
        self.assertEqual(results.count("conflict"), 1)
        self.assertIn(self.repo.get(self.group.id).tasks[0].owner_id, ("engine", "story"))
        events = self.repo.events(self.group.id)["events"]
        self.assertEqual(sum(event["kind"] == "task_updated" for event in events), 1)

    def test_owned_task_cannot_be_overwritten_by_peer(self):
        task = self.create_task(owner_id="engine")
        with self.assertRaises(GroupPermissionError):
            self.tasks.update(self.group.id, task.id, UpdateTask(expected_revision=1, title="Hijack"), "story")
        self.assertEqual(self.repo.get(self.group.id).tasks[0].revision, 1)

    def test_dependencies_cycles_evidence_and_reopening(self):
        first = self.create_task(owner_id="engine")
        second = self.create_task(owner_id="qa", dependencies=[first.id])
        with self.assertRaises(GroupConflict):
            self.tasks.update(self.group.id, first.id, UpdateTask(expected_revision=1, dependencies=[second.id]), "engine")
        with self.assertRaises(GroupConflict):
            self.tasks.update(self.group.id, second.id, UpdateTask(expected_revision=1, status="in_progress"), "qa")
        with self.assertRaises(GroupConflict):
            self.tasks.update(self.group.id, first.id, UpdateTask(expected_revision=1, status="done"), "engine")
        self.tasks.update(self.group.id, first.id, UpdateTask(expected_revision=1, status="done", evidence="Passed level tests"), "engine")
        self.tasks.update(self.group.id, second.id, UpdateTask(expected_revision=1, status="in_progress"), "qa")
        with self.assertRaises(GroupConflict):
            self.tasks.update(self.group.id, first.id, UpdateTask(expected_revision=2, status="todo"), "engine")

    def test_noop_task_edit_does_not_notify(self):
        task = self.create_task()
        before = len(self.repo.pending_deliveries())
        self.tasks.update(self.group.id, task.id, UpdateTask(expected_revision=1, title=task.title), "engine")
        self.assertEqual(len(self.repo.pending_deliveries()), before)
        self.assertEqual(self.repo.get(self.group.id).tasks[0].revision, 1)

    def test_move_releases_work_cancels_stale_delivery_and_revokes_access(self):
        task = self.create_task(owner_id="engine")
        other = self.members.create(CreateGroup(name="Other", bounds=self.group.bounds,
                                   members=[GroupMember(node_id="integrator")]))
        self.members.move("engine", other.id, expected_source=self.group.id)
        old = self.repo.get(self.group.id).tasks[0]
        self.assertEqual((old.id, old.status, old.owner_id), (task.id, "blocked", None))
        self.assertEqual(self.repo.member_group("engine").id, other.id)
        self.assertFalse(any(d["node_id"] == "engine" and d["group_id"] == self.group.id
                             for d in self.repo.pending_deliveries()))
        with self.assertRaises(GroupPermissionError):
            self.repo.get(self.group.id, "engine")
        with self.assertRaises(GroupConflict):
            self.members.move("engine", None, expected_source=self.group.id)

    def test_message_retries_are_idempotent_and_payload_mismatch_rejected(self):
        command = PublishMessage(text="Review level one", request_id="message-1", broadcast_reason="All specialties must review their part")
        first = self.messages.publish(self.group.id, command, "engine")
        second = self.messages.publish(self.group.id, command, "engine")
        self.assertEqual(first, second)
        deliveries = [d for d in self.repo.pending_deliveries() if d["seq"] == first["seq"]]
        self.assertEqual({d["node_id"] for d in deliveries}, {"story", "qa"})
        with self.assertRaises(GroupConflict):
            self.messages.publish(self.group.id, PublishMessage(text="Different", request_id="message-1"), "engine")

    def test_direct_message_visibility_and_recipient_scope(self):
        event = self.messages.publish(self.group.id, PublishMessage(
            text="Private review", request_id="direct-1", recipient_id="qa"), "engine")
        self.assertNotIn(event["seq"], [e["seq"] for e in self.repo.events(self.group.id, "story")["events"]])
        self.assertIn(event["seq"], [e["seq"] for e in self.repo.events(self.group.id, "qa")["events"]])
        self.assertEqual([d["node_id"] for d in self.repo.pending_deliveries() if d["seq"] == event["seq"]], ["qa"])
        with self.assertRaises(GroupPermissionError):
            self.messages.publish(self.group.id, PublishMessage(text="outside", request_id="bad", recipient_id="stranger"), "engine")

    def test_delivery_failure_is_persistent_and_retryable(self):
        self.messages.publish(self.group.id, PublishMessage(text="Work", request_id="work"), None)
        delivery = self.repo.pending_deliveries()[0]
        self.repo.record_delivery(delivery["seq"], delivery["node_id"], error="node queue unavailable")
        persisted = GroupRepository(self.directory).pending_deliveries()[0]
        self.assertEqual(persisted["last_error"], "node queue unavailable")
        self.assertEqual(persisted["attempts"], 1)
        self.repo.record_delivery(delivery["seq"], delivery["node_id"])
        self.assertFalse(any(d["node_id"] == delivery["node_id"] and d["seq"] == delivery["seq"]
                             for d in self.repo.pending_deliveries()))

    def test_dissolve_keeps_nodes_and_audit_but_removes_membership(self):
        node = self.directory / "engine"
        node.mkdir()
        self.members.dissolve(self.group.id, self.group.revision)
        self.assertTrue(node.is_dir())
        self.assertEqual(self.repo.list(), [])
        self.assertIsNone(self.repo.member_group("engine"))
        with self.assertRaises(GroupNotFound):
            self.repo.get(self.group.id)
        self.assertEqual(self.repo.pending_deliveries(), [])

    def test_bounds_dont_wake_agents_and_contracts_reject_bad_data(self):
        before = len(self.repo.pending_deliveries())
        updated = self.members.configure(self.group.id, 1, bounds=GroupBounds(x=20, y=40, width=700, height=500),
            layout=[SpatialMember(m.node_id, 100, 100) for m in self.group.members])
        self.assertEqual(updated.revision, 2)
        self.assertEqual(len(self.repo.pending_deliveries()), before)
        with self.assertRaises(ValidationError):
            GroupBounds(x=float("nan"), y=0, width=3, height=4)
        with self.assertRaises(ValidationError):
            UpdateTask(expected_revision=1, status=None)
        with self.assertRaises(ValidationError):
            PublishMessage(text="test", request_id="x", actor_id="forged")


if __name__ == "__main__":
    unittest.main()

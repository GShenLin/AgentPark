import json
import tempfile
from unittest.mock import patch
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.agent_groups.agent_tools import GroupAgentTools, bind_group_tools
from src.agent_groups.contracts import GroupPermissionError
from src.agent_groups.membership import GroupMembership
from src.agent_groups.repository import GroupRepository
from src.tool.base_tool import BaseTool
from src.tool.tool_invocation import invoke_tool_function
from src.web_backend.group_api import register_group_routes
from src.web_backend.request_access import has_owner_access
from src.web_backend.memory_static_files import VisibilityAwareMemoriesStaticFiles


class GroupBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.graph = self.root / "game"
        self.graph.mkdir()
        self.private = set()
        self.nodes = {"engine", "story", "qa"}
        for node in self.nodes:
            (self.graph / node).mkdir()

        def require_node(node, graph, request):
            if node not in self.nodes or (node in self.private and not has_owner_access(request)):
                raise HTTPException(404, "node not found")

        core = SimpleNamespace(
            access_api=SimpleNamespace(message_access_metadata=lambda request: {
                "_access_role": "developer" if has_owner_access(request) else "nondeveloper"}),
            graph_runtime=SimpleNamespace(_sanitize_graph_id=lambda value: value.replace("..", ""),
                                          _graph_dir=lambda value: str(self.root / value)),
            graph_api=SimpleNamespace(require_graph_visible=lambda *args: None),
            node_ops=SimpleNamespace(require_node_visible=require_node,
                                     _node_is_private=lambda graph, node: node in self.private),
        )
        app = FastAPI()
        register_group_routes(app, core)
        self.owner = TestClient(app, client=("127.0.0.1", 50001))
        self.remote = TestClient(app, client=("192.0.2.10", 50002))
        self.addCleanup(self.owner.close)
        self.addCleanup(self.remote.close)
        self.base = "/api/graphs/game"
        response = self.owner.post(self.base + "/groups", json={
            "name": "Game team", "bounds": {"x": 0, "y": 0, "width": 600, "height": 400},
            "members": [{"node_id": node} for node in ("engine", "story")],
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.group = response.json()
        self.url = self.base + "/groups/" + self.group["id"]
        self.repo = GroupRepository(self.graph)

    def prepare_spatial_layout(self):
        patcher = patch('src.web_backend.group_spatial_layout.read_board_layout_settings', return_value={
            'gridCellWidth': 300, 'gridCellHeight': 320, 'nodeWidth': 230, 'nodeHeight': 250})
        patcher.start()
        self.addCleanup(patcher.stop)
        for index, node in enumerate(('engine', 'story', 'qa')):
            (self.graph / node / 'config.json').write_text(json.dumps({
                'type_id': 'agent_node', 'ui': {'grid_x': index, 'grid_y': 0, 'width': 230, 'height': 250}}), encoding='utf-8')

    def resize(self, x, width, revision=None):
        return self.owner.patch(self.url, json={'expected_revision': revision or self.repo.get(self.group['id']).revision,
            'bounds': {'x': x, 'y': 0, 'width': width, 'height': 320}})

    def test_resize_reconciles_members_tasks_and_persists_empty_frame(self):
        self.prepare_spatial_layout()
        self.owner.patch(self.url + '/members/story', json={'expected_role': '', 'role': 'writer'})
        self.owner.post(self.url + '/tasks', json={'title': 'Engine work', 'owner_id': 'engine'})
        expanded = self.resize(0, 900)
        self.assertEqual(expanded.status_code, 200, expanded.text)
        self.assertEqual({m['node_id'] for m in expanded.json()['members']}, self.nodes)
        shrunk = self.resize(300, 600)
        self.assertEqual(shrunk.status_code, 200, shrunk.text)
        result = shrunk.json()
        self.assertEqual({m['node_id'] for m in result['members']}, {'story', 'qa'})
        self.assertEqual(next(m['role'] for m in result['members'] if m['node_id'] == 'story'), 'writer')
        self.assertEqual(result['tasks'][0]['status'], 'blocked')
        self.assertIsNone(result['tasks'][0]['owner_id'])
        self.assertFalse(any(d['node_id'] == 'engine' for d in self.repo.pending_deliveries()))
        self.assertEqual(self.resize(900, 300).json()['members'], [])
        self.assertEqual(self.owner.get(self.url).json()['bounds']['x'], 900)
        self.assertEqual(len(self.resize(0, 900).json()['members']), 3)

    def test_resize_rejects_stale_overlap_invalid_grid_and_rolls_back(self):
        self.prepare_spatial_layout()
        self.assertEqual(self.resize(1, 900).status_code, 400)
        self.resize(0, 900)
        self.assertEqual(self.resize(0, 300, revision=1).status_code, 409)
        self.resize(0, 600)
        other = self.owner.post(self.base + '/groups', json={'name': 'Other',
            'bounds': {'x': 600, 'y': 0, 'width': 300, 'height': 320}, 'members': [{'node_id': 'qa'}]})
        self.assertEqual(other.status_code, 200)
        before = self.owner.get(self.url).json()
        self.assertEqual(self.resize(300, 600).status_code, 409)
        self.assertEqual(self.owner.get(self.url).json(), before)
        self.assertEqual(self.repo.member_group('engine').id, self.group['id'])

    def test_resize_does_not_import_hidden_nodes(self):
        self.prepare_spatial_layout()
        self.private.add('qa')
        before = self.owner.get(self.url).json()
        result = self.remote.patch(self.url, json={'expected_revision': before['revision'],
            'bounds': {'x': 0, 'y': 0, 'width': 900, 'height': 320}})
        self.assertEqual(result.status_code, 404)
        self.assertEqual(self.owner.get(self.url).json(), before)
        result = self.resize(0, 900)
        self.assertTrue(result.json()['private'])
        self.assertTrue(self.resize(0, 600).json()['private'])

    def test_attachment_only_message_and_attachment_sensitive_retry(self):
        body = {"text": "", "request_id": "attachment-only", "attachments": [
            {"uri": "C:/upload/proof.png", "name": "proof.png", "kind": "image", "mime": "image/png"}]}
        first = self.owner.post(self.url + "/messages", json=body)
        self.assertEqual(first.status_code, 200, first.text)
        retry = self.owner.post(self.url + "/messages", json=body)
        self.assertEqual(retry.json()["seq"], first.json()["seq"])
        self.assertEqual(first.json()["payload"]["attachments"][0]["uri"], "C:/upload/proof.png")
        body["attachments"][0]["uri"] = "C:/upload/different.png"
        self.assertEqual(self.owner.post(self.url + "/messages", json=body).status_code, 409)
        for attachments in [[], [{"uri": "", "kind": "image"}], [{"uri": "x", "kind": "unknown"}],
                            [{"uri": "x", "kind": "image", "actor_id": "story"}]]:
            response = self.owner.post(self.url + "/messages", json={
                "text": " ", "request_id": "invalid", "attachments": attachments})
            self.assertEqual(response.status_code, 422, response.text)

    def test_http_board_task_message_and_conflict(self):
        task_response = self.owner.post(self.url + "/tasks", json={"title": "Opening level", "owner_id": "engine"})
        self.assertEqual(task_response.status_code, 200)
        task = task_response.json()
        response = self.owner.patch(self.url + "/tasks/" + task["id"], json={
            "expected_revision": 1, "status": "in_progress",
        })
        self.assertEqual(response.status_code, 200)
        stale = self.owner.patch(self.url + "/tasks/" + task["id"], json={"expected_revision": 1, "status": "blocked"})
        self.assertEqual(stale.status_code, 409)
        sent = self.owner.post(self.url + "/messages", json={"text": "Build the opening level", "request_id": "input-1"})
        self.assertEqual(sent.status_code, 200)
        duplicate = self.owner.post(self.url + "/messages", json={"text": "Build the opening level", "request_id": "input-1"})
        self.assertEqual(sent.json()["seq"], duplicate.json()["seq"])
        events = self.owner.get(self.url + "/events?after=0").json()
        self.assertEqual(events["events"][-1]["payload"]["text"], "Build the opening level")
        self.assertEqual(self.owner.get(self.url).json()["tasks"][0]["status"], "in_progress")

    def test_plan_compare_and_swap_preserves_peer_edits_but_allows_task_changes(self):
        command = {"expected_name": "Game team", "expected_objective": "",
                   "name": "Local name", "objective": "Local objective"}
        self.owner.post(self.url + "/tasks", json={"title": "Unrelated progress"})
        saved = self.owner.patch(self.url + "/plan", json=command)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["objective"], "Local objective")
        events_before = self.repo.events(self.group["id"])["events"]
        peer = {"expected_name": "Local name", "expected_objective": "Local objective",
                "name": "Peer name", "objective": "Peer objective"}
        self.assertEqual(self.owner.patch(self.url + "/plan", json=peer).status_code, 200)
        stale = self.owner.patch(self.url + "/plan", json={**peer, "name": "Stale draft"})
        self.assertEqual(stale.status_code, 409)
        current = self.owner.get(self.url).json()
        self.assertEqual((current["name"], current["objective"]), ("Peer name", "Peer objective"))
        events = self.repo.events(self.group["id"])["events"]
        self.assertEqual(len(events), len(events_before) + 1)
        self.assertEqual(events[-1]["payload"]["objective"], "Peer objective")
        # Missing comparisons cannot silently disable conflict protection.
        self.assertEqual(self.owner.patch(self.url + "/plan", json={"name": "Unsafe", "objective": ""}).status_code, 422)
        self.private.add("engine")
        self.assertEqual(self.remote.patch(self.url + "/plan", json=peer).status_code, 404)

    def test_strict_boundary_rejects_forged_actor_and_invalid_geometry(self):
        self.assertEqual(self.owner.post(self.url + "/messages", json={
            "text": "spoof", "request_id": "1", "actor_id": "engine",
        }).status_code, 422)
        self.assertEqual(self.owner.patch(self.url, json={
            "expected_revision": 1, "bounds": {"x": 0, "y": 0, "width": -1, "height": 1},
        }).status_code, 422)
        self.assertEqual(self.owner.get(self.url + "/events?limit=10000").status_code, 422)
        self.assertEqual(self.owner.get("/api/graphs/missing/groups").status_code, 404)

    def test_role_update_has_visibility_membership_and_conflict_guards(self):
        url = self.url + "/members/story"
        command = {"expected_role": "", "role": "Story and dialogue"}
        response = self.owner.patch(url, json=command)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(next(m["role"] for m in response.json()["members"] if m["node_id"] == "story"), command["role"])
        self.assertEqual(self.owner.patch(url, json=command).status_code, 409)
        self.assertEqual(self.owner.patch(self.url + "/members/qa", json=command).status_code, 409)
        self.assertEqual(self.owner.patch(url, json={**command, "actor_id": "engine"}).status_code, 422)
        self.private.add("story")
        self.assertEqual(self.remote.patch(url, json={"expected_role": command["role"], "role": "Hidden"}).status_code, 404)

    def test_visibility_and_history_remain_private_after_member_leaves(self):
        self.assertEqual(len(self.remote.get(self.base + "/groups").json()["groups"]), 1)
        self.private.add("engine")
        GroupMembership(self.repo).protect_member_history("engine")
        self.assertEqual(self.remote.get(self.url).status_code, 404)
        self.assertEqual(self.remote.get(self.url + "/events").status_code, 404)
        self.assertEqual(self.remote.post(self.url + "/messages", json={"text": "x", "request_id": "x"}).status_code, 404)
        self.assertEqual(self.remote.get(self.base + "/groups").json(), {"groups": []})
        response = self.owner.put(self.base + "/group-members/engine", json={
            "target_group_id": None, "expected_source": self.group["id"],
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.owner.get(self.url).json()["private"])
        self.assertEqual(self.remote.get(self.url).status_code, 404)

    def test_dissolve_and_move_are_revision_checked_and_keep_agents(self):
        moved = self.owner.put(self.base + "/group-members/qa", json={
            "target_group_id": self.group["id"], "expected_source": None, "role": "QA",
        })
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(self.owner.delete(self.url + "?expected_revision=1").status_code, 409)
        revision = self.owner.get(self.url).json()["revision"]
        self.assertEqual(self.owner.delete(self.url + f"?expected_revision={revision}").status_code, 200)
        self.assertEqual(self.owner.get(self.url).status_code, 404)
        self.assertEqual(self.owner.get(self.base + "/groups").json(), {"groups": []})
        self.assertTrue(all((self.graph / node).is_dir() for node in self.nodes))

    def test_registered_tools_bind_identity_validate_arguments_and_revoke_access(self):
        messages = []
        agent = SimpleNamespace(Message=lambda *args, **kwargs: messages.append((args, kwargs)))
        agent.tools = BaseTool(agent)
        self.assertTrue(bind_group_tools(agent, node_directory=str(self.graph / "engine"), node_id="engine", role="system"))
        self.assertEqual(len(agent.tools.tool_declarations), 8)
        schema = next(item['function']['parameters'] for item in agent.tools.tool_declarations
                      if item['function']['name'] == 'group_update_task')
        self.assertEqual(schema['properties']['dependencies']['type'], 'array')
        self.assertNotIn('dependencies', schema['required'])
        self.assertNotIn({'type': 'null'}, schema['properties']['status'].get('anyOf', []))
        self.assertIn({'type': 'null'}, schema['properties']['owner_id']['anyOf'])
        self.assertIn('"your_node_id": "engine"', messages[0][0][1])
        functions = agent.tools.function_map
        task = invoke_tool_function(functions["group_create_task"], {"title": "Build game"}, agent=agent)
        claimed = invoke_tool_function(functions["group_update_task"], {
            "task_id": task["id"], "expected_revision": 1, "owner_id": "engine", "status": "in_progress",
        }, agent=agent)
        self.assertEqual(claimed["owner_id"], "engine")
        with self.assertRaises(ValidationError):
            invoke_tool_function(functions["group_send_message"], {
                "text": "spoof", "request_id": "spoof", "actor_id": "story",
            }, agent=agent)
        sent = invoke_tool_function(functions["group_send_message"], {"text": "Ready", "request_id": "ready", "recipient_id": "story"}, agent=agent)
        self.assertEqual(sent["actor_id"], "engine")
        GroupMembership(self.repo).move("engine", None, expected_source=self.group["id"])
        for name, args in [("group_board", {}), ("group_send_message", {"text": "late", "request_id": "late", "recipient_id": "story"}),
                           ("group_create_task", {"title": "late"})]:
            with self.assertRaises(GroupPermissionError):
                invoke_tool_function(functions[name], args, agent=agent)

    def test_group_tools_preserve_distinct_member_capabilities(self):
        agents = []
        for node, provider, tool_name in [("engine", "provider-engine", "compile_level"),
                                          ("story", "provider-story", "inspect_dialogue")]:
            agent = SimpleNamespace(provider_id=provider, skills=[tool_name], Message=lambda *args, **kwargs: None)
            agent.tools = BaseTool(agent)
            agent.tools.register_external_tool({"type": "function", "function": {
                "name": tool_name, "description": "Existing member capability",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            }}, lambda tool_name=tool_name: {"capability": tool_name})
            original = agent.tools.function_map[tool_name]
            self.assertTrue(bind_group_tools(agent, node_directory=str(self.graph / node), node_id=node, role="system"))
            self.assertIs(agent.tools.function_map[tool_name], original)
            self.assertEqual(invoke_tool_function(original, {}, agent=agent), {"capability": tool_name})
            self.assertEqual((agent.provider_id, agent.skills), (provider, [tool_name]))
            self.assertEqual(len(agent.tools.tool_declarations), 9)
            agents.append(agent)
        self.assertNotIn("inspect_dialogue", agents[0].tools.function_map)
        self.assertNotIn("compile_level", agents[1].tools.function_map)
        # The same collaboration action keeps each caller's own identity.
        for node, agent in zip(("engine", "story"), agents):
            event = invoke_tool_function(agent.tools.function_map["group_send_message"],
                {"text": "Specialist result", "request_id": node + "-result", "recipient_id": "story" if node == "engine" else "engine"}, agent=agent)
            self.assertEqual(event["actor_id"], node)

    def test_ungrouped_nodes_do_not_get_tools_or_create_database(self):
        unrelated = self.root / "other" / "node"
        unrelated.mkdir(parents=True)
        self.assertFalse(bind_group_tools(SimpleNamespace(), node_directory=str(unrelated), node_id="node", role="system"))
        self.assertFalse((unrelated.parent / "groups.sqlite3").exists())

    def test_group_database_and_journals_cannot_be_downloaded_as_memory_files(self):
        app = FastAPI()
        app.mount("/memories", VisibilityAwareMemoriesStaticFiles(directory=str(self.root), core=SimpleNamespace()))
        with TestClient(app) as client:
            for name in ("groups.sqlite3", "groups.sqlite3-wal", "groups.sqlite3-shm"):
                self.assertEqual(client.get("/memories/game/" + name).status_code, 404)


if __name__ == "__main__":
    unittest.main()

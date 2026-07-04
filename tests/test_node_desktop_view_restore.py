import json
from types import SimpleNamespace

from src.web_backend import node_desktop_view
from src.web_backend.node_desktop_view import NodeDesktopViewDomain


class FakeGraphRuntime:
    def __init__(self, root, events):
        self.root = root
        self.events = events

    def _sanitize_graph_id(self, value):
        return str(value or "default").strip() or "default"

    def _sanitize_node_id(self, value):
        return str(value or "").strip()

    def _resolve_existing_node_id(self, _graph_id, node_id):
        return node_id

    def _node_config_path(self, node_id, graph_id):
        return str(self.root / "memories" / graph_id / node_id / "config.json")

    def _log_graph_event(self, *args, **kwargs):
        self.events.append((args, kwargs))


def test_restore_visible_desktop_pets_launches_visible_views(monkeypatch, tmp_path):
    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()
    for node_id in ("n1", "n2"):
        node_dir = tmp_path / "memories" / "default" / node_id
        node_dir.mkdir(parents=True)
        (node_dir / "config.json").write_text(json.dumps({"node_id": node_id}), encoding="utf-8")
    (cache_dir / "node_desktop_views.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "views": [
                    {"view_id": "v1", "graph_id": "default", "node_id": "n1", "visible": True, "pinned": True},
                    {"view_id": "v2", "graph_id": "default", "node_id": "n2", "visible": False, "pinned": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    events = []
    launched = []

    def fake_launch(graph_id, node_id, payload):
        launched.append((graph_id, node_id, payload))
        return SimpleNamespace(pid=1234)

    graph_runtime = FakeGraphRuntime(tmp_path, events)
    core = SimpleNamespace(graph_api=SimpleNamespace(list_graphs=lambda: {"graphs": [{"id": "default"}]}), graph_runtime=graph_runtime)
    monkeypatch.setattr(node_desktop_view, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(node_desktop_view, "launch_node_desktop_pet_process", fake_launch)

    result = NodeDesktopViewDomain(core, graph_runtime).restore_visible_desktop_pets()

    assert result["requested"] == 1
    assert result["restored"] == 1
    assert result["failed"] == []
    assert launched == [("default", "n1", {"visible": True, "pinned": True, "view_id": "v1"})]
    assert events[0][0][1] == "node_desktop_pet_restored"


def test_mark_all_desktop_pets_hidden_clears_stale_visible_views(monkeypatch, tmp_path):
    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()
    store_path = cache_dir / "node_desktop_views.json"
    store_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "views": [
                    {"view_id": "v1", "graph_id": "default", "node_id": "n1", "visible": True},
                    {"view_id": "v2", "graph_id": "default", "node_id": "n2", "visible": False},
                ],
            }
        ),
        encoding="utf-8",
    )
    events = []
    graph_runtime = FakeGraphRuntime(tmp_path, events)
    core = SimpleNamespace(graph_runtime=graph_runtime)
    monkeypatch.setattr(node_desktop_view, "_get_runtime_root", lambda: str(tmp_path))

    result = NodeDesktopViewDomain(core, graph_runtime).mark_all_desktop_pets_hidden()

    stored = json.loads(store_path.read_text(encoding="utf-8"))
    assert result["updated"] == 1
    assert stored["views"][0]["visible"] is False
    assert stored["views"][1]["visible"] is False

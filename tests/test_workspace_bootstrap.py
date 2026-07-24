from types import SimpleNamespace

from src.web_backend.workspace_bootstrap import WorkspaceBootstrapDomain


class _GraphApi:
    def __init__(self):
        self.calls = []

    def get_startup_graph_config(self, request=None):
        self.calls.append(("startup", request))
        return {"graph_id": "test"}

    def get_graph(self, graph_id, request=None):
        self.calls.append(("graph", graph_id, request))
        return {"graph": {"id": graph_id, "name": "Test", "nodes": []}}

    def list_graphs(self, request=None):
        self.calls.append(("graphs", request))
        return {"graphs": [{"id": "test", "name": "Test"}]}


def test_workspace_bootstrap_uses_true_startup_graph_and_returns_mount_snapshot():
    graph_api = _GraphApi()
    request = object()
    core = SimpleNamespace(
        graph_api=graph_api,
        remote_api=SimpleNamespace(
            get_remote_status=lambda request=None: {"is_local_client": True},
            list_remotes=lambda request=None: {"remotes": [{"id": "local"}]},
        ),
        system_api=SimpleNamespace(list_providers=lambda request=None: {"providers": [{"id": "openai"}]}),
        node_ops=SimpleNamespace(
            list_nodes=lambda: {"nodes": [{"type_id": "agent_node"}]},
            list_tools=lambda: {"tools": ["read_file"]},
        ),
        profile_api=SimpleNamespace(list_graph_profiles=lambda: {"profiles": [{"id": "default"}]}),
        settings_api=SimpleNamespace(
            get_settings_section=lambda section: {"data": {"accent": "blue"}, "active_preset_id": "dark"}
        ),
        mobile_api=SimpleNamespace(list_mobile_pcs=lambda: {"pcs": [{"id": "phone"}]}),
        user_interaction_api=SimpleNamespace(
            list_user_interactions=lambda request=None: {"requests": [{"request_id": "ask-1"}]}
        ),
    )

    payload = WorkspaceBootstrapDomain(core).get_workspace_bootstrap(request=request)

    assert graph_api.calls[:2] == [("startup", request), ("graph", "test", request)]
    assert payload["startup_graph"]["id"] == "test"
    assert payload["remote_status"] == {"is_local_client": True}
    assert payload["providers"] == [{"id": "openai"}]
    assert payload["nodes"] == [{"type_id": "agent_node"}]
    assert payload["tools"] == ["read_file"]
    assert payload["graphs"] == [{"id": "test", "name": "Test"}]
    assert payload["graph_profiles"] == [{"id": "default"}]
    assert payload["theme"] == {"data": {"accent": "blue"}, "active_preset_id": "dark"}
    assert payload["mobile_pcs"] == [{"id": "phone"}]
    assert payload["user_interactions"] == [{"request_id": "ask-1"}]

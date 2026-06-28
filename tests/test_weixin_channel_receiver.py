def test_receiver_name_match_strips_command_prefix():
    from src.channels.receiver_routing import match_receiver_name

    envelope = {
        "role": "user",
        "parts": [
            {"type": "text", "text": "/ChatGPT summarize this"},
            {"type": "resource", "resource": {"kind": "image", "uri": "image.png"}},
        ],
    }

    matched = match_receiver_name(envelope, "ChatGPT")

    assert matched is not None
    assert matched["parts"][0] == {"type": "text", "text": "summarize this"}
    assert matched["parts"][1] == {"type": "resource", "resource": {"kind": "image", "uri": "image.png"}}
    assert envelope["parts"][0]["text"] == "/ChatGPT summarize this"


def test_receiver_name_match_rejects_colon_separator():
    from src.channels.receiver_routing import match_receiver_name

    envelope = {"role": "user", "parts": [{"type": "text", "text": "/ChatGPT: summarize this"}]}

    assert match_receiver_name(envelope, "ChatGPT") is None


def test_receiver_name_match_rejects_other_prefix():
    from src.channels.receiver_routing import match_receiver_name

    envelope = {"role": "user", "parts": [{"type": "text", "text": "/Other summarize this"}]}

    assert match_receiver_name(envelope, "ChatGPT") is None


def test_receiver_name_match_rejects_partial_command_name():
    from src.channels.receiver_routing import match_receiver_name

    envelope = {"role": "user", "parts": [{"type": "text", "text": "/ChatGPT2 summarize this"}]}

    assert match_receiver_name(envelope, "ChatGPT") is None


def test_receiver_without_name_accepts_message_unchanged():
    from src.channels.receiver_routing import match_receiver_name

    envelope = {"role": "user", "parts": [{"type": "text", "text": "hello"}]}

    assert match_receiver_name(envelope, "") is envelope


def test_receiver_name_match_rejects_empty_command_body():
    from src.channels.receiver_routing import match_receiver_name

    envelope = {"role": "user", "parts": [{"type": "text", "text": "/ChatGPT"}]}

    assert match_receiver_name(envelope, "ChatGPT") is None



def test_receiver_loop_uses_persisted_name_config(tmp_path):
    import threading

    from src.channels.service import ChannelService
    from src.web_backend import state_store

    config_path = tmp_path / "ChannelReceiver" / "config.json"
    state_store._write_json_dict(
        str(config_path),
        {
            "node_id": "ChannelReceiver",
            "type_id": "channel_receiver_node",
            "Channel": "openclaw-weixin",
            "AccountId": "acct-1",
            "Name": "doubao",
            "Active": False,
            "PollTimeoutSeconds": 1,
        },
    )

    stop_event = threading.Event()
    emitted = []

    class FakeGraphRuntime:
        def _sanitize_graph_id(self, value):
            return str(value or "default").strip() or "default"

        def _sanitize_node_id(self, value):
            return str(value or "").strip()

        def _node_config_path(self, node_id, graph_id):
            assert node_id == "ChannelReceiver"
            assert graph_id == "default"
            return str(config_path)

    class FakeGraphApi:
        def emit_graph(self, graph_id, payload):
            emitted.append((graph_id, payload))
            stop_event.set()

    class FakeCore:
        graph_runtime = FakeGraphRuntime()
        graph_api = FakeGraphApi()

    class FakeDriver:
        def __init__(self):
            self.calls = 0

        def get_updates(self, *, account_id, timeout_seconds):
            assert account_id == "acct-1"
            assert timeout_seconds == 1
            self.calls += 1
            if self.calls == 1:
                return {"msgs": [{"text": "/doubao hello"}]}
            stop_event.set()
            return {"msgs": []}

        def message_to_envelope(self, *, account_id, message):
            assert account_id == "acct-1"
            return {"role": "user", "parts": [{"type": "text", "text": message["text"]}]}

    service = ChannelService(FakeCore())
    service._driver = FakeDriver()

    service._receiver_loop("default", "ChannelReceiver", stop_event)

    assert len(emitted) == 1
    payload = emitted[0][1]["payload"]
    assert payload["parts"] == [{"type": "text", "text": "hello"}]
    assert state_store._read_json_dict(str(config_path))["Active"] is True


def test_receiver_active_state_accepts_followup_without_command(tmp_path, monkeypatch):
    from src.channels import service as service_module
    from src.channels.service import ChannelService
    from src.web_backend import state_store

    graph_dir = tmp_path / "graphs" / "default"
    config_path = graph_dir / "ReceiverA" / "config.json"
    state_store._write_json_dict(
        str(config_path),
        {
            "node_id": "ReceiverA",
            "type_id": "channel_receiver_node",
            "Channel": "openclaw-weixin",
            "AccountId": "acct-1",
            "Name": "alpha",
            "Active": True,
            "PollTimeoutSeconds": 1,
        },
    )
    monkeypatch.setattr(service_module.runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "graphs"))

    class FakeGraphRuntime:
        def _sanitize_graph_id(self, value):
            return str(value or "default").strip() or "default"

        def _sanitize_node_id(self, value):
            return str(value or "").strip()

        def _node_config_path(self, node_id, graph_id):
            assert graph_id == "default"
            return str(graph_dir / node_id / "config.json")

    class FakeCore:
        graph_runtime = FakeGraphRuntime()

    service = ChannelService(FakeCore())
    cfg = service._read_receiver_runtime_config("default", "ReceiverA")
    routed = service._route_receiver_envelope(
        "default",
        "ReceiverA",
        {"role": "user", "parts": [{"type": "text", "text": "follow up"}]},
        cfg,
    )

    assert routed.graph_id == "default"
    assert routed.node_id == "ReceiverA"
    assert routed.envelope["parts"] == [{"type": "text", "text": "follow up"}]


def test_receiver_runtime_config_rejects_invalid_poll_timeout(tmp_path, monkeypatch):
    import pytest

    from src.channels import service as service_module
    from src.channels.errors import ChannelConfigError
    from src.channels.service import ChannelService
    from src.web_backend import state_store

    graph_dir = tmp_path / "graphs" / "default"
    config_path = graph_dir / "ReceiverA" / "config.json"
    state_store._write_json_dict(
        str(config_path),
        {
            "node_id": "ReceiverA",
            "type_id": "channel_receiver_node",
            "Channel": "openclaw-weixin",
            "AccountId": "acct-1",
            "PollTimeoutSeconds": "soon",
        },
    )
    monkeypatch.setattr(service_module.runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "graphs"))

    class FakeGraphRuntime:
        def _sanitize_graph_id(self, value):
            return str(value or "default").strip() or "default"

        def _sanitize_node_id(self, value):
            return str(value or "").strip()

        def _node_config_path(self, node_id, graph_id):
            assert graph_id == "default"
            return str(graph_dir / node_id / "config.json")

    class FakeCore:
        graph_runtime = FakeGraphRuntime()

    service = ChannelService(FakeCore())
    with pytest.raises(ChannelConfigError, match="PollTimeoutSeconds must be an integer"):
        service._read_receiver_runtime_config("default", "ReceiverA")


def test_receiver_loop_broadcasts_plain_message_to_active_receivers_across_graphs(tmp_path, monkeypatch):
    import threading

    from src.channels import service as service_module
    from src.channels.service import ChannelService
    from src.web_backend import state_store

    graphs_root = tmp_path / "graphs"
    graph_a_path = graphs_root / "graphA" / "ReceiverAlpha" / "config.json"
    graph_b_path = graphs_root / "graphB" / "ReceiverBeta" / "config.json"
    graph_c_path = graphs_root / "graphC" / "ReceiverGamma" / "config.json"
    for path, name, active in [
        (graph_a_path, "alpha", True),
        (graph_b_path, "beta", True),
        (graph_c_path, "gamma", False),
    ]:
        state_store._write_json_dict(
            str(path),
            {
                "node_id": path.parent.name,
                "type_id": "channel_receiver_node",
                "Channel": "openclaw-weixin",
                "AccountId": "acct-1",
                "Name": name,
                "Active": active,
                "PollTimeoutSeconds": 1,
            },
        )
    monkeypatch.setattr(service_module.runtime_paths, "_get_graphs_dir", lambda: str(graphs_root))

    stop_event = threading.Event()
    emitted = []

    class FakeGraphRuntime:
        def _sanitize_graph_id(self, value):
            return str(value or "default").strip() or "default"

        def _sanitize_node_id(self, value):
            return str(value or "").strip()

        def _node_config_path(self, node_id, graph_id):
            return str(graphs_root / graph_id / node_id / "config.json")

    class FakeGraphApi:
        def emit_graph(self, graph_id, payload):
            emitted.append((graph_id, payload))
            if len(emitted) >= 2:
                stop_event.set()

    class FakeCore:
        graph_runtime = FakeGraphRuntime()
        graph_api = FakeGraphApi()

    class FakeDriver:
        def __init__(self):
            self.calls = 0

        def get_updates(self, *, account_id, timeout_seconds):
            assert account_id == "acct-1"
            assert timeout_seconds == 1
            self.calls += 1
            if self.calls == 1:
                return {"msgs": [{"text": "plain follow up"}]}
            stop_event.set()
            return {"msgs": []}

        def message_to_envelope(self, *, account_id, message):
            assert account_id == "acct-1"
            return {"role": "user", "parts": [{"type": "text", "text": message["text"]}]}

    service = ChannelService(FakeCore())
    service._driver = FakeDriver()

    service._receiver_loop("graphA", "ReceiverAlpha", stop_event)

    assert [(graph_id, payload["from_id"]) for graph_id, payload in emitted] == [
        ("graphA", "ReceiverAlpha"),
        ("graphB", "ReceiverBeta"),
    ]
    assert emitted[0][1]["payload"]["parts"] == [{"type": "text", "text": "plain follow up"}]
    assert emitted[0][1]["trace_id"] == emitted[1][1]["trace_id"]


def test_start_receiver_uses_single_poller_per_account(tmp_path, monkeypatch):
    from src.channels import service as service_module
    from src.channels.service import ChannelService
    from src.web_backend import state_store

    graphs_root = tmp_path / "graphs"
    first_path = graphs_root / "graphA" / "ReceiverAlpha" / "config.json"
    second_path = graphs_root / "graphB" / "ReceiverBeta" / "config.json"
    for path, name in [(first_path, "alpha"), (second_path, "beta")]:
        state_store._write_json_dict(
            str(path),
            {
                "node_id": path.parent.name,
                "type_id": "channel_receiver_node",
                "Channel": "openclaw-weixin",
                "AccountId": "acct-1",
                "Name": name,
                "Active": True,
                "PollTimeoutSeconds": 1,
            },
        )
    monkeypatch.setattr(service_module.runtime_paths, "_get_graphs_dir", lambda: str(graphs_root))

    class FakeThread:
        created = []

        def __init__(self, *args, **kwargs):
            self.started = False
            FakeThread.created.append(self)

        def start(self):
            self.started = True

        def is_alive(self):
            return self.started

    monkeypatch.setattr(service_module.threading, "Thread", FakeThread)

    class FakeGraphRuntime:
        def _sanitize_graph_id(self, value):
            return str(value or "default").strip() or "default"

        def _sanitize_node_id(self, value):
            return str(value or "").strip()

        def _node_config_path(self, node_id, graph_id):
            return str(graphs_root / graph_id / node_id / "config.json")

    class FakeCore:
        graph_runtime = FakeGraphRuntime()

    service = ChannelService(FakeCore())

    service.start_receiver("graphA", "ReceiverAlpha")
    service.start_receiver("graphB", "ReceiverBeta")

    assert len(FakeThread.created) == 1
    assert len(service._account_pollers) == 1
    poller = service._account_pollers["acct-1"]
    stop_event = poller["stop_event"]

    service.stop_receiver("graphA", "ReceiverAlpha")
    assert not stop_event.is_set()
    assert "acct-1" in service._account_pollers

    service.stop_receiver("graphB", "ReceiverBeta")
    assert stop_event.is_set()
    assert "acct-1" not in service._account_pollers


def test_receiver_command_switches_active_receiver_and_closes_others(tmp_path, monkeypatch):
    from src.channels import service as service_module
    from src.channels.service import ChannelService
    from src.web_backend import state_store

    graph_dir = tmp_path / "graphs" / "default"
    alpha_path = graph_dir / "ReceiverAlpha" / "config.json"
    beta_path = graph_dir / "ReceiverBeta" / "config.json"
    state_store._write_json_dict(
        str(alpha_path),
        {
            "node_id": "ReceiverAlpha",
            "type_id": "channel_receiver_node",
            "Channel": "openclaw-weixin",
            "AccountId": "acct-1",
            "Name": "alpha",
            "Active": True,
            "PollTimeoutSeconds": 1,
        },
    )
    state_store._write_json_dict(
        str(beta_path),
        {
            "node_id": "ReceiverBeta",
            "type_id": "channel_receiver_node",
            "Channel": "openclaw-weixin",
            "AccountId": "acct-1",
            "Name": "beta",
            "Active": False,
            "PollTimeoutSeconds": 1,
        },
    )
    monkeypatch.setattr(service_module.runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "graphs"))

    class FakeGraphRuntime:
        def _sanitize_graph_id(self, value):
            return str(value or "default").strip() or "default"

        def _sanitize_node_id(self, value):
            return str(value or "").strip()

        def _node_config_path(self, node_id, graph_id):
            assert graph_id == "default"
            return str(graph_dir / node_id / "config.json")

    class FakeCore:
        graph_runtime = FakeGraphRuntime()

    service = ChannelService(FakeCore())
    service.start_receiver = lambda graph_id, node_id, cfg=None: {"ok": True}
    cfg = service._read_receiver_runtime_config("default", "ReceiverAlpha")
    routed = service._route_receiver_envelope(
        "default",
        "ReceiverAlpha",
        {"role": "user", "parts": [{"type": "text", "text": "/beta hello"}]},
        cfg,
    )

    assert routed.graph_id == "default"
    assert routed.node_id == "ReceiverBeta"
    assert routed.envelope["parts"] == [{"type": "text", "text": "hello"}]
    assert state_store._read_json_dict(str(alpha_path))["Active"] is False
    assert state_store._read_json_dict(str(beta_path))["Active"] is True


def test_receiver_switch_command_without_body_only_updates_state(tmp_path, monkeypatch):
    from src.channels import service as service_module
    from src.channels.service import ChannelService
    from src.web_backend import state_store

    graph_dir = tmp_path / "graphs" / "default"
    config_path = graph_dir / "ReceiverBeta" / "config.json"
    state_store._write_json_dict(
        str(config_path),
        {
            "node_id": "ReceiverBeta",
            "type_id": "channel_receiver_node",
            "Channel": "openclaw-weixin",
            "AccountId": "acct-1",
            "Name": "beta",
            "Active": False,
            "PollTimeoutSeconds": 1,
        },
    )
    monkeypatch.setattr(service_module.runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "graphs"))

    class FakeGraphRuntime:
        def _sanitize_graph_id(self, value):
            return str(value or "default").strip() or "default"

        def _sanitize_node_id(self, value):
            return str(value or "").strip()

        def _node_config_path(self, node_id, graph_id):
            assert graph_id == "default"
            return str(graph_dir / node_id / "config.json")

    class FakeCore:
        graph_runtime = FakeGraphRuntime()

    service = ChannelService(FakeCore())
    cfg = service._read_receiver_runtime_config("default", "ReceiverBeta")
    routed = service._route_receiver_envelope(
        "default",
        "ReceiverBeta",
        {"role": "user", "parts": [{"type": "text", "text": "/beta"}]},
        cfg,
    )

    assert routed.graph_id == "default"
    assert routed.node_id == "ReceiverBeta"
    assert routed.envelope is None
    assert routed.command_matched is True
    assert state_store._read_json_dict(str(config_path))["Active"] is True

def test_receiver_command_deactivates_same_account_receivers_across_graphs(tmp_path, monkeypatch):
    import threading

    from src.channels import service as service_module
    from src.channels.receiver_models import ReceiverKey
    from src.channels.service import ChannelService
    from src.web_backend import state_store

    graphs_root = tmp_path / "graphs"
    graph_a_dir = graphs_root / "graphA"
    graph_b_dir = graphs_root / "graphB"
    graph_a_path = graph_a_dir / "ReceiverAlpha" / "config.json"
    graph_b_path = graph_b_dir / "ReceiverBeta" / "config.json"
    state_store._write_json_dict(
        str(graph_a_path),
        {
            "node_id": "ReceiverAlpha",
            "type_id": "channel_receiver_node",
            "Channel": "openclaw-weixin",
            "AccountId": "acct-1",
            "Name": "alpha",
            "Active": False,
            "PollTimeoutSeconds": 1,
        },
    )
    state_store._write_json_dict(
        str(graph_b_path),
        {
            "node_id": "ReceiverBeta",
            "type_id": "channel_receiver_node",
            "Channel": "openclaw-weixin",
            "AccountId": "acct-1",
            "Name": "beta",
            "Active": True,
            "PollTimeoutSeconds": 1,
        },
    )
    monkeypatch.setattr(service_module.runtime_paths, "_get_graphs_dir", lambda: str(graphs_root))

    class FakeGraphRuntime:
        def _sanitize_graph_id(self, value):
            return str(value or "default").strip() or "default"

        def _sanitize_node_id(self, value):
            return str(value or "").strip()

        def _node_config_path(self, node_id, graph_id):
            return str(graphs_root / graph_id / node_id / "config.json")

    class FakeCore:
        graph_runtime = FakeGraphRuntime()

    service = ChannelService(FakeCore())
    graph_a_stop = threading.Event()
    graph_b_stop = threading.Event()
    service._receivers[ReceiverKey("graphA", "ReceiverAlpha").text()] = {"stop_event": graph_a_stop}
    service._receivers[ReceiverKey("graphB", "ReceiverBeta").text()] = {"stop_event": graph_b_stop}

    cfg = service._read_receiver_runtime_config("graphA", "ReceiverAlpha")
    routed = service._route_receiver_envelope(
        "graphA",
        "ReceiverAlpha",
        {"role": "user", "parts": [{"type": "text", "text": "/beta"}]},
        cfg,
    )

    assert routed.graph_id == "graphB"
    assert routed.node_id == "ReceiverBeta"
    assert routed.command_matched is True
    assert state_store._read_json_dict(str(graph_a_path))["Active"] is False
    assert state_store._read_json_dict(str(graph_b_path))["Active"] is True
    assert not graph_a_stop.is_set()
    assert not graph_b_stop.is_set()

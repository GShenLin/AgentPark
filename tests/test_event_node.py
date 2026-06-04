import importlib

from src.message_protocol import envelope_text


def test_event_node_schema_and_output():
    mod = importlib.import_module("nodes.event_node")
    node = mod.Node()

    cfg = {}
    node.on_create(cfg, None)

    assert cfg.get("EventKey") == ""
    assert "schema" not in cfg
    schema = node.get_config_schema(None)
    assert schema.get("EventKey") == {"type": "text", "label": "EventKey"}

    out = node.on_input("hello", {"EventKey": "chat.message"})
    assert isinstance(out, dict)
    routes = out.get("routes")
    assert isinstance(routes, list) and routes
    assert routes[0].get("output_index") == 0
    assert envelope_text(routes[0].get("payload")) == "hello"
    assert out.get("event_key") == "chat.message"


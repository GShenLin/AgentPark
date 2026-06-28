from src.message_protocol import envelope_text
from src.web_backend.route_parser import NodeRouteParser


def test_parse_node_output_requires_object():
    try:
        NodeRouteParser.parse_node_output("hello")
        assert False, "expected ValueError for non-object output"
    except ValueError as exc:
        assert "routes" in str(exc)


def test_parse_node_output_requires_routes_field():
    try:
        NodeRouteParser.parse_node_output(
            {
                "display": "x",
            }
        )
        assert False, "expected ValueError when routes is missing"
    except ValueError as exc:
        assert "routes" in str(exc)


def test_parse_node_output_routes_only():
    out = NodeRouteParser.parse_node_output(
        {
            "routes": [
                {"output_index": 1, "payload": "x"},
                {"output_index": 3, "payload": "y"},
            ],
            "display": "ok",
        }
    )
    assert out["display_text"] == "ok"
    assert [(item["output_index"], envelope_text(item["payload"])) for item in out["routes"]] == [(1, "x"), (3, "y")]


def test_parse_node_output_allows_explicit_suppressed_output():
    out = NodeRouteParser.parse_node_output(
        {
            "display": "waiting 1/2",
            "routes": [],
            "suppress_output": True,
        }
    )

    assert out["display_text"] == "waiting 1/2"
    assert out["routes"] == []

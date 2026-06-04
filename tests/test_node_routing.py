from src.node_routing import normalize_node_output


def test_normalize_node_output_requires_object():
    try:
        normalize_node_output("hello")
        assert False, "expected ValueError for non-object output"
    except ValueError as exc:
        assert "routes" in str(exc)


def test_normalize_node_output_requires_routes_field():
    try:
        normalize_node_output(
            {
                "display": "x",
            }
        )
        assert False, "expected ValueError when routes is missing"
    except ValueError as exc:
        assert "routes" in str(exc)


def test_normalize_node_output_routes_only():
    out = normalize_node_output(
        {
            "routes": [
                {"output_index": 1, "payload": "x"},
                {"output_index": 3, "payload": "y"},
            ],
            "display": "ok",
        }
    )
    assert out["display_text"] == "ok"
    assert out["routes"] == [
        {"output_index": 1, "payload": "x"},
        {"output_index": 3, "payload": "y"},
    ]


def test_normalize_node_output_allows_explicit_suppressed_output():
    out = normalize_node_output(
        {
            "display": "waiting 1/2",
            "routes": [],
            "suppress_output": True,
        }
    )

    assert out["display_text"] == "waiting 1/2"
    assert out["routes"] == []

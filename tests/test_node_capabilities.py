from src.node_capabilities import NODE_CAPABILITY_LIST


def test_node_capability_list_trims_and_dedupes_exact_names():
    assert NODE_CAPABILITY_LIST.parse([" text ", "TEXT", "", None, "resource:image"]) == [
        "text",
        "TEXT",
        "resource:image",
    ]


def test_node_capability_list_rejects_non_sequences():
    assert NODE_CAPABILITY_LIST.parse("text") == []

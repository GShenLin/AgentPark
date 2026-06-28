from src.node_capabilities import NODE_CAPABILITY_LIST


def test_node_capability_list_trims_and_dedupes_case_insensitively():
    assert NODE_CAPABILITY_LIST.parse([" text ", "TEXT", "", None, "resource:image"]) == [
        "text",
        "resource:image",
    ]


def test_node_capability_list_rejects_non_sequences():
    assert NODE_CAPABILITY_LIST.parse("text") == []

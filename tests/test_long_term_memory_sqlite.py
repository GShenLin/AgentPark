from __future__ import annotations

from src.long_term_memory.sqlite_store import SqliteLongTermMemoryStore


def test_sqlite_long_term_memory_stores_keywords_and_binary_assets(tmp_path) -> None:
    store = SqliteLongTermMemoryStore("Graph", "Agent", path=str(tmp_path / "memory.sqlite3"))
    memory = store.add_memory(
        kind="decision",
        content="压缩门禁期间只提供 compact_tool_context。",
        summary="压缩工具约束",
        keywords=["压缩门禁", "compact_tool_context"],
        source_trace_id="trace-1",
    )
    asset = store.add_asset(memory.id, "diagram.png", b"\x89PNG\r\n", media_type="image/png")

    results = store.search("compact_tool_context")
    loaded_asset = store.get_asset(asset.id)

    assert results[0].id == memory.id
    assert results[0].keywords == ("compact_tool_context", "压缩门禁")
    assert loaded_asset is not None
    assert loaded_asset.media_type == "image/png"
    assert loaded_asset.data == b"\x89PNG\r\n"

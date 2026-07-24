from src.web_backend.graph_event_stream import GraphEventStreamStore


def test_wait_for_change_delivers_burst_events_in_version_order():
    store = GraphEventStreamStore()

    store.publish("g1", {"event": "work_persisted_alert"})
    store.publish("g1", {"event": "node_output"})
    store.publish("g1", {"event": "node_state_set"})

    first = store.wait_for_change("g1", 0, timeout=0.1)
    second = store.wait_for_change("g1", first["version"], timeout=0.1)
    third = store.wait_for_change("g1", second["version"], timeout=0.1)

    assert [first["event"], second["event"], third["event"]] == [
        "work_persisted_alert",
        "node_output",
        "node_state_set",
    ]
    assert [first["version"], second["version"], third["version"]] == [1, 2, 3]


def test_wait_for_change_recovers_from_history_rollover_at_oldest_available_event():
    store = GraphEventStreamStore(history_limit=2)

    store.publish("g1", {"event": "one"})
    store.publish("g1", {"event": "two"})
    store.publish("g1", {"event": "three"})

    recovered = store.wait_for_change("g1", 0, timeout=0.1)

    assert recovered["event"] == "two"
    assert recovered["version"] == 2


def test_global_stream_delivers_events_across_graphs_in_publish_order():
    store = GraphEventStreamStore()

    store.publish("g1", {"event": "work_persisted_alert"})
    store.publish("g2", {"event": "runtime_notice"})

    first = store.wait_for_global_change(0, timeout=0.1)
    second = store.wait_for_global_change(first["global_version"], timeout=0.1)

    assert first["graph_id"] == "g1"
    assert second["graph_id"] == "g2"
    assert [first["global_version"], second["global_version"]] == [1, 2]


def test_global_stream_reports_exact_gap_before_oldest_retained_event():
    store = GraphEventStreamStore(history_limit=2)
    store.publish("g1", {"event": "one"})
    store.publish("g1", {"event": "two"})
    store.publish("g1", {"event": "three"})

    gap = store.wait_for_global_change(0, timeout=0.1)
    recovered = store.wait_for_global_change(gap["global_version"], timeout=0.1)

    assert gap == {
        "event": "stream_gap",
        "from_global_version": 1,
        "to_global_version": 1,
        "global_version": 1,
    }
    assert recovered["event"] == "two"
    assert recovered["global_version"] == 2


def test_global_stream_timeout_returns_none():
    store = GraphEventStreamStore()

    assert store.wait_for_global_change(0, timeout=0.1) is None


def test_publish_normalizes_graph_id_for_global_stream():
    store = GraphEventStreamStore()

    store.publish("g1", {"event": "work_persisted_alert", "graph_id": "wrong"})

    event = store.wait_for_global_change(0, timeout=0.1)
    assert event["graph_id"] == "g1"

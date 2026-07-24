import json

import pytest

from src.web_backend.node_run_terminal import build_node_run_terminal_event


def test_node_run_terminal_event_carries_failure_contract():
    event = build_node_run_terminal_event(
        trace_id="trace-1",
        status="failed",
        provider_id="demo",
        started_epoch_ms=1000,
        duration_ms=250,
        error="provider failed",
    )

    payload = json.loads(event["message"])
    assert event["stage"] == "node_run_summary"
    assert event["provider"] == "demo"
    assert payload["status"] == "failed"
    assert payload["error"] == "provider failed"
    assert payload["duration_ms"] == 250


def test_node_run_terminal_rejects_unknown_status():
    with pytest.raises(ValueError, match="unsupported node terminal status"):
        build_node_run_terminal_event(
            trace_id="trace-1",
            status="unknown",
            started_epoch_ms=1000,
            duration_ms=0,
        )

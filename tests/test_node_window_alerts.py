import threading
import time

from src.web_backend.graph_event_stream import GraphEventStreamStore
from src.web_backend.node_window_alerts import NodeWindowAlerts


def event(receipt='done'):
    return {'event': 'work_persisted_alert', 'alert_id': receipt, 'node_instance_id': 'Agent'}


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline, 'Background delivery did not finish'
        time.sleep(0.01)


def test_completion_opens_with_no_browser_or_frontend_subscribers():
    events, calls = GraphEventStreamStore(), []
    service = NodeWindowAlerts(events, lambda *target: calls.append(target))
    service.start(9876)
    try:
        events.publish('g', event())
        wait_for(lambda: service.status()['last_delivery'] is not None)
        assert calls == [('Agent', 'g', 9876)]
        assert service.status()['last_delivery']['outcome'] == 'opened'
    finally:
        service.close()


def test_foreground_pages_suppress_and_last_connection_close_restores_delivery():
    events, calls = GraphEventStreamStore(), []
    service = NodeWindowAlerts(events, lambda *target: calls.append(target))
    service.start(9876)
    try:
        service.set_focused('tab-a', True)
        service.set_focused('tab-b', True)
        service.set_focused('tab-a', False)
        events.publish('g', event('visible'))
        assert service.status()['last_delivery']['outcome'] == 'foreground'
        assert not calls
        service.set_focused('tab-b', False)
        events.publish('g', event('closed'))
        wait_for(lambda: len(calls) == 1)
        events.publish('g', event('visible'))  # Suppressed events do not reopen later.
        events.publish('g', event('closed'))
        assert calls == [('Agent', 'g', 9876)]
    finally:
        service.close()


def test_slow_launch_does_not_block_execution_or_lose_burst_completions():
    events, calls = GraphEventStreamStore(history_limit=1), []
    release, started = threading.Event(), threading.Event()

    def launch(*target):
        started.set()
        assert release.wait(3)
        calls.append(target)

    service = NodeWindowAlerts(events, launch)
    service.start(9876)
    try:
        events.publish('g', event('first'))
        assert started.wait(1)
        for i in range(30):
            events.publish('g', event(str(i)))
            events.publish('g', {'event': 'node_output'})
        release.set()
        wait_for(lambda: len(calls) == 31)
    finally:
        release.set()
        service.close()


def test_failures_are_reported_and_do_not_disable_later_delivery(caplog):
    events = GraphEventStreamStore()

    def launch(*_target):
        raise RuntimeError('renderer failed')

    service = NodeWindowAlerts(events, launch)
    service.start(9876)
    try:
        events.publish('g', event())
        wait_for(lambda: events.get('g')['event'] == 'node_window_alert_failed')
        assert service.status()['last_delivery']['error'] == 'renderer failed'
        assert 'Node window alert failed' in caplog.text
        service.launch = lambda *_target: None
        events.publish('g', event('next'))
        wait_for(lambda: service.status()['last_delivery']['outcome'] == 'opened')
    finally:
        service.close()


def test_snapshots_progress_and_shutdown_do_not_launch_windows():
    events, calls = GraphEventStreamStore(), []
    service = NodeWindowAlerts(events, lambda *target: calls.append(target))
    service.start(9876)
    events.publish('g', {**event(), 'stream_snapshot': True})
    events.publish('g', {'event': 'node_output'})
    service.close()
    events.publish('g', event())
    assert not calls
    assert not service.status()['running']

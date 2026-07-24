from functions.console_progress_watchdog import PytestProgressWatchdog


def test_pytest_watchdog_quiet_progress_resets_deadline():
    chunks: list[bytes] = []
    watchdog = PytestProgressWatchdog(
        stdout_chunks=chunks,
        timeout_seconds=60,
        started_at=0,
    )

    chunks.append(b"................................")
    watchdog.observe(now=55)

    assert watchdog.expired(now=114) is False
    snapshot = watchdog.snapshot(now=114).to_payload()
    assert snapshot["progress_events"] == 32
    assert snapshot["seconds_since_progress"] == 59


def test_pytest_watchdog_verbose_terminal_status_is_progress():
    chunks = [b"tests/test_contract.py::test_shape PASSED [ 50%]\n"]
    watchdog = PytestProgressWatchdog(
        stdout_chunks=chunks,
        timeout_seconds=30,
        started_at=0,
    )

    watchdog.observe(now=20)

    assert watchdog.expired(now=49) is False
    assert watchdog.snapshot(now=49).progress_events == 1


def test_pytest_watchdog_repeated_traceback_lines_are_not_progress():
    chunks = [
        b"E   RuntimeError: worker bootstrap failed\n" * 500,
        b"diagnostic log activity without a completed test\n" * 500,
    ]
    watchdog = PytestProgressWatchdog(
        stdout_chunks=chunks,
        timeout_seconds=60,
        started_at=0,
    )

    watchdog.observe(now=61)

    assert watchdog.expired(now=61) is True
    snapshot = watchdog.snapshot(now=61)
    assert snapshot.progress_events == 0
    assert snapshot.seconds_since_progress == 61


def test_pytest_watchdog_single_traceback_ellipsis_is_not_progress():
    chunks = [b"... traceback continuation\n"]
    watchdog = PytestProgressWatchdog(
        stdout_chunks=chunks,
        timeout_seconds=10,
        started_at=0,
    )

    watchdog.observe(now=11)

    assert watchdog.expired(now=11) is True
    assert watchdog.snapshot(now=11).progress_events == 0

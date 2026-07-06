def test_start_env_parent_exit_monitor_uses_configured_pid(monkeypatch):
    from src import windows_parent_monitor

    captured = {}
    exit_func = object()

    monkeypatch.setenv("AGENTPARK_EXIT_WHEN_PID_EXITS", "12345")
    monkeypatch.setattr(
        windows_parent_monitor,
        "start_process_exit_monitor",
        lambda parent_pid, exit_func=None, thread_name="": captured.update(
            {"parent_pid": parent_pid, "exit_func": exit_func, "thread_name": thread_name}
        )
        or True,
    )

    assert windows_parent_monitor.start_env_parent_exit_monitor(exit_func=exit_func) is True
    assert captured == {
        "parent_pid": 12345,
        "exit_func": exit_func,
        "thread_name": "launcher-exit-monitor",
    }


def test_start_env_parent_exit_monitor_ignores_invalid_pid(monkeypatch):
    from src import windows_parent_monitor

    monkeypatch.setenv("AGENTPARK_EXIT_WHEN_PID_EXITS", "not-a-pid")
    monkeypatch.setattr(
        windows_parent_monitor,
        "start_process_exit_monitor",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not start monitor")),
    )

    assert windows_parent_monitor.start_env_parent_exit_monitor() is False

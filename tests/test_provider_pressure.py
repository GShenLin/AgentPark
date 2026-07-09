import json
import threading
import time

import src.providers.provider_pressure as provider_pressure
from src.providers.provider_pressure import ProviderPressureManager


def _write_provider_config(tmp_path, provider):
    config_path = tmp_path / "moduleProvider.json"
    config_path.write_text(
        json.dumps({"providers": {"demo": provider}}, ensure_ascii=False),
        encoding="utf-8",
    )
    return config_path


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_provider_pressure_queues_when_concurrency_limit_is_reached(monkeypatch, tmp_path):
    config_path = _write_provider_config(
        tmp_path,
        {
            "type": "openai",
            "apiKey": "secret",
            "concurrencyLimit": 1,
        },
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    manager = ProviderPressureManager()
    release_first = threading.Event()
    entered_second = threading.Event()

    def first_worker():
        with manager.acquire("demo"):
            release_first.wait(timeout=1)

    def second_worker():
        with manager.acquire("demo"):
            entered_second.set()

    first = threading.Thread(target=first_worker)
    second = threading.Thread(target=second_worker)
    first.start()
    assert _wait_until(lambda: manager.snapshot()["providers"][0]["in_flight"] == 1)

    second.start()
    assert _wait_until(lambda: manager.snapshot()["providers"][0]["queued"] == 1)
    assert not entered_second.is_set()

    release_first.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert entered_second.is_set()
    row = manager.snapshot()["providers"][0]
    assert row["queued"] == 0
    assert row["in_flight"] == 0
    assert row["peak_in_flight"] == 1
    assert row["peak_queued"] == 1


def test_provider_pressure_queues_until_rpm_interval_has_elapsed(monkeypatch, tmp_path):
    monkeypatch.setattr(provider_pressure, "RPM_INTERVAL_BASE_SEC", 0.1)
    config_path = _write_provider_config(
        tmp_path,
        {
            "type": "openai",
            "apiKey": "secret",
            "rpmLimit": 1,
        },
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    manager = ProviderPressureManager()

    with manager.acquire("demo"):
        pass

    entered_second = threading.Event()

    def second_worker():
        with manager.acquire("demo"):
            entered_second.set()

    started_at = time.monotonic()
    second = threading.Thread(target=second_worker)
    second.start()
    assert _wait_until(lambda: manager.snapshot()["providers"][0]["queued"] == 1)
    assert not entered_second.is_set()

    second.join(timeout=1)

    assert entered_second.is_set()
    assert time.monotonic() - started_at >= 0.08
    row = manager.snapshot()["providers"][0]
    assert row["queued"] == 0
    assert row["peak_rpm_used"] == 1
    assert row["rpm_interval_sec"] == 0.1


def test_provider_pressure_unconfigured_limits_do_not_queue(monkeypatch, tmp_path):
    config_path = _write_provider_config(
        tmp_path,
        {
            "type": "openai",
            "apiKey": "secret",
        },
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    manager = ProviderPressureManager()

    with manager.acquire("demo"):
        row = manager.snapshot()["providers"][0]

    assert row["concurrency_limit"] is None
    assert row["rpm_limit"] is None
    assert row["queued"] == 0
    assert row["in_flight"] == 1
    assert row["peak_in_flight"] == 1

from contextlib import contextmanager

import pytest

from src.providers import curl_transport
from src.providers.curl_transport import CurlResponse
from src.providers.curl_transport import CurlHttpTransport
from src.providers.curl_transport import CurlTransportError
from src.runtime_cancellation import CancellationRequested


class _FakeStderr:
    def read(self):
        return ""


class _FakeProcess:
    def __init__(self, stdout):
        self.stdout = stdout
        self.stderr = _FakeStderr()
        self._return_code = None

    def wait(self, timeout=None):
        del timeout
        if self._return_code is None:
            self._return_code = 0
        return self._return_code

    def poll(self):
        return self._return_code

    def kill(self):
        self._return_code = -9
        release = getattr(self.stdout, "release", None)
        if callable(release):
            release()


class _BlockingStdout:
    def __init__(self):
        self._released = curl_transport.threading.Event()

    def __iter__(self):
        return self

    def __next__(self):
        self._released.wait()
        raise StopIteration

    def release(self):
        self._released.set()


@contextmanager
def _unlocked_provider_slot():
    yield


def _monotonic_values(*values):
    iterator = iter(values)
    return lambda: next(iterator)


def test_curl_executable_uses_plain_curl_on_posix(monkeypatch):
    monkeypatch.setattr(curl_transport.os, "name", "posix")

    assert CurlHttpTransport._curl_executable() == "curl"


def test_curl_executable_uses_curl_exe_on_windows(monkeypatch):
    monkeypatch.setattr(curl_transport.os, "name", "nt")

    assert CurlHttpTransport._curl_executable() == "curl.exe"


def test_curl_post_command_uses_platform_executable(monkeypatch):
    monkeypatch.setattr(curl_transport.os, "name", "posix")
    monkeypatch.setattr(CurlHttpTransport, "_curl_proxy_args", lambda url: ["--proxy", "http://localhost:8080"])

    command = CurlHttpTransport._build_curl_post_command(
        url="https://example.test/v1/responses",
        headers={"Authorization": "Bearer token"},
        payload_path="/tmp/request.json",
        timeout_val=60,
        connect_timeout=15,
        marker="__STATUS__",
        no_buffer=True,
    )

    assert command[0] == "curl"
    assert command[1] == "--disable"
    assert command[command.index("--proxy") + 1] == "http://localhost:8080"
    assert "--no-buffer" in command
    assert "curl.exe" not in command
    assert command[command.index("--max-time") + 1] == "60"


def test_sse_stream_timeout_is_reset_by_each_received_line(monkeypatch):
    transport = CurlHttpTransport()
    observed = {}

    def fake_popen(command, **_kwargs):
        observed["command"] = command
        return _FakeProcess(
            iter(
                [
                    "data: first\n",
                    "data: second\n",
                    "__STATUS__200\n",
                ]
            )
        )

    monkeypatch.setattr(curl_transport.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(transport, "_provider_pressure_slot", _unlocked_provider_slot)
    monkeypatch.setattr(
        curl_transport.time,
        "monotonic",
        _monotonic_values(0.0, 0.75, 0.75, 1.5, 1.5, 1.6, 1.6, 1.7),
    )

    items = list(
        transport._curl_post_sse_raw_lines(
            url="https://example.test/v1/responses",
            headers={},
            payload_json="{}",
            timeout_sec=1,
            marker="__STATUS__",
        )
    )

    assert items[:2] == ["first", "second"]
    assert isinstance(items[-1], CurlResponse)
    assert items[-1].status_code == 200
    assert "--no-buffer" in observed["command"]
    assert "--max-time" not in observed["command"]


def test_sse_stream_times_out_after_idle_interval(monkeypatch):
    transport = CurlHttpTransport()
    process = _FakeProcess(_BlockingStdout())

    monkeypatch.setattr(curl_transport.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(transport, "_provider_pressure_slot", _unlocked_provider_slot)
    monkeypatch.setattr(curl_transport.time, "monotonic", _monotonic_values(0.0, 1.0))

    with pytest.raises(CurlTransportError, match="idle timeout after 1s"):
        list(
            transport._curl_post_sse_raw_lines(
                url="https://example.test/v1/responses",
                headers={},
                payload_json="{}",
                timeout_sec=1,
                marker="__STATUS__",
            )
        )

    assert process.poll() is not None


def test_sse_stream_remains_cancellable_without_total_timeout(monkeypatch):
    transport = CurlHttpTransport()
    transport.cancel_event = curl_transport.threading.Event()
    transport.cancel_event.set()
    process = _FakeProcess(_BlockingStdout())

    monkeypatch.setattr(curl_transport.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(transport, "_provider_pressure_slot", _unlocked_provider_slot)

    with pytest.raises(CancellationRequested):
        list(
            transport._curl_post_sse_raw_lines(
                url="https://example.test/v1/responses",
                headers={},
                payload_json="{}",
                timeout_sec=60,
                marker="__STATUS__",
            )
        )

    assert process.poll() is not None

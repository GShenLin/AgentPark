from src.providers import curl_transport
from src.providers.curl_transport import CurlHttpTransport


def test_curl_executable_uses_plain_curl_on_posix(monkeypatch):
    monkeypatch.setattr(curl_transport.os, "name", "posix")

    assert CurlHttpTransport._curl_executable() == "curl"


def test_curl_executable_uses_curl_exe_on_windows(monkeypatch):
    monkeypatch.setattr(curl_transport.os, "name", "nt")

    assert CurlHttpTransport._curl_executable() == "curl.exe"


def test_curl_post_command_uses_platform_executable(monkeypatch):
    monkeypatch.setattr(curl_transport.os, "name", "posix")

    command = CurlHttpTransport._build_curl_post_command(
        url="https://example.test/v1/responses",
        headers={"Authorization": "Bearer token"},
        payload_path="/tmp/request.json",
        timeout_val=60,
        connect_timeout=15,
        marker="__STATUS__",
        no_buffer=False,
    )

    assert command[0] == "curl"
    assert "curl.exe" not in command

"""Real curl exchanges against loopback, including cookies and process cleanup."""
import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.providers.curl_transport import CurlHttpTransport, CurlHttpError, CurlTransportError


@pytest.fixture
def endpoint():
    seen = []
    waiting = threading.Event()
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def do_PUT(self):
            self.respond()

        def respond(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            seen.append((self.command, self.path, dict(self.headers), body))
            if self.path == "/wait":
                waiting.set()
                release.wait(3)
            status = 302 if self.path == "/redirect" else 403 if self.path == "/denied" else 200
            self.send_response(status)
            if self.path == "/redirect":
                self.send_header("Location", "/echo")
            if self.path == "/login":
                self.send_header("Set-Cookie", "session=hello; Path=/; HttpOnly")
            self.send_header("Content-Type", "application/octet-stream")
            content = body if body else b"\x00\xff\n__AGENTPARK_HTTP_CODE__:599"
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", seen, waiting
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_binary_methods_status_and_proxy_bypass(endpoint, monkeypatch):
    url, seen, _ = endpoint
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    transport = CurlHttpTransport()
    data = b"\x00\xff\n__AGENTPARK_HTTP_CODE__:599"
    response = transport.request(url=url + "/echo", method="PUT", body=data,
                                 headers={"Content-Type": "application/octet-stream"}, trust_env=False)
    assert response.content == data and response.status_code == 200
    assert seen[-1][0] == "PUT" and seen[-1][3] == data
    transport.request(url=url + "/echo", method="GET", body=data)
    assert seen[-1][0] == "GET" and seen[-1][3] == data
    denied = transport.request(url=url + "/denied")
    with pytest.raises(CurlHttpError) as caught:
        denied.raise_for_status()
    assert caught.value.status_code == 403 and caught.value.content == data


def test_redirect_policy_and_size_limit(endpoint):
    url, seen, _ = endpoint
    transport = CurlHttpTransport()
    assert transport.request(url=url + "/redirect", follow_redirects=False).status_code == 302
    assert len(seen) == 1
    assert transport.request(url=url + "/redirect").status_code == 200
    assert seen[-1][1] == "/echo"
    with pytest.raises(CurlTransportError):
        transport.request(url=url + "/echo", max_response_bytes=2)


def test_cookie_session_and_websocket_header(endpoint, tmp_path):
    url, seen, _ = endpoint
    cookies = str(tmp_path / "cookies")
    transport = CurlHttpTransport()
    transport.request(url=url + "/login", cookie_file=cookies)
    transport.request(url=url + "/echo", cookie_file=cookies)
    assert seen[-1][2]["Cookie"] == "session=hello"
    assert transport.cookie_header(cookies, url + "/portal/connect") == "session=hello"
    assert transport.cookie_header(cookies, "https://other.invalid/") == ""


def test_async_cancel_reaps_process(endpoint, monkeypatch):
    from src.providers import curl_transport
    url, _, waiting = endpoint
    processes = []
    popen = curl_transport.subprocess.Popen

    def capture(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(curl_transport.subprocess, "Popen", capture)

    async def run():
        task = asyncio.create_task(CurlHttpTransport().request_async(url=url + "/wait"))
        assert await asyncio.to_thread(waiting.wait, 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes and all(p.poll() is not None for p in processes)

    asyncio.run(run())


def test_rejects_header_injection_before_network(endpoint):
    url, seen, _ = endpoint
    with pytest.raises(ValueError, match="header"):
        CurlHttpTransport().request(url=url, headers={"X-Test": "a\r\nX-Other: b"})
    assert not seen

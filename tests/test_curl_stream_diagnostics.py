import json
import socket
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO

import pytest

from src.providers.curl_transport import CurlHttpTransport, CurlResponse, CurlTransportError
from src.providers.curl_stream_diagnostics import METRICS_MARKER, read_stream_stderr


@contextmanager
def server(body, *, truncate=False, status=200):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body) + (100 if truncate else 0)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            if truncate:
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/responses"
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=2)


def transport():
    instance = CurlHttpTransport()
    instance.events = []
    instance.tool_event_callback = instance.events.append
    return instance


def terminal(instance):
    events = [json.loads(e["message"]) for e in instance.events if e.get("stage") == "curl_stream_end"]
    assert len(events) == 1
    return events[0]


def test_real_curl_records_status_and_phase_timings_without_credentials():
    instance = transport()
    body = 'data: {"text":"中文"}\n\n'.encode("utf-8")
    with server(body) as url:
        items = list(instance.stream_sse_data(url=url, headers={"Authorization": "Bearer secret-test"},
                                             payload_json="{}", timeout_sec=5))
    assert items[0] == '{"text":"中文"}'
    assert isinstance(items[-1], CurlResponse)
    assert items[-1].status_code == 200
    end = terminal(instance)
    assert end["reason"] == "eof"
    assert end["return_code"] == 0
    assert end["eof"] is True
    assert end["received_bytes"] == len(body)
    assert 0 <= end["queue_wait_ms"] <= end["first_byte_ms"] <= end["elapsed_ms"]
    assert end["receive_ms"] >= 0
    assert end["tail_wait_ms"] >= 0
    assert end["curl_timings"]["http_code"] == 200
    assert end["curl_timings"]["first_byte_seconds"] >= end["curl_timings"]["connect_seconds"]
    assert "secret-test" not in json.dumps(instance.events)


def test_truncated_connection_retains_curl_error_and_does_not_yield_partial_json():
    instance = transport()
    body = b'data: {"type":"response.output_item.done"}\n\ndata: {"type":"response.completed","unfinished":"'
    with server(body, truncate=True) as url:
        stream = instance.stream_sse_data(url=url, headers={}, payload_json="{}", timeout_sec=5)
        assert next(stream) == '{"type":"response.output_item.done"}'
        with pytest.raises(CurlTransportError, match=r"curl: \(18\)"):
            list(stream)
    end = terminal(instance)
    assert end["reason"] == "transport_error"
    assert end["eof"] is True
    assert end["return_code"] == 18
    assert end["stderr"]
    assert end["curl_timings"]["http_code"] == 200


def test_clean_http_eof_with_partial_line_is_protocol_failure():
    instance = transport()
    with server(b'data: {"unfinished":"') as url:
        with pytest.raises(CurlTransportError, match="unterminated line"):
            list(instance.stream_sse_data(url=url, headers={}, payload_json="{}", timeout_sec=5))
    end = terminal(instance)
    assert end["reason"] == "truncated_line"
    assert end["return_code"] == 0


def test_consumer_close_records_transport_cleanup():
    instance = transport()
    with server(b'data: first\n\ndata: second\n\n') as url:
        stream = instance.stream_sse_data(url=url, headers={}, payload_json="{}", timeout_sec=5)
        assert next(stream) == "first"
        stream.close()
    end = terminal(instance)
    assert end["reason"] == "consumer_closed"
    assert end["return_code"] is not None


def test_stderr_separates_timing_record_from_network_error():
    stderr = BytesIO(("curl: (35) TLS failed\n" + METRICS_MARKER +
                      '{"http_code":"000","connect_seconds":0.1}\n').encode())
    message, timings = read_stream_stderr(stderr)
    assert message == "curl: (35) TLS failed"
    assert timings == {"http_code": 0, "connect_seconds": 0.1}


def test_http_error_body_without_newline_retains_status():
    instance = transport()
    body = b'{"error":"invalid request"}'
    with server(body, status=400) as url:
        items = list(instance.stream_sse_data(url=url, headers={}, payload_json="{}", timeout_sec=5))
    assert items[-1].status_code == 400
    assert items[-1].body == body.decode()
    assert terminal(instance)["reason"] == "http_error"

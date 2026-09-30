"""Exercise ACP transport errors and cancellation using an actual child process."""
import os
import sys
import threading
import time

import pytest

from src.harness.acp_client import AcpClient
from src.runtime_cancellation import CancellationRequested


def client_for(source, tmp_path, **options):
    return AcpClient([sys.executable, "-u", "-c", source], cwd=str(tmp_path),
                     env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                     timeout=options.get("timeout", 5), cancel_source=options.get("cancel"), on_update=lambda _: None)


@pytest.mark.parametrize("payload,exception,match", [
    ('{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"upstream failed"}}', RuntimeError, "upstream failed"),
    ('{"jsonrpc":"2.0","id":99,"result":{}}', ValueError, "response id"),
    ('{"jsonrpc":"2.0","id":1,"result":"bad"}', ValueError, "must be an object"),
    ('not-json', ValueError, "Expecting value"),
])
def test_transport_never_accepts_invalid_success(tmp_path, payload, exception, match):
    client = client_for(f"import sys; sys.stdin.readline(); print({payload!r})", tmp_path)
    try:
        with pytest.raises(exception, match=match):
            client.request("initialize", {})
    finally:
        client.close()
    assert client.process.poll() is not None


def test_permission_request_is_explicitly_cancelled(tmp_path):
    source = '''import sys,json
sys.stdin.readline()
print(json.dumps({"jsonrpc":"2.0","id":"permission","method":"session/request_permission","params":{}}))
reply=json.loads(sys.stdin.readline())
assert reply["result"]["outcome"]["outcome"] == "cancelled"
'''
    client = client_for(source, tmp_path)
    try:
        with pytest.raises(RuntimeError, match="interactive permission"):
            client.request("session/prompt", {})
    finally:
        client.close()
    assert client.process.returncode == 0


@pytest.mark.parametrize("cancelled", [False, True])
def test_pending_request_timeout_or_cancellation_stops_child(tmp_path, cancelled):
    cancel = threading.Event()
    timer = threading.Timer(0.2, cancel.set)
    client = client_for("import sys,time; sys.stdin.readline(); time.sleep(60)", tmp_path,
                        timeout=10 if cancelled else 0.2, cancel=cancel)
    if cancelled:
        timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(CancellationRequested if cancelled else TimeoutError):
            client.request("session/prompt", {})
    finally:
        timer.cancel()
        client.close()
    assert client.process.poll() is not None
    assert time.monotonic() - started < 10

import multiprocessing
import os
import time

import pytest

from src.native_path_picker import NativePathPickerError, _run_picker


def _success(connection, value):
    connection.send(("ok", value))
    connection.close()


def _crash(connection):
    os._exit(37)


def _hang(connection):
    time.sleep(30)


def _unrelated(ready, stop):
    ready.set()
    stop.wait(30)


@pytest.mark.parametrize("value", ["", "C:/资料/笔记"])
def test_success_and_cancellation(value):
    assert _run_picker(_success, (value,), timeout=10) == value


def test_child_crash_and_timeout_do_not_stop_parent_or_unrelated_process():
    context = multiprocessing.get_context("spawn")
    ready, stop = context.Event(), context.Event()
    other = context.Process(target=_unrelated, args=(ready, stop))
    other.start()
    try:
        assert ready.wait(10)
        parent_pid = os.getpid()
        with pytest.raises(NativePathPickerError, match="exit code 37"):
            _run_picker(_crash, (), timeout=10)
        assert os.getpid() == parent_pid and other.is_alive()
        with pytest.raises(NativePathPickerError, match="超时"):
            _run_picker(_hang, (), timeout=0.2)
        assert os.getpid() == parent_pid and other.is_alive()
    finally:
        stop.set()
        other.join(timeout=10)
        if other.is_alive():
            other.terminate()
            other.join(timeout=5)
        other.close()

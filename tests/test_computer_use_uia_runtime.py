import threading

import pytest

from src.computer_use.contracts import ComputerUseError
from src.computer_use.windows_uia import _AutomationRuntime


def test_uia_runtime_reuses_one_initialized_thread_and_finalizes_there():
    events = []

    def initialize():
        events.append(('initialize', threading.get_ident()))
        return type('State', (), {'desktop': object()})()

    def finalize(state):
        events.append(('finalize', threading.get_ident(), state.desktop))

    runtime = _AutomationRuntime(initialize, finalize)
    try:
        first = runtime.call(lambda desktop: (threading.get_ident(), desktop))
        second = runtime.call(lambda desktop: (threading.get_ident(), desktop))
        assert first[0] == second[0] == events[0][1]
        assert first[1] is second[1]
        assert events == [('initialize', first[0])]
    finally:
        runtime.close()

    assert events[1][0] == 'finalize'
    assert events[1][1] == events[0][1]
    assert events[1][2] is first[1]


def test_uia_runtime_marshals_errors_without_worker_tracebacks():
    state = type('State', (), {'desktop': object()})()
    runtime = _AutomationRuntime(lambda: state, lambda _state: None)
    try:
        with pytest.raises(ComputerUseError, match='target moved') as captured:
            runtime.call(lambda _desktop: (_ for _ in ()).throw(ComputerUseError('target moved')))
        traceback_names = []
        current = captured.value.__traceback__
        while current is not None:
            traceback_names.append(current.tb_frame.f_code.co_name)
            current = current.tb_next
        assert '_run' not in traceback_names
    finally:
        runtime.close()


def test_uia_runtime_rejects_calls_after_close():
    runtime = _AutomationRuntime(
        lambda: type('State', (), {'desktop': object()})(), lambda _state: None)
    runtime.close()
    with pytest.raises(RuntimeError, match='closed'):
        runtime.call(lambda desktop: desktop)

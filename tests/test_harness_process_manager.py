from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from src.harness import install_manager
from src.harness.contracts import HarnessContext, HarnessResult
from src.harness.file_lock import file_lease
from src.harness.process_manager import HarnessProcesses
from src.runtime_cancellation import CancellationRequested, raise_if_cancel_requested


class Runtime:
    def __init__(self):
        self.alive = False
        self.starts = 0
        self.turns = []
        self.entered = threading.Event()

    def prepare(self, context):
        if not self.alive:
            self.starts += 1
        self.alive = True

    def run(self, text, context):
        self.turns.append(text)
        self.entered.set()
        if text == 'wait':
            while not context.values['cancel_event'].is_set():
                threading.Event().wait(.01)
            raise_if_cancel_requested(context.values['cancel_event'])
        return HarnessResult(text, {})

    def is_alive(self):
        return self.alive

    def close(self):
        self.alive = False


@pytest.fixture
def processes(tmp_path, monkeypatch):
    import src.harness.process_manager as module
    manager = HarnessProcesses()
    monkeypatch.setattr(HarnessProcesses, '_instance', manager)
    monkeypatch.setattr(module, 'create_adapter', lambda _: Runtime())
    monkeypatch.setattr(install_manager, 'get_workspace_root', lambda: str(tmp_path))
    yield manager
    manager.close_all()


def context(tmp_path, name):
    node = tmp_path / name
    node.mkdir(exist_ok=True)
    return HarnessContext(str(node / 'config.json'), str(node), {'graph_id': 'g', 'node_instance_id': name})


def test_prewarm_turns_stop_and_restart_keep_conversation(processes, tmp_path):
    ctx = context(tmp_path, 'one')
    memory = tmp_path / 'one' / 'conversation.json'
    memory.write_text('keep', encoding='utf8')
    processes.execute('pi', ctx)
    runtime = processes._entry('pi', ctx.node_directory).adapter
    assert runtime.starts == 1 and not runtime.turns
    for text in ['a', 'b']:
        assert processes.execute('pi', ctx, text).text == text
    assert runtime.starts == 1 and processes.status(ctx.node_directory)['state'] == 'ready'
    with pytest.raises(RuntimeError, match='busy'):
        with file_lease(install_manager.install_root('pi').parent / 'pi.lock', exclusive=True):
            pytest.fail('idle native processes must retain installation ownership')
    processes.stop(ctx.node_directory)
    assert processes.status(ctx.node_directory)['state'] == 'stopped'
    assert memory.read_text(encoding='utf8') == 'keep'
    processes.execute('pi', ctx, 'c')
    assert runtime.starts == 2


def test_stop_cancels_running_turn_and_never_replays(processes, tmp_path):
    ctx = context(tmp_path, 'busy')
    runtime = processes._entry('pi', ctx.node_directory).adapter
    errors = []
    def turn():
        try:
            processes.execute('pi', ctx, 'wait')
        except Exception as exc:
            errors.append(exc)
    worker = threading.Thread(target=turn)
    worker.start()
    assert runtime.entered.wait(2)
    assert processes.status(ctx.node_directory)['state'] == 'running'
    processes.stop(ctx.node_directory)
    worker.join(2)
    assert not worker.is_alive() and isinstance(errors[0], CancellationRequested)
    assert processes.status(ctx.node_directory)['state'] == 'stopped'
    processes.execute('pi', ctx)
    assert runtime.turns == ['wait']


def test_update_stops_only_its_type_then_restores_without_messages(processes, tmp_path, monkeypatch):
    targets = [('pi', 'one'), ('pi', 'two'), ('hermes_agent', 'other')]
    contexts = [context(tmp_path, name) for _, name in targets]
    for (kind, _), ctx in zip(targets, contexts):
        processes.execute(kind, ctx)
    runtimes = [processes._entry(kind, ctx.node_directory).adapter for (kind, _), ctx in zip(targets, contexts)]
    def install(kind, action):
        assert kind == 'pi' and action == 'upgrade'
        assert not runtimes[0].alive and not runtimes[1].alive and runtimes[2].alive
        # A later manual stop overrides the updater's restoration intent.
        processes.stop(contexts[1].node_directory)
        with pytest.raises(RuntimeError, match='being changed'):
            with install_manager.runtime_lease('pi'):
                pytest.fail('must not start during update')
        return 'updated'
    monkeypatch.setattr(install_manager, '_mutate_installation', install)
    def verify(kind):
        assert not runtimes[0].alive and runtimes[2].alive
        with pytest.raises(RuntimeError, match='being changed'):
            with install_manager.runtime_lease(kind):
                pytest.fail('must not start before installation verification completes')
        return {'status': 'ready'}
    monkeypatch.setattr(install_manager, '_inspect_installation', verify)
    result = install_manager.mutate_installation('pi', 'upgrade')
    assert not result['restore_errors']
    assert [r.starts for r in runtimes] == [2, 1, 1]
    assert [r.alive for r in runtimes] == [True, False, True]
    assert all(not r.turns for r in runtimes)
    assert {p['node_id'] for p in processes.list('pi')} == {'one'}


def test_failed_update_stays_closed_and_preserves_other_type(processes, tmp_path, monkeypatch):
    a, b = context(tmp_path, 'a'), context(tmp_path, 'b')
    processes.execute('pi', a)
    processes.execute('hermes_agent', b)
    def failure(*args):
        raise RuntimeError('installer failed')
    monkeypatch.setattr(install_manager, '_mutate_installation', failure)
    with pytest.raises(RuntimeError, match='installer failed'):
        install_manager.mutate_installation('pi', 'upgrade')
    assert processes.status(a.node_directory)['state'] == 'stopped'
    assert processes.status(b.node_directory)['state'] == 'ready'
    assert 'pi' not in install_manager._MUTATING


def test_restore_failure_is_reported_and_other_nodes_continue(processes, tmp_path):
    a, b = context(tmp_path, 'a'), context(tmp_path, 'b')
    for ctx in [a, b]:
        processes.execute('pi', ctx)
    paths = processes.suspend_type('pi')
    def fail(_):
        raise RuntimeError('native initialization failed')
    processes._entry('pi', a.node_directory).adapter.prepare = fail
    assert processes.restore(paths) == [{'node_id': 'a', 'error': 'native initialization failed'}]
    assert processes.status(a.node_directory)['state'] == 'error'
    assert processes.status(b.node_directory)['state'] == 'ready'


def test_unexpected_child_exit_is_visible(processes, tmp_path):
    ctx = context(tmp_path, 'crash')
    processes.execute('pi', ctx)
    processes._entry('pi', ctx.node_directory).adapter.alive = False
    assert processes.status(ctx.node_directory)['state'] == 'error'
    assert processes.status(ctx.node_directory)['error']

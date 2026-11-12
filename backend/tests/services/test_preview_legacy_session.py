import importlib
import json
import os
import signal
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVICES = Path(__file__).parents[2] / 'app' / 'services'


@pytest.fixture
def session_module(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SERVICES))
    module = importlib.import_module('preview_legacy_session')
    root = tmp_path / 'workspace'
    root.mkdir()
    monkeypatch.setattr(module, 'ROOT', root)
    monkeypatch.setattr(module.journal_api, 'ROOT', root)
    monkeypatch.setattr(module.journal_api, 'STATE', tmp_path / 'preview.sqlite')
    monkeypatch.setattr(module, 'PLAN', tmp_path / 'plan.json')
    monkeypatch.setattr(module, 'OWNER', tmp_path / 'owner.json')
    monkeypatch.setattr(module, 'LOCK', tmp_path / 'lock')
    return module


def command(script):
    return {'cwd': '.', 'argv': [sys.executable, '-u', '-c', script]}


def plan(setup=(), server=None):
    return {
        'setup': list(setup),
        'api': {**(server or command('import time; time.sleep(20)')), 'port': 8765, 'path': '/health'},
    }


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError('Preview did not reach expected state')


def launch_supervisor(module, value, **kwargs):
    supervisor = module.Supervisor(value, str(uuid.uuid4()), **kwargs)
    thread = threading.Thread(target=supervisor.execute)
    thread.start()
    return supervisor, thread


def all_events(module):
    events, cursor = [], 0
    while True:
        page = module.journal_api.read_events(cursor)
        if not page['events']:
            return events
        events.extend(page['events'])
        last = events[-1]
        cursor = last['payload'].get('through_cursor', last['cursor'])


def test_setup_output_is_incremental_and_masked_before_sqlite(session_module):
    m = session_module
    secret = 'fixture-private-password'
    (m.ROOT / '.env').write_text(f'PASSWORD={secret}\nPORT=8765\n')
    setup = command("import sys,time; print('fixture-private-',end='',flush=True); time.sleep(.15); print('password'); print('fixture-private-password',file=sys.stderr); time.sleep(.3); sys.exit(7)")
    supervisor, thread = launch_supervisor(m, plan([setup]))
    try:
        wait_for(lambda: any(event['kind'] == 'stdout' for event in all_events(m)))
        assert thread.is_alive()  # Output exists before the command has completed.
        thread.join(5)
        assert not thread.is_alive()
        events = all_events(m)
        text = json.dumps(events)
        assert secret not in text
        assert '[REDACTED]' in text
        assert any(event['kind'] == 'stderr' for event in events)
        assert [event['kind'] for event in events].count('command_start') == 1
        assert next(event['payload']['exit_code'] for event in events if event['kind'] == 'command_exit') == 7
        assert events[-1]['payload']['status'] == 'failed'
        assert 'setup command 1' in events[-1]['payload']['reason']
        assert secret.encode() not in m.journal_api.STATE.read_bytes()
    finally:
        supervisor.cancel_signal()
        thread.join(5)
        supervisor.journal.db.close()


def test_ready_server_is_supervised_and_cleanup_retains_terminal_exit(session_module, monkeypatch):
    m = session_module
    monkeypatch.setattr(m.Supervisor, 'healthy', lambda *_: True)
    value = plan()
    value['website'] = {**command('import time; time.sleep(20)'), 'port': 9876, 'path': '/'}
    value['initial_path'] = '/docs'
    supervisor, thread = launch_supervisor(m, value)
    try:
        wait_for(lambda: m.journal_api.read_events(0).get('ready'))
        state = m.journal_api.read_events(0)
        assert state['state'] == 'running'
        assert state['details'] == {'api_port': '8765', 'website_port': '9876', 'initial_port': '9876', 'initial_path': '/docs'}
        assert thread.is_alive()
        assert len(supervisor.processes) == 2
        supervisor.cancel_signal()
        thread.join(5)
        assert not thread.is_alive()
        assert all(process.poll() is not None for _, process in supervisor.processes)
        events = all_events(m)
        assert [event['kind'] for event in events].count('command_exit') == 2
        assert events[-1]['payload']['status'] == 'stopped'
        assert events[-1]['payload']['ready'] is False
        before = m.journal_api.read_events(0)['cursor']
        supervisor.journal.emit('stdout', {'text': 'late output'})
        assert m.journal_api.read_events(0)['cursor'] == before
    finally:
        supervisor.cancel_signal()
        thread.join(5)
        supervisor.journal.db.close()


def test_unexpected_ready_server_exit_fails_and_stops_other_server(session_module, monkeypatch):
    m = session_module
    monkeypatch.setattr(m.Supervisor, 'healthy', lambda *_: True)
    value = plan()
    value['website'] = {**command('import time; time.sleep(20)'), 'port': 9876, 'path': '/'}
    supervisor, thread = launch_supervisor(m, value)
    try:
        wait_for(lambda: m.journal_api.read_events(0).get('ready'))
        os.killpg(supervisor.processes[0][1].pid, signal.SIGTERM)
        thread.join(5)
        assert not thread.is_alive()
        events = all_events(m)
        assert events[-1]['payload']['status'] == 'failed'
        assert 'api startup command exited' in events[-1]['payload']['reason']
        assert [event['kind'] for event in events].count('command_exit') == 2
        assert all(process.poll() is not None for _, process in supervisor.processes)
    finally:
        supervisor.cancel_signal()
        thread.join(5)
        supervisor.journal.db.close()


@pytest.mark.parametrize('phase', ['setup', 'startup'])
def test_timeouts_are_terminal_and_kill_commands(session_module, monkeypatch, phase):
    m = session_module
    monkeypatch.setattr(m.Supervisor, 'healthy', lambda *_: False)
    value = plan([command('import time; time.sleep(20)')] if phase == 'setup' else [])
    supervisor, thread = launch_supervisor(m, value, setup_timeout=0.1, startup_timeout=0.1)
    thread.join(5)
    try:
        assert not thread.is_alive()
        events = all_events(m)
        assert events[-1]['payload']['status'] == 'failed'
        assert 'timed out' in events[-1]['payload']['reason']
        assert any(event['kind'] == 'command_exit' for event in events)
        assert all(process.poll() is not None for _, process in supervisor.processes)
    finally:
        supervisor.cancel_signal()
        thread.join(5)
        supervisor.journal.db.close()


def test_environment_is_allowlisted_and_has_no_docker_settings(session_module, monkeypatch):
    m = session_module
    monkeypatch.setenv('PLATFORM_TOKEN', 'must-not-be-inherited')
    monkeypatch.setenv('DOCKER_HOST', 'unix:///platform.sock')
    setup = command("import os,json; print(json.dumps(dict(os.environ))); raise SystemExit(4)")
    supervisor, thread = launch_supervisor(m, plan([setup]))
    thread.join(5)
    try:
        text = json.dumps(all_events(m))
        assert 'must-not-be-inherited' not in text
        assert 'PLATFORM_TOKEN' not in text
        assert 'DOCKER_HOST' not in text
        assert 'npm_config_cache' in text
        assert 'UV_CACHE_DIR' in text
    finally:
        supervisor.journal.db.close()


def test_reopening_same_execution_never_reexecutes_setup(session_module):
    m = session_module
    value = plan([command("from pathlib import Path; Path('count').write_text('once'); raise SystemExit(2)")])
    execution_id = str(uuid.uuid4())
    first = m.Supervisor(value, execution_id)
    first.execute()
    first.journal.db.close()
    cursor = m.journal_api.read_events(0)['cursor']
    (m.ROOT / 'count').unlink()
    retry = m.Supervisor(value, execution_id)
    retry.execute()
    try:
        assert not (m.ROOT / 'count').exists()
        assert m.journal_api.read_events(0)['cursor'] == cursor
        with pytest.raises(RuntimeError, match='previous preview'):
            m.Supervisor(value, str(uuid.uuid4()))
    finally:
        retry.journal.db.close()


def test_atomic_bootstrap_claim_reattaches_before_journal_exists(session_module, monkeypatch):
    m = session_module
    calls = []
    monkeypatch.setattr(m.subprocess, 'Popen', lambda *args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(pid=4321))
    monkeypatch.setattr(m.os, 'kill', lambda *_: None)
    execution_id = str(uuid.uuid4())
    assert m.start(execution_id)['execution_id'] == execution_id
    assert m.start(execution_id)['execution_id'] == execution_id
    assert len(calls) == 1
    assert not any(key.startswith('DOCKER_') for key in calls[0][1]['env'])
    with pytest.raises(RuntimeError, match='previous preview'):
        m.start(str(uuid.uuid4()))


def test_missing_bootstrap_supervisor_is_interrupted_not_restarted(session_module, monkeypatch):
    m = session_module
    execution_id = str(uuid.uuid4())
    m.OWNER.write_text(json.dumps({'execution_id': execution_id, 'pid': 4321}))

    def missing(*_):
        raise ProcessLookupError

    monkeypatch.setattr(m.os, 'kill', missing)
    assert m.start(execution_id)['state'] == 'interrupted'


def test_secret_input_failure_is_closed_before_command_execution(session_module):
    m = session_module
    (m.ROOT / '.env').write_text('PASSWORD=' + 'x' * 65536)
    supervisor = m.Supervisor(plan(), str(uuid.uuid4()))
    supervisor.execute()
    try:
        events = all_events(m)
        assert not supervisor.processes
        assert events[-1]['payload']['status'] == 'failed'
        assert events[-1]['payload']['reason'] == 'Project secret configuration could not be loaded safely'
    finally:
        supervisor.journal.db.close()


def test_dead_supervisor_is_reconciled_without_running_commands(session_module, monkeypatch):
    m = session_module
    execution_id = str(uuid.uuid4())
    journal = m.Journal(execution_id, m.LockedRedactor())
    journal.emit('command_start', {'command': 0, 'argv': ['python', '-m', 'app']})
    journal.db.close()
    m.OWNER.write_text(json.dumps({'execution_id': execution_id, 'pid': 4321}))
    monkeypatch.setattr(m, 'alive', lambda *_: False)
    current = m.read_events(0)
    assert current['state'] == 'interrupted'
    assert current['events'][-1]['payload']['reason'] == 'Preview supervisor stopped unexpectedly'
    assert m.read_events(current['cursor'])['events'] == []


def test_journal_output_limits_keep_gaps_and_final_metadata(session_module, monkeypatch):
    m = session_module
    monkeypatch.setattr(m.journal_api, 'OUTPUT_BYTES', 1024)
    monkeypatch.setattr(m.journal_api, 'OUTPUT_EVENTS', 3)
    journal = m.Journal(str(uuid.uuid4()), m.LockedRedactor())
    try:
        journal.emit('command_start', {'command': 0, 'argv': ['python']})
        for _ in range(10):
            journal.emit('stdout', {'command': 0, 'text': 'x' * 512})
        journal.emit('command_exit', {'command': 0, 'exit_code': 5})
        journal.status('failed', reason='Setup failed')
        events = all_events(m)
        assert any(event['kind'] == 'gap' for event in events)
        assert sum(len(event['payload'].get('text', '').encode()) for event in events) <= 1024
        assert [event['kind'] for event in events].count('command_start') == 1
        assert [event['kind'] for event in events].count('command_exit') == 1
        assert events[-1]['payload']['status'] == 'failed'
    finally:
        journal.db.close()


@pytest.mark.parametrize('bad', [{'cwd': '../escape', 'argv': ['python']}, {'cwd': '.', 'argv': ['docker', 'info']}, {'cwd': '.', 'argv': ['python'], 'env': {'DOCKER_HOST': 'unix:///socket'}}])
def test_invalid_commands_fail_before_any_project_process(session_module, bad):
    m = session_module
    supervisor = m.Supervisor(plan([bad]), str(uuid.uuid4()))
    supervisor.execute()
    try:
        assert not supervisor.processes
        assert all_events(m)[-1]['payload']['status'] == 'failed'
    finally:
        supervisor.journal.db.close()


def test_health_uses_local_application_path_without_proxy(session_module, monkeypatch):
    m = session_module
    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self, size):
            assert size == 1024

    class Opener:
        def open(self, url, *, timeout):
            seen.append((url, timeout))
            return Response()

    def build(proxy):
        assert proxy.proxies == {}
        return Opener()

    monkeypatch.setattr(m.request, 'build_opener', build)
    supervisor = m.Supervisor(plan(), str(uuid.uuid4()))
    try:
        assert supervisor.healthy(plan()['api'])
        assert seen == [('http://127.0.0.1:8765/health', 0.5)]
    finally:
        supervisor.journal.db.close()

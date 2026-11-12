import importlib
import json
from pathlib import Path

import pytest

from app.services.preview_native_runtime import (
    APPLY_SOURCE,
    UPLOAD,
    NativeRuntime,
    archive_files,
    replay_events,
    snapshot_secret_values,
    source_snapshot,
)


@pytest.fixture
def session_module(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / 'app/services'))
    module = importlib.import_module('preview_native_session')
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'STATE', tmp_path / 'journal.sqlite')
    return module


def test_selected_checkout_snapshot_is_read_only_and_excludes_outside_inputs(tmp_path):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    (checkout / '.env').write_text('PASSWORD=project-only\n')
    (tmp_path / 'other-chat').mkdir()
    (tmp_path / 'other-chat/private').write_text('other chat secret')
    (checkout / 'outside').symlink_to(tmp_path / 'other-chat', target_is_directory=True)
    (checkout / 'redirect').symlink_to(tmp_path / 'other-chat/private')
    (checkout / '.docker').mkdir()
    (checkout / '.docker/config.json').write_text('platform registry credential')
    before = (checkout / '.env').read_bytes()
    snapshot = source_snapshot(checkout)
    assert set(snapshot) == {'.env'}
    assert snapshot['.env'][0] == before
    assert (checkout / '.env').read_bytes() == before


@pytest.mark.parametrize('replacement', ['hardlink', 'fifo'])
def test_source_snapshot_rechecks_opened_file_before_reading(tmp_path, monkeypatch, replacement):
    import os

    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    victim = checkout / 'victim.txt'
    victim.write_text('selected checkout data')
    original_open = os.open
    changed = False

    def race_open(name, flags, *args, **kwargs):
        nonlocal changed
        if name == 'victim.txt' and not changed:
            changed = True
            if replacement == 'hardlink':
                os.link(victim, tmp_path / 'outside-link')
            else:
                victim.unlink()
                os.mkfifo(victim)
        return original_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, 'open', race_open)
    with pytest.raises(RuntimeError, match='changed before synchronization'):
        source_snapshot(checkout)
    assert changed


def test_native_command_and_custom_named_environment_secrets_precede_journal(session_module, tmp_path):
    m = session_module
    (tmp_path / 'settings').mkdir()
    (tmp_path / 'settings/credentials').write_text('PASSWORD=custom-file-secret\n')
    plan = {'commands': [{'cwd': '.', 'argv': [
        'docker', 'compose', '--env-file', 'settings/credentials',
        'run', '-e', 'API_TOKEN=command-secret', 'api',
    ]}]}
    redactor = m.SecretRedactor(m.known_secrets(plan))
    assert redactor.redact('custom-file-secret command-secret') == '[REDACTED] [REDACTED]'
    assert 'command-secret' not in str(redactor.redact_json(plan))


def test_changed_credentials_are_acknowledged_before_exposure(session_module, tmp_path, monkeypatch):
    import tempfile

    m = session_module
    (tmp_path / '.env').write_text('PASSWORD=previous-credential\n')
    with tempfile.TemporaryDirectory(prefix='pv-', dir='/tmp') as short:
        monkeypatch.setattr(m, 'STATE', Path(short) / 'j.sqlite')
        supervisor = m.Supervisor({'commands': []}, 'credential-rotation')
        supervisor.start_control()
        try:
            stage = Path(short) / 'stage'
            stage.mkdir()
            values = snapshot_secret_values({
                '.env': (b'PASSWORD=rotated-credential\n', 0o600),
                'settings/custom': (b'API_TOKEN=custom-credential\n', 0o600),
                'compose.yml': (b'services:\n  app:\n    environment:\n      SECRET: compose-credential\n', 0o644),
            })
            (stage / 'secrets.json').write_text(json.dumps(values))
            m.prepare_sync(stage)
            with supervisor.journal.lock:
                redactor = supervisor.journal.redactor
                text = redactor.feed('watch', 'previous-credential rotated-')
                text += redactor.feed('watch', 'credential custom-credential compose-credential')
                supervisor.journal.emit('stdout', {'text': text})
            output = m.read_events(0)['events'][-1]['payload']['text']
            assert output == '[REDACTED] [REDACTED] [REDACTED] [REDACTED]'
        finally:
            supervisor.cancel_signal()
            supervisor.cleanup()
            supervisor.journal.db.close()


def test_source_update_is_not_applied_when_secret_acknowledgement_fails(tmp_path, monkeypatch):
    import uuid
    from types import SimpleNamespace

    chat = uuid.uuid4()
    root = tmp_path / str(chat)
    root.mkdir()
    (root / '.env').write_text('PASSWORD=rotated-credential\n')
    runtime = NativeRuntime(SimpleNamespace(WORKSPACE_ROOT=tmp_path))
    runtime.previous[chat] = {'.env': 'previous-hash'}
    calls = []
    monkeypatch.setattr(runtime, 'upload', lambda *_args, **_kwargs: None)

    def execute(_chat, argv):
        calls.append(argv)
        if 'prepare-sync' in argv:
            raise RuntimeError('No credential acknowledgement')

    monkeypatch.setattr(runtime, 'exec', execute)
    with pytest.raises(RuntimeError, match='acknowledgement'):
        runtime.sync(chat)
    assert not any(APPLY_SOURCE in call for call in calls)
    assert runtime.previous[chat] == {'.env': 'previous-hash'}


def test_watch_recreation_refreshes_routes_after_bounded_missing_service(session_module, monkeypatch):
    from types import SimpleNamespace

    m = session_module
    plan = {'commands': [{'cwd': '.', 'argv': ['docker', 'compose', 'watch']}], 'application': {'port': 8765}}
    supervisor = m.Supervisor(plan, 'watch-recreation')
    ticks = iter([False, False, False, True])
    supervisor.cancel = SimpleNamespace(wait=lambda _delay: next(ticks), set=lambda: None)
    monkeypatch.setattr(supervisor, 'start_control', lambda: None)
    monkeypatch.setattr(m, 'validate_command', lambda _command: None)
    monkeypatch.setattr(m, 'native_model', lambda _command: {})
    monkeypatch.setattr(supervisor, 'add_model_secrets', lambda _model: None)
    route = {'8765': {'service': 'website', 'target': 8765, 'role': 'website'}}
    monkeypatch.setattr(m, 'application_routes', lambda *_args: route)
    monkeypatch.setattr(supervisor, 'run', lambda *_args, **_kwargs: SimpleNamespace(poll=lambda: None))
    routes = iter([
        {'8765': {**route['8765'], 'container': 'first'}}, None,
        {'8765': {**route['8765'], 'container': 'replacement'}},
    ])
    monkeypatch.setattr(supervisor, 'inspect_routes', lambda *_args: next(routes))
    monkeypatch.setattr(supervisor, 'ready', lambda *_args: True)
    supervisor.execute()
    statuses = [event['payload'] for event in m.read_events(0)['events'] if event['kind'] == 'status']
    published = [event['details']['routes']['8765']['container'] for event in statuses if event.get('ready')]
    assert published == ['first', 'replacement']
    assert any(event['status'] == 'running' and not event['ready'] for event in statuses)
    assert statuses[-1]['status'] == 'stopped'


@pytest.mark.parametrize('expired', [False, True])
def test_readiness_probe_timeouts_recover_only_within_startup_deadline(session_module, tmp_path, monkeypatch, expired):
    from types import SimpleNamespace

    m = session_module
    plan = {'commands': [{'cwd': '.', 'argv': ['docker', 'compose', 'watch']}], 'application': {'port': 8765}}
    supervisor = m.Supervisor(plan, 'bounded-probe-timeouts')
    ticks = iter([False, False, False, True])
    supervisor.cancel = SimpleNamespace(wait=lambda _delay: next(ticks), set=lambda: None)
    now = [0]
    monkeypatch.setattr(m, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(supervisor, 'start_control', lambda: None)
    monkeypatch.setattr(m, 'validate_command', lambda command: (tmp_path, command['argv'], dict(m.ENV)))
    monkeypatch.setattr(m, 'native_model', lambda _command: {})
    monkeypatch.setattr(supervisor, 'add_model_secrets', lambda _model: None)
    route = {'8765': {'service': 'website', 'target': 8765, 'role': 'website'}}
    monkeypatch.setattr(m, 'application_routes', lambda *_args: route)
    monkeypatch.setattr(supervisor, 'run', lambda *_args, **_kwargs: SimpleNamespace(poll=lambda: None))
    monkeypatch.setenv('PREVIEW_HELPER_IMAGE', 'sha256:local-helper')
    probes = []

    def probe(argv, **kwargs):
        kind = 'inspect' if 'ps' in argv else 'http'
        probes.append(kind)
        assert kwargs['timeout'] == (5 if kind == 'inspect' else 8)
        if probes.count(kind) == 1:
            if expired:
                now[0] = 181
            raise m.subprocess.TimeoutExpired(argv, kwargs['timeout'])
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            'Service': 'website', 'State': 'running', 'ID': 'application',
        }).encode())

    monkeypatch.setattr(m.subprocess, 'run', probe)
    supervisor.execute()
    statuses = [event['payload'] for event in m.read_events(0)['events'] if event['kind'] == 'status']
    if expired:
        assert probes == ['inspect']
        assert statuses[-1]['status'] == 'failed'
        assert 'did not become ready' in statuses[-1]['reason']
        assert not any(event.get('ready') for event in statuses)
    else:
        assert probes == ['inspect', 'inspect', 'http', 'inspect', 'http']
        assert any(event.get('ready') for event in statuses)
        assert statuses[-1]['status'] == 'stopped'
        assert not any(event['status'] == 'failed' for event in statuses)


def test_cancellation_drains_delayed_child_output_before_final_status(session_module, tmp_path, monkeypatch):
    import sys
    import threading
    import time

    m = session_module
    plan = {'commands': [{'cwd': '.', 'argv': ['docker', 'compose', 'watch']}], 'application': {'port': 8765}}
    supervisor = m.Supervisor(plan, 'delayed-cancellation')
    script = "import signal,time,sys\ndef stop(*_):\n time.sleep(0.8)\n print('trailing cancellation output',flush=True)\n sys.exit(0)\nsignal.signal(signal.SIGTERM,stop)\nprint('ready for cancellation',flush=True)\nwhile True: time.sleep(0.1)\n"
    monkeypatch.setattr(supervisor, 'start_control', lambda: None)
    monkeypatch.setattr(m, 'validate_command', lambda _command: (tmp_path, [sys.executable, '-u', '-c', script], dict(m.ENV)))
    monkeypatch.setattr(m, 'native_model', lambda _command: {})
    monkeypatch.setattr(supervisor, 'add_model_secrets', lambda _model: None)
    route = {'8765': {'service': 'website', 'target': 8765, 'role': 'website', 'container': 'application'}}
    monkeypatch.setattr(m, 'application_routes', lambda *_args: route)
    monkeypatch.setattr(supervisor, 'inspect_routes', lambda *_args: route)
    monkeypatch.setattr(supervisor, 'ready', lambda *_args: True)
    worker = threading.Thread(target=supervisor.execute, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if any(event['payload'].get('text') == 'ready for cancellation\n' for event in m.read_events(0)['events']):
                break
            threading.Event().wait(0.01)
        else:
            pytest.fail('Child did not arm its real SIGTERM handler')
    finally:
        supervisor.cancel_signal()
        worker.join(10)
    assert not worker.is_alive()
    events = m.read_events(0)['events']
    trailing = next(event for event in events if 'trailing cancellation output' in event['payload'].get('text', ''))
    exits = [event for event in events if event['kind'] == 'command_exit']
    assert len(exits) == 1 and exits[0]['payload']['exit_code'] == 0
    assert trailing['cursor'] < exits[0]['cursor'] < events[-1]['cursor']
    assert events[-1]['payload']['status'] == 'stopped'


def test_archive_contains_regular_owned_files_only():
    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(archive_files({'docs/start.md': (b'text', 0o644)}))) as archive:
        entry = archive.getmembers()[0]
        assert entry.name == 'docs/start.md'
        assert entry.isfile() and entry.uid == 1000 and entry.gid == 1000


def test_streamed_upload_creates_regular_files_without_rootfs_extraction(tmp_path):
    import subprocess
    import sys

    result = subprocess.run([sys.executable, '-I', '-c', UPLOAD, str(tmp_path)],
                            input=archive_files({'stage/docs/start.md': (b'checkout text', 0o640)}),
                            capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'stage/docs/start.md').read_bytes() == b'checkout text'
    assert (tmp_path / 'stage/docs/start.md').stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize('redirect', [False, True])
def test_streamed_upload_rejects_escape_and_redirected_parents(tmp_path, redirect):
    import subprocess
    import sys

    root = tmp_path / 'staging'
    root.mkdir()
    if redirect:
        (root / 'redirect').symlink_to(tmp_path, target_is_directory=True)
    name = 'redirect/escape.txt' if redirect else '../escape.txt'
    result = subprocess.run([sys.executable, '-I', '-c', UPLOAD, str(root)],
                            input=archive_files({name: (b'must not escape', 0o644)}),
                            capture_output=True)
    assert result.returncode != 0
    assert not (tmp_path / 'escape.txt').exists()


@pytest.mark.parametrize('service', [
    {'privileged': True},
    {'network_mode': 'host'},
    {'volumes': [{'type': 'bind', 'source': '/var/run/docker.sock'}]},
    {'build': {'context': 'https://example.com/project'}},
    {'devices': ['/dev/kvm']},
    {'build': {'context': '.', 'entitlements': ['security.insecure']}},
])
def test_native_config_rejects_host_access_before_start(session_module, service):
    with pytest.raises((ValueError, OSError)):
        session_module.validate_model({'services': {'website': service}})


def test_local_bind_build_and_named_storage_use_native_semantics(session_module, tmp_path):
    (tmp_path / 'app').mkdir()
    (tmp_path / 'app/Dockerfile').write_text('FROM scratch\n')
    session_module.validate_model({
        'services': {'website': {
            'build': {'context': str(tmp_path / 'app'), 'dockerfile': 'Dockerfile'},
            'volumes': [{'type': 'bind', 'source': str(tmp_path / 'app')}, {'type': 'volume', 'source': 'data'}],
        }}, 'volumes': {'data': {'name': 'fixed-data'}},
    })


def test_application_routes_exclude_auxiliary_tools(session_module):
    model = {'services': {
        'website': {'ports': [{'published': '8765', 'target': 80}], 'depends_on': {'api': {}}},
        'api': {'expose': ['8000'], 'depends_on': {'db': {}}},
        'db': {'image': 'postgres', 'ports': [{'published': '15432', 'target': 5432}]},
        'admin': {'ports': [{'published': '8080', 'target': 8080}]},
    }}
    routes = session_module.application_routes(model, {'port': 8765})
    assert set(routes) == {'8765', '8000'}
    assert routes['8765']['target'] == 80
    with pytest.raises(ValueError, match='auxiliary'):
        session_module.application_routes(model, {'port': 8080})


def test_documented_api_only_exposed_port_keeps_swagger_entrypoint(session_module):
    model = {'services': {'api': {'expose': ['8766']}}}
    routes = session_module.application_routes(model, {'port': 8766, 'path': '/docs/'})
    assert routes == {'8766': {'service': 'api', 'target': 8766, 'role': 'website'}}
    model['services']['another'] = {'expose': ['8766']}
    with pytest.raises(ValueError, match='one resolved service'):
        session_module.application_routes(model, {'port': 8766, 'path': '/docs/'})


def test_native_journal_redacts_before_write_and_reports_source_gaps(session_module, monkeypatch):
    from preview_redaction import SecretRedactor
    monkeypatch.setattr(session_module, 'OUTPUT_BYTES', 12)
    journal = session_module.Journal('stable-execution', SecretRedactor(['private-password']))
    journal.emit('command_start', {'argv': ['command', 'private-password']})
    journal.emit('stdout', {'text': 'private-password'})
    journal.emit('stderr', {'text': 'newest output'})
    journal.status('failed', reason='failed with private-password')
    rows = journal.db.execute('SELECT payload FROM events').fetchall()
    assert all('private-password' not in row[0] for row in rows)
    replay = session_module.read_events(0)
    assert replay['execution_id'] == 'stable-execution'
    assert replay['state'] == 'failed' and replay['ready'] is False
    assert any(event['kind'] == 'gap' for event in replay['events'])
    assert any(event['kind'] == 'command_start' for event in replay['events'])
    assert replay['events'][-1]['payload']['reason'] == 'failed with [REDACTED]'


def test_terminal_replay_preserves_gap_remainder_without_mutating_cache():
    cached = [{'cursor': 1, 'kind': 'status', 'payload': {}},
              {'cursor': 2, 'kind': 'gap', 'payload': {'through_cursor': 50}},
              {'cursor': 51, 'kind': 'status', 'payload': {'status': 'failed'}}]
    replay = replay_events(cached, 20)
    assert [event['cursor'] for event in replay] == [21, 51]
    assert replay[0]['payload']['through_cursor'] == 50
    assert cached[1]['cursor'] == 2
    assert replay_events(cached, 50) == [cached[-1]]


def test_dead_native_supervisor_retains_history_and_becomes_interrupted(session_module, monkeypatch):
    from preview_redaction import SecretRedactor

    journal = session_module.Journal('stable-execution', SecretRedactor())
    journal.emit('command_start', {'command': 0, 'argv': ['docker', 'compose', 'watch']})
    journal.emit('stdout', {'text': 'retained output'})
    journal.db.close()
    session_module.STATE.with_suffix('.owner.json').write_text(json.dumps({'execution_id': 'stable-execution', 'pid': 123}))
    monkeypatch.setattr(session_module, 'supervisor_alive', lambda _pid: False)
    current = session_module.runtime_events(0)
    assert current['state'] == 'interrupted'
    assert current['events'][1]['kind'] == 'command_start'
    assert current['events'][2]['payload']['text'] == 'retained output'
    assert session_module.runtime_events(current['cursor'])['events'] == []


def test_dead_native_supervisor_before_journal_does_not_remain_starting(session_module, monkeypatch):
    session_module.STATE.with_suffix('.owner.json').write_text(json.dumps({'execution_id': 'stable-execution', 'pid': 123}))
    monkeypatch.setattr(session_module, 'supervisor_alive', lambda _pid: False)
    current = session_module.runtime_events(0)
    assert current['state'] == 'interrupted'
    assert 'before creating' in current['events'][-1]['payload']['reason']


def test_native_bootstrap_retry_does_not_execute_again(session_module, monkeypatch):
    from preview_redaction import SecretRedactor

    journal = session_module.Journal('stable-execution', SecretRedactor())
    journal.db.close()
    monkeypatch.setattr(session_module.subprocess, 'Popen', lambda *_args, **_kwargs: pytest.fail('must not launch twice'))
    assert session_module.start('stable-execution')['execution_id'] == 'stable-execution'
    with pytest.raises(ValueError, match='previous preview'):
        session_module.start('different-execution')


def test_preparation_does_not_allow_host_paths_or_run_privileges(session_module):
    for argv in (['cp', '/etc/passwd', '.env'], ['docker', 'compose', 'run', '--privileged', 'api'], ['docker', 'compose', '-f', '/etc/compose.yml', 'watch']):
        with pytest.raises(ValueError):
            session_module.validate_command({'cwd': '.', 'argv': argv, 'env': {}})

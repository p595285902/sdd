import importlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.preview_native_runtime import (
    APPLY_SOURCE,
    UPLOAD,
    EventReader,
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


@pytest.fixture
def route_runtime(monkeypatch):
    runtime = NativeRuntime(SimpleNamespace())
    runtime.helper_id = 'sha256:trusted-public-helper'
    helpers, calls = {}, []

    def execute(chat, argv, **_kwargs):
        calls.append((chat, argv))
        if argv[:2] == ['docker', 'inspect']:
            helper = helpers.get((chat, argv[-1]))
            if helper is None:
                raise RuntimeError('No such helper')
            return json.dumps(helper).encode()
        if argv[:3] == ['docker', 'rm', '-f']:
            helpers.pop((chat, argv[-1]), None)
            return b''
        assert argv[:3] == ['docker', 'run', '-d']
        name = argv[argv.index('--name') + 1]
        helpers[(chat, name)] = {'State': {'Running': True}, 'Image': runtime.helper_id,
            'HostConfig': {'NetworkMode': next(value.split('=', 1)[1] for value in argv if value.startswith('--network=')),
                           'ReadonlyRootfs': True, 'Privileged': False, 'CapDrop': ['ALL'],
                           'SecurityOpt': ['no-new-privileges:true'], 'PidsLimit': 128}, 'Mounts': []}
        return b'fixed-helper-container'

    monkeypatch.setattr(runtime, 'exec', execute)
    current = {'execution_id': str(uuid.uuid4()), 'details': {'routes': {
        '8765': {'container': 'a' * 64, 'target': 8765, 'role': 'website'},
    }}}
    return runtime, current, helpers, calls


def test_forwarding_reuses_only_the_readonly_namespace_not_request_processes(route_runtime):
    runtime, current, helpers, calls = route_runtime
    chat = uuid.uuid4()
    first = runtime.browser_command(current, '8765', chat)
    second = runtime.browser_command(current, '8765', chat)
    assert first == second and first[0][:3] == ['docker', 'exec', '-i']
    assert first[1] == '8765'
    runs = [argv for _, argv in calls if argv[:3] == ['docker', 'run', '-d']]
    assert len(runs) == 1
    assert '--read-only' in runs[0] and '--cap-drop=ALL' in runs[0]
    assert '--security-opt=no-new-privileges:true' in runs[0] and '--pids-limit=128' in runs[0]
    assert all(owner == chat for owner, _ in calls)
    assert next(iter(helpers.values()))['Mounts'] == []


@pytest.mark.parametrize('change', ['recreated-app', 'stopped-helper', 'wrong-image', 'wrong-network', 'writable-helper'])
def test_forwarding_rebuilds_stale_or_modified_helpers_before_any_request(route_runtime, change):
    runtime, current, helpers, calls = route_runtime
    chat = uuid.uuid4()
    prefix, _ = runtime.browser_command(current, '8765', chat)
    helper = helpers[(chat, prefix[-1])]
    if change == 'recreated-app':
        current['details']['routes']['8765']['container'] = 'b' * 64
    elif change == 'stopped-helper':
        helper['State']['Running'] = False
    elif change == 'wrong-image':
        helper['Image'] = 'project-image'
    elif change == 'wrong-network':
        helper['HostConfig']['NetworkMode'] = 'host'
    else:
        helper['HostConfig']['ReadonlyRootfs'] = False
    runtime.browser_command(current, '8765', chat)
    assert len([argv for _, argv in calls if argv[:3] == ['docker', 'run', '-d']]) == 2
    fresh = helpers[(chat, prefix[-1])]
    assert fresh['HostConfig']['NetworkMode'] == 'container:' + current['details']['routes']['8765']['container']
    assert fresh['Image'] == runtime.helper_id and fresh['HostConfig']['ReadonlyRootfs']


def test_forwarding_helpers_stay_chat_scoped_and_terminal_cleanup_forgets_only_owner(route_runtime):
    runtime, current, _helpers, _calls = route_runtime
    first, second = uuid.uuid4(), uuid.uuid4()
    runtime.browser_command(current, '8765', first)
    runtime.browser_command({**current, 'execution_id': str(uuid.uuid4())}, '8765', second)
    assert set(runtime.browser_helpers) == {(first, '8765'), (second, '8765')}
    runtime.terminal[first] = {}
    runtime.before_stop(first, {'Config': {'Labels': {'sdd.preview.native-execution': current['execution_id']}}})
    assert set(runtime.browser_helpers) == {(second, '8765')}


def test_unregistered_or_invalid_routes_never_create_a_forwarder(route_runtime):
    runtime, current, helpers, calls = route_runtime
    with pytest.raises(ValueError):
        runtime.browser_command(current, '8025', uuid.uuid4())
    current['details']['routes']['8765']['container'] = '../other-chat'
    with pytest.raises(ValueError):
        runtime.browser_command(current, '8765', uuid.uuid4())
    assert not calls and not helpers


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


def event_server_command(session_module, state, *, setup=''):
    script = (
        'import sys; from pathlib import Path; '
        'sys.path.insert(0,sys.argv[1]); import preview_native_session as session; '
        'session.STATE=Path(sys.argv[2]); ' + (setup + '; ' if setup else '') + 'session.serve_events()'
    )
    return [sys.executable, '-I', '-u', '-c', script, str(Path(session_module.__file__).parent), str(state)]


@pytest.fixture
def event_transport(session_module, monkeypatch):
    from app.services import preview_native_runtime as module

    states, spawned = {}, []
    popen = subprocess.Popen
    def launch(argv, **kwargs):
        assert argv[1:5] == ['exec', '-i', '--user', '1000:1000']
        assert argv[-4:] == ['python3', '-u', module.RUNNER, 'events-serve']
        process = popen(event_server_command(session_module, states[argv[5]]), **kwargs)
        spawned.append(process)
        return process
    monkeypatch.setattr(module.subprocess, 'Popen', launch)
    controller = SimpleNamespace(SOCKET='/never-open-docker.sock', container_name=lambda chat: chat.hex)
    runtime = NativeRuntime(controller)
    try:
        yield runtime, states, spawned
    finally:
        runtime.close_readers()
        for process in spawned:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)


def test_persistent_event_reader_reads_fresh_redacted_pages_without_respawning(session_module, event_transport):
    from preview_redaction import SecretRedactor

    runtime, states, spawned = event_transport
    chat = uuid.uuid4()
    states[chat.hex] = session_module.STATE
    journal = session_module.Journal('execution-a', SecretRedactor(['private-secret']))
    try:
        first = runtime.read(chat, 0)
        assert len(spawned) == 1 and first['cursor'] == 1
        journal.emit('stdout', {'text': 'new private-secret output'})
        second = runtime.read(chat, first['cursor'])
        assert second['events'][0]['payload']['text'] == 'new [REDACTED] output'
        assert second['cursor'] == 2 and len(spawned) == 1
        assert runtime.read(chat, second['cursor'])['events'] == []
        assert len(spawned) == 1 and spawned[0].poll() is None
        runtime.close_reader(chat)
        assert spawned[0].poll() is not None and not runtime.readers
        assert runtime.read(chat, 0) == runtime.read(chat, 0)
        assert len(spawned) == 2  # Reopened read, never a repeated project command.
    finally:
        journal.db.close()


def test_event_reader_chat_separation_and_serialized_concurrent_requests(session_module, event_transport, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from preview_redaction import SecretRedactor

    runtime, states, spawned = event_transport
    chats = [uuid.uuid4(), uuid.uuid4()]
    for index, chat in enumerate(chats):
        state = session_module.STATE.parent / f'chat-{index}.sqlite'
        states[chat.hex] = state
        monkeypatch.setattr(session_module, 'STATE', state)
        journal = session_module.Journal(f'execution-{index}', SecretRedactor())
        journal.emit('stdout', {'text': f'chat {index} only'})
        journal.db.close()
    requests = chats * 8
    with ThreadPoolExecutor(max_workers=8) as pool:
        pages = list(pool.map(lambda chat: runtime.read(chat, 1), requests))
    assert len(spawned) == 2
    for chat, page in zip(requests, pages, strict=True):
        index = chats.index(chat)
        assert page['execution_id'] == f'execution-{index}'
        assert page['events'][0]['payload']['text'] == f'chat {index} only'


def test_event_reader_eof_restarts_only_the_idempotent_read(session_module, event_transport):
    from preview_redaction import SecretRedactor

    runtime, states, spawned = event_transport
    chat = uuid.uuid4()
    states[chat.hex] = session_module.STATE
    journal = session_module.Journal('retry-read', SecretRedactor())
    journal.db.close()
    assert runtime.read(chat, 0)['execution_id'] == 'retry-read'
    spawned[0].kill()
    spawned[0].wait(timeout=2)
    assert runtime.read(chat, 1)['events'] == []
    assert len(spawned) == 2 and spawned[1].poll() is None


@pytest.mark.parametrize('cursor', [-1, True, 0.1, '1', 2**63])
def test_runtime_rejects_bad_event_cursor_before_starting_process(event_transport, cursor):
    runtime, _, spawned = event_transport
    with pytest.raises(ValueError, match='cursor'):
        runtime.read(uuid.uuid4(), cursor)
    assert not spawned


@pytest.mark.parametrize('script,expected', [
    ("import sys; sys.stdin.buffer.readline(); sys.stdout.write('project-secret\\n'); sys.stdout.flush()", 'invalid protocol'),
    ("import sys; sys.stdin.buffer.readline(); sys.stdout.write('{\\\"after\\\":999,\\\"result\\\":{}}\\n'); sys.stdout.flush()", 'invalid protocol'),
    ("import sys; sys.stdin.buffer.readline(); sys.stdout.buffer.write(b'x'*4097); sys.stdout.flush()", 'exceeded'),
    ("import sys,threading; sys.stdin.buffer.readline(); threading.Event().wait()", 'timed out'),
    ("import sys; sys.stdin.buffer.readline(); sys.stdout.write('{partial'); sys.stdout.flush()", 'exited'),
])
def test_event_reader_rejects_malformed_oversized_hung_or_eof_process(script, expected):
    reader = EventReader([sys.executable, '-I', '-u', '-c', script], os.environ, timeout=1, limit=4096)
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match=expected) as error:
            reader.read(0)
        assert 'project-secret' not in str(error.value)
    finally:
        reader.close()
    assert reader.process.poll() is not None and time.monotonic() - started < 3


@pytest.mark.parametrize('cursor_line', [b'-1\n', b'true\n', b'1.0\n', b'01\n', b'9223372036854775808\n', b'1'*33, b'2'])
def test_event_server_rejects_invalid_cursor_protocol_and_eof(session_module, cursor_line):
    result = subprocess.run(event_server_command(session_module, session_module.STATE), input=cursor_line,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {'error': 'invalid_request'}
    assert not result.stderr


def test_event_server_missing_journal_can_recover_and_errors_are_sanitized(session_module, event_transport):
    from app.services.preview_native_runtime import EventJournalNotReady
    from preview_redaction import SecretRedactor

    runtime, states, spawned = event_transport
    chat = uuid.uuid4()
    states[chat.hex] = session_module.STATE
    with pytest.raises(EventJournalNotReady):
        runtime.read(chat, 0)
    journal = session_module.Journal('late-journal', SecretRedactor())
    journal.db.close()
    assert runtime.read(chat, 0)['execution_id'] == 'late-journal' and len(spawned) == 1


def test_event_server_empty_eof_and_unavailable_errors_do_not_expose_exception_text(session_module):
    command = event_server_command(session_module, session_module.STATE)
    empty = subprocess.run(command, input=b'', stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
    assert empty.returncode == 0 and not empty.stdout and not empty.stderr
    command = event_server_command(session_module, session_module.STATE,
        setup="session.runtime_events=lambda _after: (_ for _ in ()).throw(RuntimeError('project-secret'))")
    result = subprocess.run(command, input=b'0\n', stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
    assert result.returncode == 0 and json.loads(result.stdout) == {'after': 0, 'error': 'unavailable'}
    assert b'project-secret' not in result.stdout + result.stderr


def test_native_stop_preserves_all_terminal_pages_then_closes_reader_even_without_container(session_module, event_transport, monkeypatch):
    from preview_redaction import SecretRedactor
    from app.services.preview_native_runtime import NATIVE_LABEL

    runtime, states, spawned = event_transport
    chat = uuid.uuid4()
    states[chat.hex] = session_module.STATE
    journal = session_module.Journal('terminal-execution', SecretRedactor(['private-secret']))
    for index in range(120):
        journal.emit('stdout', {'text': f'{index}: private-secret'})
    journal.status('stopped')
    journal.db.close()
    monkeypatch.setattr(runtime, 'exec', lambda *_args: b'')
    container = {'Config': {'Labels': {NATIVE_LABEL: 'terminal-execution'}}}
    runtime.read(chat, 0)
    runtime.before_stop(chat, container)
    assert not runtime.readers and spawned[0].poll() is not None
    retained = runtime.terminal[chat]
    assert len(retained['events']) == 122 and retained['events'][-1]['payload']['status'] == 'stopped'
    assert all('private-secret' not in json.dumps(event) for event in retained['events'])
    runtime.read(chat, 0)
    runtime.before_stop(chat, None)
    assert not runtime.readers and spawned[1].poll() is not None
    assert runtime.terminal[chat] == retained


def test_event_transport_failure_is_closed_actionable_and_reaped(session_module, event_transport):
    from app.services.preview_native_runtime import NATIVE_LABEL

    runtime, states, spawned = event_transport
    chat = uuid.uuid4()
    states[chat.hex] = session_module.STATE
    session_module.STATE.write_text('project-secret invalid database')
    runtime.c.inspect = lambda _chat: {'Config': {'Labels': {NATIVE_LABEL: 'execution-a'}}}
    with pytest.raises(RuntimeError, match='journal is unavailable') as error:
        runtime.events(chat)
    assert 'project-secret' not in str(error.value)
    assert not runtime.readers and spawned[0].poll() is not None
    assert chat not in runtime.last and chat not in runtime.terminal


def test_event_transport_rejects_execution_identity_mismatch(session_module, event_transport):
    from app.services.preview_native_runtime import NATIVE_LABEL
    from preview_redaction import SecretRedactor

    runtime, states, spawned = event_transport
    chat = uuid.uuid4()
    states[chat.hex] = session_module.STATE
    journal = session_module.Journal('different-execution', SecretRedactor())
    journal.db.close()
    runtime.c.inspect = lambda _chat: {'Config': {'Labels': {NATIVE_LABEL: 'owned-execution'}}}
    with pytest.raises(RuntimeError, match='identity changed'):
        runtime.events(chat)
    assert not runtime.readers and spawned[0].poll() is not None
    assert chat not in runtime.last


def test_event_server_bounds_a_hung_runtime_read_without_polling(session_module):
    command = event_server_command(session_module, session_module.STATE, setup=(
        "import time; original=session.signal.setitimer; "
        "session.signal.setitimer=lambda kind,seconds: original(kind,0.1 if seconds else 0); "
        "session.runtime_events=lambda _after: time.sleep(3600)"
    ))
    started = time.monotonic()
    result = subprocess.run(command, input=b'0\n', stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
    assert result.returncode == 0 and not result.stderr
    assert json.loads(result.stdout) == {'after': 0, 'error': 'unavailable'}
    assert time.monotonic() - started < 3

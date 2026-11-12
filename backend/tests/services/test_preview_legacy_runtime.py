import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.preview_legacy_runtime import LegacyRuntime


class Transport:
    def __init__(self):
        self.calls = []
        self.uploads = []
        self.current = None
        self.fail_reads = False
        self.terminal = {}

    def upload(self, chat, files, path, *, uid):
        self.uploads.append((chat, files, path, uid))

    def exec(self, chat, argv, *, user):
        assert user == '65534:65534'
        self.calls.append(argv)
        action = argv[2]
        if action == 'events':
            if self.current is None or self.fail_reads:
                raise RuntimeError('No journal')
            after = int(argv[3])
            return json.dumps({**self.current, 'events': [event for event in self.current['events'] if event['cursor'] > after][:99]}).encode()
        if action == 'start':
            self.current = {'execution_id': argv[3], 'state': 'starting', 'ready': False, 'details': {}, 'cursor': 1, 'events': [{'cursor': 1, 'kind': 'status', 'payload': {'status': 'starting', 'ready': False}}]}
            return json.dumps(self.current).encode()
        if action == 'stop':
            self.current['state'] = 'stopped'
            self.current['ready'] = False
            self.current['cursor'] += 1
            self.current['events'].append({'cursor': self.current['cursor'], 'kind': 'status', 'payload': {'status': 'stopped', 'ready': False}})
            return b''
        raise AssertionError(action)


class Controller:
    def __init__(self):
        self.native = Transport()
        self.container = {'Id': 'legacy-container', 'Config': {'Labels': {}}, 'State': {'Running': True}}
        self.activity_lock = threading.Lock()
        self.activity = {}
        self.stops = []
        self.legacy = LegacyRuntime(self)

    def inspect(self, chat):
        return self.container

    def stop(self, chat):
        self.legacy.before_stop(chat, self.container)
        self.stops.append(chat)
        self.container = None


@pytest.fixture
def runtime():
    controller = Controller()
    return controller.legacy, controller, uuid.uuid4()


def test_concurrent_same_execution_launch_reattaches_once(runtime):
    legacy, controller, chat = runtime
    execution_id = str(uuid.uuid4())
    plan = {'execution_id': execution_id, 'setup': [], 'api': {}}
    controller.native.terminal[chat] = {'execution_id': str(uuid.uuid4()), 'state': 'stopped'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: legacy.launch(chat, plan), range(4)))
    assert all(result['execution_id'] == execution_id for result in results)
    assert all(result['state'] == 'starting' for result in results)
    assert len(controller.native.uploads) == 1
    assert sum(call[2] == 'start' for call in controller.native.calls) == 1
    _, files, path, uid = controller.native.uploads[0]
    assert path == '/tmp' and uid == 65534
    content, mode = files['preview-legacy-plan.json']
    assert mode == 0o600 and json.loads(content)['execution_id'] == execution_id
    assert chat in controller.activity
    assert chat not in controller.native.terminal
    controller.native.terminal[chat] = {'execution_id': execution_id, 'state': 'stopped'}
    legacy.launch(chat, plan)
    assert chat in controller.native.terminal  # Same-ID reattachment changes no ownership.


def test_controller_restart_reattaches_to_sandbox_execution(runtime):
    legacy, controller, chat = runtime
    execution_id = str(uuid.uuid4())
    legacy.launch(chat, {'execution_id': execution_id})
    controller.native.calls.clear()
    restarted = LegacyRuntime(controller)
    current = restarted.launch(chat, {'execution_id': execution_id})
    assert current['execution_id'] == execution_id
    assert len(controller.native.uploads) == 1
    assert [call[2] for call in controller.native.calls] == ['events']
    with pytest.raises(RuntimeError, match='previous preview'):
        restarted.launch(chat, {'execution_id': str(uuid.uuid4())})
    assert len(controller.native.uploads) == 1


def test_status_is_cache_only_and_preserves_legacy_ports(runtime):
    legacy, controller, chat = runtime
    assert legacy.status(chat, controller.container) is None
    legacy.launch(chat, {'execution_id': str(uuid.uuid4())})
    controller.native.current.update(state='running', ready=True, details={'api_port': '8765', 'initial_port': '8765', 'initial_path': '/docs'})
    legacy.events(chat)
    controller.native.calls.clear()
    current = legacy.status(chat, controller.container)
    assert current['state'] == 'running' and current['ready']
    assert current['initial_port'] == current['api_port'] == '8765'
    assert current['initial_path'] == '/docs'
    assert controller.native.calls == []
    controller.container['State']['Running'] = False
    assert legacy.status(chat, controller.container)['state'] == 'interrupted'
    assert controller.native.calls == []


def test_unlaunched_and_native_workloads_are_not_legacy_executions(runtime):
    legacy, controller, chat = runtime
    legacy.before_stop(chat, controller.container)
    assert chat not in legacy.terminal
    controller.container['Config']['Labels']['sdd.preview.native-execution'] = str(uuid.uuid4())
    assert legacy.status(chat, controller.container) is None
    with pytest.raises(FileNotFoundError):
        legacy.launch(chat, {'execution_id': str(uuid.uuid4())})
    with pytest.raises(FileNotFoundError):
        legacy.events(chat)
    calls = len(controller.native.calls)
    legacy.before_stop(chat, controller.container)
    assert len(controller.native.calls) == calls


def test_before_stop_drains_every_page_and_terminal_survives_removal(runtime):
    legacy, controller, chat = runtime
    legacy.launch(chat, {'execution_id': str(uuid.uuid4())})
    source = controller.native.current
    source['events'] = [{'cursor': index, 'kind': 'stdout', 'payload': {'text': f'line {index}'}} for index in range(1, 241)]
    source.update(cursor=240, state='running', ready=True)
    legacy.before_stop(chat, controller.container)
    assert legacy.terminal[chat]['state'] == 'stopped'
    assert len(legacy.terminal[chat]['events']) == 241
    assert legacy.terminal[chat]['events'][-1]['payload']['status'] == 'stopped'
    controller.container = None
    controller.native.calls.clear()
    events, cursor = [], 0
    while True:
        page = legacy.events(chat, cursor)
        if not page['events']:
            break
        events.extend(page['events'])
        cursor = events[-1]['cursor']
        if cursor < page['cursor']:
            assert page['state'] == 'running'
    assert len(events) == 241
    assert legacy.events(chat, cursor)['state'] == 'stopped'
    assert legacy.status(chat, None)['state'] == 'stopped'
    assert controller.native.calls == []


def test_failed_server_journal_retains_exit_and_final_status_after_cleanup(runtime):
    legacy, controller, chat = runtime
    legacy.launch(chat, {'execution_id': str(uuid.uuid4())})
    source = controller.native.current
    source.update(state='failed', ready=False, cursor=3, events=[
        {'cursor': 1, 'kind': 'command_start', 'payload': {'command': 0}},
        {'cursor': 2, 'kind': 'command_exit', 'payload': {'command': 0, 'exit_code': 9}},
        {'cursor': 3, 'kind': 'status', 'payload': {'status': 'failed', 'reason': 'API stopped'}},
    ])
    first = legacy.events(chat)
    assert controller.stops == [chat]
    assert first['state'] == 'failed' and first['execution_id'] == source['execution_id']
    assert [event['kind'] for event in first['events']] == ['command_start', 'command_exit', 'status']
    assert legacy.events(chat, 1)['events'] == first['events'][1:]
    assert legacy.events(chat, 3)['events'] == []


def test_gap_cursors_advance_during_terminal_preservation(runtime):
    legacy, controller, chat = runtime
    legacy.launch(chat, {'execution_id': str(uuid.uuid4())})
    controller.native.current.update(state='failed', cursor=1001, events=[
        {'cursor': 1, 'kind': 'gap', 'payload': {'through_cursor': 999}},
        {'cursor': 1000, 'kind': 'command_exit', 'payload': {'exit_code': 3}},
        {'cursor': 1001, 'kind': 'status', 'payload': {'status': 'failed'}},
    ])
    page = legacy.events(chat)
    assert len(page['events']) == 3
    assert page['events'][0]['payload']['through_cursor'] == 999
    assert legacy.events(chat, 999)['events'][0]['kind'] == 'command_exit'


def test_missing_cached_journal_becomes_interrupted_on_cleanup(runtime):
    legacy, controller, chat = runtime
    execution_id = str(uuid.uuid4())
    legacy.launch(chat, {'execution_id': execution_id})
    controller.native.fail_reads = True
    legacy.before_stop(chat, controller.container)
    controller.container = None
    assert legacy.events(chat)['state'] == 'interrupted'
    assert legacy.events(chat)['execution_id'] == execution_id

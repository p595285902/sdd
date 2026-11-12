"""Trusted supervisor inside one private rootless Docker sandbox.

No platform Docker socket/configuration is available here. Journal contents are
redacted before SQLite writes. Browser forwarding is not performed by projects.
"""
from __future__ import annotations

import codecs
import fcntl
import json
import os
import re
import selectors
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from preview_native_plan import PreviewInstructionsError, compose_action, config_command
from preview_redaction import SecretRedactor, command_secrets

ROOT = Path('/workspace')
STATE = Path('/run/user/1000/preview.sqlite')
OUTPUT_BYTES = 262144
OUTPUT_EVENTS = 1024
SECRET_KEY = re.compile(r'password|passwd|secret|token|api[_-]?key|private[_-]?key|credential', re.I)
ENV = {
    'HOME': '/home/rootless', 'PATH': '/usr/local/bin:/usr/bin:/bin',
    'DOCKER_HOST': 'unix:///run/user/1000/docker.sock',
    'HTTP_PROXY': 'http://127.0.0.1:3128', 'HTTPS_PROXY': 'http://127.0.0.1:3128',
    'NO_PROXY': 'localhost,127.0.0.1', 'COMPOSE_ANSI': 'never',
}


def local_path(value: str, *, base: Path | None = None, must_exist: bool = True) -> Path:
    path = ((base or ROOT) / value).resolve(strict=must_exist)
    if not path.is_relative_to(ROOT) or any(part in ('.git', '.claude') for part in path.relative_to(ROOT).parts):
        raise PreviewInstructionsError('Project input must remain inside the selected checkout')
    return path


def known_secrets(plan: dict) -> list[str]:
    values = []
    budget = 0
    explicit = set()
    for command in plan['commands']:
        values.extend(command_secrets(command))
        argv = command['argv']
        for index, value in enumerate(argv):
            target = None
            if value == '--env-file' and index + 1 < len(argv):
                target = argv[index + 1]
            elif value.startswith('--env-file='):
                target = value.split('=', 1)[1]
            if target:
                explicit.add(local_path(target, base=ROOT / command.get('cwd', '.'), must_exist=False))
    # These are project inputs, never sent to the instruction resolver.
    paths = sorted(set(ROOT.rglob('*')) | explicit)
    if len(paths) > 10000:
        raise PreviewInstructionsError('Project inputs exceed the file limit')
    for path in paths:
        if path.is_symlink() or not path.is_file() or not (path in explicit or path.name == '.env' or path.name.startswith('.env.') or path.suffix == '.env'):
            continue
        local_path(str(path))
        if path.stat().st_size > 65536:
            raise PreviewInstructionsError('Project environment file exceeds the secret-processing limit')
        budget += path.stat().st_size
        if budget > 262144:
            raise PreviewInstructionsError('Project environment files exceed the secret-processing budget')
        for line in path.read_text().splitlines():
            match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*?)\s*$', line)
            if match and SECRET_KEY.search(match[1]):
                value = match[2].strip('\"\'')
                if value:
                    values.append(value)
    return values


def prepare_sync(stage: Path):
    # Initial synchronization precedes any supervisor/project process. Every
    # later update requires an acknowledgement from the existing supervisor.
    if not STATE.exists() and not STATE.with_suffix('.owner.json').exists():
        return
    data = (stage / 'secrets.json').read_bytes()
    if len(data) > 524288:
        raise PreviewInstructionsError('Project secrets exceed the synchronization budget')
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(5)
        connection.connect(str(STATE.with_suffix('.control.sock')))
        connection.sendall(data + b'\n')
        with connection.makefile('rb') as response:
            if response.readline(64) != b'OK\n':
                raise PreviewInstructionsError('The running preview could not safely accept changed project credentials')


class Journal:
    def __init__(self, execution_id: str, redactor: SecretRedactor):
        self.redactor = redactor
        self.lock = threading.RLock()
        self.final = False
        self.exited = set()
        self.db = sqlite3.connect(STATE, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=TRUNCATE')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS events(cursor INTEGER PRIMARY KEY, kind TEXT, payload TEXT, bytes INTEGER);
          CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1), body TEXT);
        ''')
        saved = self.db.execute('SELECT body FROM state WHERE id=1').fetchone()
        if saved:
            self.state = json.loads(saved[0])
            if self.state['execution_id'] != execution_id:
                self.db.close()
                raise PreviewInstructionsError('Stop the previous preview before starting a new execution')
        else:
            self.state = {'execution_id': execution_id, 'state': 'starting', 'ready': False, 'details': {}, 'cursor': 0, 'dropped_bytes': 0}
            self.emit('status', {'status': 'starting', 'ready': False})

    def emit(self, kind: str, payload: dict):
        with self.lock:
            if self.final or (kind == 'command_exit' and payload['command'] in self.exited):
                return
            payload = self.redactor.redact_json(payload)
            self.state['cursor'] += 1
            size = len(payload.get('text', '').encode()) if kind in ('stdout', 'stderr') else 0
            self.db.execute('INSERT INTO events VALUES(?,?,?,?)', (self.state['cursor'], kind, json.dumps(payload), size))
            if kind == 'status':
                self.state['state'] = payload['status']
                self.state['ready'] = payload.get('ready', False)
            if 'details' in payload:
                self.state['details'] = payload['details']
            count, total = self.db.execute("SELECT count(*),coalesce(sum(bytes),0) FROM events WHERE kind IN ('stdout','stderr')").fetchone()
            while count > OUTPUT_EVENTS or total > OUTPUT_BYTES:
                row = self.db.execute("SELECT cursor,bytes FROM events WHERE kind IN ('stdout','stderr') ORDER BY cursor LIMIT 1").fetchone()
                self.db.execute('DELETE FROM events WHERE cursor=?', (row[0],))
                self.state['dropped_bytes'] += row[1]
                count -= 1
                total -= row[1]
            self.db.execute('INSERT OR REPLACE INTO state VALUES(1,?)', (json.dumps(self.state),))
            self.db.commit()
            if kind == 'command_exit':
                self.exited.add(payload['command'])
            if kind == 'status' and payload['status'] in ('failed', 'stopped', 'interrupted'):
                self.final = True

    def status(self, status: str, *, ready: bool = False, reason: str = '', details: dict | None = None):
        self.emit('status', {'status': status, 'ready': ready, 'reason': reason, **({'details': details} if details is not None else {})})


def read_events(after: int) -> dict:
    db = sqlite3.connect(f'file:{STATE}?mode=ro', uri=True)
    try:
        db.execute('BEGIN')
        state = json.loads(db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
        rows = db.execute('SELECT cursor,kind,payload FROM events WHERE cursor>? ORDER BY cursor LIMIT 99', (after,)).fetchall()
        events = []
        expected = after + 1
        for cursor, kind, body in rows:
            if cursor > expected:
                events.append({'cursor': expected, 'kind': 'gap', 'payload': {'through_cursor': cursor - 1, 'total_dropped_bytes': state['dropped_bytes']}})
            events.append({'cursor': cursor, 'kind': kind, 'payload': json.loads(body)})
            expected = cursor + 1
            if len(events) >= 98:
                break
        if not rows and after < state['cursor']:
            events.append({'cursor': after + 1, 'kind': 'gap', 'payload': {'through_cursor': state['cursor'], 'total_dropped_bytes': state['dropped_bytes']}})
        return {**state, 'events': events}
    finally:
        db.close()


def validate_command(command: dict) -> tuple[Path, list[str], dict]:
    cwd = local_path(command['cwd'])
    if not cwd.is_dir():
        raise PreviewInstructionsError('Documented command directory is not available')
    argv = command['argv']
    if not isinstance(argv, list) or not argv or len(argv) > 128 or any(not isinstance(value, str) or '\x00' in value or len(value) > 2048 for value in argv):
        raise PreviewInstructionsError('Invalid documented startup command')
    action = compose_action(argv)
    if not action:
        if argv[0] not in ('cp', 'mkdir'):
            raise PreviewInstructionsError('Document initialization scripts as a Compose run command so they execute in the configured project service')
        allowed = {'-r', '-R', '--recursive', '-f', '--force', '-n', '--no-clobber', '--'} if argv[0] == 'cp' else {'-p', '--parents', '--'}
        paths = []
        for value in argv[1:]:
            if value.startswith('-'):
                if value not in allowed:
                    raise PreviewInstructionsError('Unsupported checkout-local file preparation option')
            else:
                paths.append(local_path(value, base=cwd, must_exist=False))
        if len(paths) < (2 if argv[0] == 'cp' else 1):
            raise PreviewInstructionsError('Document explicit checkout-local preparation paths')
    elif action[1] not in ('run', 'build', 'pull', 'up', 'watch'):
        raise PreviewInstructionsError('Unsupported native startup action')
    if action:
        globals = argv[:action[0]]
        for index, value in enumerate(globals):
            if value in ('-f', '--file', '--env-file', '--project-directory'):
                if index + 1 >= len(globals):
                    raise PreviewInstructionsError('Missing checkout-local Compose configuration path')
                local_path(globals[index + 1], base=cwd, must_exist=False)
            elif value.startswith(('--file=', '--env-file=', '--project-directory=')):
                local_path(value.split('=', 1)[1], base=cwd, must_exist=False)
            elif value.startswith('-f') and value != '-f':
                local_path(value[2:], base=cwd, must_exist=False)
    # Run flags can add host access beyond the resolved service configuration.
    forbidden = ('--privileged', '--volume', '-v', '--mount', '--device', '--network', '--pid', '--ipc', '--cap-add', '--security-opt', '--use-aliases')
    if action and any(value == flag or value.startswith(flag + '=') or (flag == '-v' and value.startswith('-v')) for value in argv[action[0] + 1:] for flag in forbidden):
        raise PreviewInstructionsError('Documented commands must not request additional mounts, privileges or host namespaces')
    command_env = command.get('env', {})
    if not isinstance(command_env, dict) or any(key.startswith('DOCKER_') or key in ('HOME', 'PATH', 'LD_PRELOAD', 'LD_LIBRARY_PATH', 'COMPOSE_FILE', 'COMPOSE_ENV_FILES') for key in command_env):
        raise PreviewInstructionsError('Project startup must not override private runtime control settings')
    return cwd, argv, {**ENV, **command_env}


def native_model(command: dict) -> dict:
    cwd, _, env = validate_command(command)
    process = subprocess.Popen(config_command(command), cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, _ = process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise PreviewInstructionsError('Native Compose configuration resolution timed out') from None
    if process.returncode or len(out) > 2 * 1024 * 1024:
        raise PreviewInstructionsError('Native Compose configuration is invalid or incomplete; check documented files, interpolation and required dependencies')
    model = json.loads(out)
    validate_model(model)
    return model


def validate_model(model: dict):
    services = model.get('services', {})
    if not services or len(services) > 32:
        raise PreviewInstructionsError('Native Compose service model is empty or exceeds the service limit')
    for key in ('volumes', 'networks', 'configs', 'secrets'):
        for item in (model.get(key) or {}).values():
            if item.get('external') or item.get('driver_opts') or item.get('driver') not in (None, '', 'local', 'bridge'):
                raise PreviewInstructionsError('Project configuration requests an external or host-backed resource')
            if item.get('file'):
                local_path(item['file'])
    for name, service in services.items():
        if any(service.get(key) for key in ('privileged', 'devices', 'device_cgroup_rules', 'cap_add', 'security_opt', 'use_api_socket', 'volumes_from', 'external_links', 'sysctls', 'credential_spec', 'cgroup_parent', 'gpus', 'runtime')):
            raise PreviewInstructionsError(f'Service {name} requests unsupported host access or privileges')
        if any(service.get(key) in ('host', 'host-gateway') or str(service.get(key, '')).startswith('container:') for key in ('network_mode', 'pid', 'ipc', 'uts', 'cgroup')) or service.get('extra_hosts'):
            raise PreviewInstructionsError(f'Service {name} requests a host namespace or host route')
        for mount in service.get('volumes', []):
            if mount.get('type') == 'bind':
                path = local_path(mount['source'])
                if path.name in ('docker.sock', 'containerd.sock') or path.is_socket():
                    raise PreviewInstructionsError('Project mounts must not expose control sockets')
            elif mount.get('type') not in ('volume', 'tmpfs'):
                raise PreviewInstructionsError('Unsupported project mount type')
        build = service.get('build')
        if build:
            if build.get('privileged') or build.get('entitlements') or build.get('ssh') or build.get('network') == 'host':
                raise PreviewInstructionsError(f'Service {name} requests privileged build access')
            context = local_path(build.get('context', '.'))
            if build.get('dockerfile'):
                local_path(build['dockerfile'], base=context)
            for context_value in (build.get('additional_contexts') or {}).values():
                if not str(context_value).startswith('service:'):
                    local_path(context_value)
        for watch in (service.get('develop') or {}).get('watch', []):
            local_path(watch['path'])
        for dependency in service.get('depends_on', {}):
            if dependency not in services:
                raise PreviewInstructionsError(f'Service {name} requires an unavailable dependency')


def application_routes(model: dict, application: dict) -> dict[str, dict]:
    services = model['services']
    candidates = []
    for name, service in services.items():
        for item in service.get('ports', []):
            if str(item.get('published')) == str(application.get('port')):
                candidates.append((name, int(item['target']), str(item['published'])))
        if not service.get('ports'):
            for value in service.get('expose', []):
                target = str(value).split('/')[0]
                if target == str(application.get('port')):
                    candidates.append((name, int(target), target))
        if name == application.get('service'):
            ports = service.get('ports') or [{'target': value} for value in service.get('expose', [])]
            if len(ports) == 1:
                item = ports[0]
                candidates.append((name, int(item['target']), str(item.get('published', item['target']))))
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) != 1:
        raise PreviewInstructionsError('The documented main application must identify one resolved service and port')
    name, target, public = candidates[0]
    if re.search(r'mailpit|adminer|postgres|mysql|redis|(^|[-_\s/])(mail|admin|database|db)([-_\s/:]|$)', name + ' ' + str(services[name].get('image', '')), re.I):
        raise PreviewInstructionsError('An auxiliary tool cannot be the main application preview')
    routes = {public: {'service': name, 'target': target, 'role': 'website'}}
    # API traffic is registered only for actual transitive application dependencies.
    dependencies = set()
    pending = list(services[name].get('depends_on', {}))
    while pending:
        dependency = pending.pop()
        if dependency not in dependencies:
            dependencies.add(dependency)
            pending.extend(services[dependency].get('depends_on', {}))
    for dependency in sorted(dependencies):
        if dependency not in ('api', 'backend'):
            continue
        service = services[dependency]
        ports = service.get('ports') or [{'target': value} for value in service.get('expose', [])]
        if len(ports) == 1:
            item = ports[0]
            routes[str(item.get('published', item['target']))] = {'service': dependency, 'target': int(item['target']), 'role': 'api'}
    return routes


class Supervisor:
    def __init__(self, plan: dict, execution_id: str):
        self.plan = plan
        self.journal = Journal(execution_id, SecretRedactor(known_secrets(plan)))
        self.cancel = threading.Event()
        self.process: subprocess.Popen | None = None
        self.processes = []
        self.finished_setup = set()
        self.readers = []
        self.lock = threading.Lock()
        self.control_socket = None
        self.control_thread = None

    def start_control(self):
        self.control_socket = socket.socket(socket.AF_UNIX)
        path = STATE.with_suffix('.control.sock')
        self.control_socket.bind(str(path))
        path.chmod(0o600)
        self.control_socket.listen(4)
        self.control_socket.settimeout(0.2)
        self.control_thread = threading.Thread(target=self.control_loop, daemon=True)
        self.control_thread.start()

    def control_loop(self):
        while not self.cancel.is_set():
            try:
                connection, _ = self.control_socket.accept()
            except TimeoutError:
                continue
            with connection:
                connection.settimeout(2)
                try:
                    with connection.makefile('rb') as request:
                        data = request.readline(524289)
                    if len(data) > 524288 or not data.endswith(b'\n'):
                        raise ValueError('Invalid secret update')
                    values = json.loads(data)
                    if not isinstance(values, list):
                        raise ValueError('Invalid secret update')
                    with self.journal.lock:
                        self.journal.redactor.update_secrets(values)
                    connection.sendall(b'OK\n')
                except (OSError, ValueError, TypeError):
                    try:
                        connection.sendall(b'DENIED\n')
                    except OSError:
                        pass

    def cancel_signal(self, *_):
        self.cancel.set()

    def cleanup(self):
        # A terminal journal is permission for the controller to remove the
        # sandbox. Terminate/drain children before publishing that permission.
        for sig, timeout in ((signal.SIGTERM, 2), (signal.SIGKILL, 1)):
            for _, process in self.processes:
                if process.pid not in self.finished_setup:
                    try:
                        os.killpg(process.pid, sig)
                    except ProcessLookupError:
                        pass
            deadline = time.monotonic() + timeout
            for _, process in self.processes:
                try:
                    process.wait(max(0.01, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    pass
        for reader in self.readers:
            reader.join(3)
        for index, process in self.processes:
            if process.returncode is not None:
                self.journal.emit('command_exit', {'command': index, 'exit_code': process.returncode})
        if self.control_thread:
            self.control_thread.join(3)
        if self.control_socket:
            self.control_socket.close()

    def run(self, command: dict, index: int, *, startup: bool = False) -> subprocess.Popen:
        cwd, argv, env = validate_command(command)
        self.journal.emit('command_start', {'command': index, 'argv': argv, 'cwd': command['cwd'], 'source': command.get('source', {})})
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        with self.lock:
            self.process = process
            self.processes.append((index, process))
        reader = threading.Thread(target=self.capture, args=(process, index), daemon=True)
        reader.start()
        self.readers.append(reader)
        if not startup:
            deadline = time.monotonic() + 180
            while process.poll() is None:
                if self.cancel.wait(0.1):
                    raise InterruptedError('Preview was stopped during documented setup')
                if time.monotonic() > deadline:
                    raise PreviewInstructionsError('Documented setup exceeded its time limit')
            # Retire any descendants while this process group is still ours;
            # never signal a completed setup PID after hours of watch activity.
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    pass
                reader.join(0.5)
            self.finished_setup.add(process.pid)
            if process.returncode:
                raise PreviewInstructionsError(f'Documented setup command {index + 1} failed with exit code {process.returncode}; startup was not executed')
        return process

    def capture(self, process: subprocess.Popen, index: int):
        selector = selectors.DefaultSelector()
        decoders = {}
        for stream, pipe in (('stdout', process.stdout), ('stderr', process.stderr)):
            selector.register(pipe, selectors.EVENT_READ, stream)
            decoders[stream] = codecs.getincrementaldecoder('utf-8')(errors='replace')
        try:
            while selector.get_map():
                for key, _ in selector.select(0.2):
                    stream = key.data
                    data = os.read(key.fileobj.fileno(), 4096)
                    if data:
                        with self.journal.lock:
                            text = self.journal.redactor.feed(f'{index}:{stream}', decoders[stream].decode(data))
                            if text:
                                self.journal.emit(stream, {'command': index, 'stream': stream, 'text': text})
                    else:
                        with self.journal.lock:
                            tail = self.journal.redactor.feed(f'{index}:{stream}', decoders[stream].decode(b'', final=True))
                            tail += self.journal.redactor.finish(f'{index}:{stream}')
                            if tail:
                                self.journal.emit(stream, {'command': index, 'stream': stream, 'text': tail})
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
            process.wait()
            self.journal.emit('command_exit', {'command': index, 'exit_code': process.returncode})
        finally:
            selector.close()

    def inspect_routes(self, command: dict, routes: dict) -> dict | None:
        cwd, argv, env = validate_command(command)
        action = compose_action(argv)
        result = subprocess.run([*argv[:action[0]], 'ps', '--format', 'json'], cwd=cwd, env=env, capture_output=True, timeout=5)
        if result.returncode or len(result.stdout) > 262144:
            return None
        rows = []
        for line in result.stdout.splitlines():
            if line:
                item = json.loads(line)
                rows.extend(item if isinstance(item, list) else [item])
        by_service = {row['Service']: row for row in rows if row.get('State') == 'running'}
        resolved = {}
        for port, route in routes.items():
            row = by_service.get(route['service'])
            if not row:
                return None
            resolved[port] = {**route, 'container': row['ID']}
        return resolved

    def ready(self, routes: dict, application: dict) -> bool:
        # Health must come from the selected application, not an auxiliary port.
        main = next(route for route in routes.values() if route['role'] == 'website')
        script = "import sys,urllib.request; urllib.request.build_opener(urllib.request.ProxyHandler({})).open(sys.argv[1],timeout=2).read(1024)"
        result = subprocess.run(['docker', 'run', '--rm', '--pull=never', '--network', 'container:' + main['container'], '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=32', os.environ['PREVIEW_HELPER_IMAGE'], 'python', '-c', script, f"http://127.0.0.1:{main['target']}{application.get('path', '/') }"], env=ENV, capture_output=True, timeout=8)
        return result.returncode == 0

    def add_model_secrets(self, model):
        config_path = Path('/home/rootless/.docker/config.json')
        proxy_config = json.loads(config_path.read_text())
        proxy_config['proxies']['default']['noProxy'] = ','.join(['localhost', '127.0.0.1', *model['services']])
        config_path.write_text(json.dumps(proxy_config))
        with self.journal.lock:
            self.journal.redactor.update_secrets([
                str(value) for service in model['services'].values()
                for key, value in (service.get('environment') or {}).items()
                if value and SECRET_KEY.search(key)
            ])

    def execute(self):
        status, reason = 'failed', 'Native preview startup failed'
        try:
            self.start_control()
            # File preparation may create the documented .env. Resolve and
            # validate each native model before its first executable action;
            # never start services from a partially validated Compose model.
            for command in self.plan['commands']:
                validate_command(command)
            for index, command in enumerate(self.plan['commands'][:-1]):
                if compose_action(command['argv']):
                    model = native_model(command)
                    self.add_model_secrets(model)
                self.run(command, index)
            command = self.plan['commands'][-1]
            model = native_model(command)
            self.add_model_secrets(model)
            routes = application_routes(model, self.plan['application'])
            process = self.run(command, len(self.plan['commands']) - 1, startup=True)
            action = compose_action(command['argv'])[1]
            detached = action == 'up' and any(flag in command['argv'] for flag in ('-d', '--detach'))
            deadline = time.monotonic() + 180
            ready = False
            published = None
            while not self.cancel.wait(0.5):
                exit_code = process.poll()
                if exit_code is not None and (not detached or exit_code):
                    raise PreviewInstructionsError(f'Documented startup command exited with code {exit_code}')
                try:
                    resolved = self.inspect_routes(command, routes)
                except subprocess.TimeoutExpired:
                    resolved = None
                if ready and resolved == published:
                    continue
                if ready:
                    # Native watch can remove/recreate a service. Withdraw stale
                    # destinations during the bounded transition, not the sandbox.
                    ready = False
                    deadline = time.monotonic() + 180
                    self.journal.status('running', ready=False, reason='The application is restarting under native Compose.')
                responsive = False
                if resolved:
                    try:
                        responsive = self.ready(resolved, self.plan['application'])
                    except subprocess.TimeoutExpired:
                        # One bounded observation can time out under the outer
                        # CPU budget. Keep the existing application deadline;
                        # a slow probe is not a fatal project-command failure.
                        pass
                if responsive:
                    website = next(port for port, route in resolved.items() if route['role'] == 'website')
                    details = {'initial_port': website, 'initial_path': self.plan['application'].get('path', '/'), 'website_port': website, 'routes': resolved}
                    api = next((port for port, route in resolved.items() if route['role'] == 'api'), None)
                    if api:
                        details['api_port'] = api
                    self.journal.status('running', ready=True, details=details)
                    ready, published = True, resolved
                elif time.monotonic() > deadline:
                    raise PreviewInstructionsError('The documented application did not become ready; auxiliary service responses do not establish readiness')
            status, reason = 'stopped', 'Preview sandbox was stopped'
        except InterruptedError:
            status, reason = 'stopped', 'Preview sandbox was stopped'
        except Exception as error:
            # Never log native stderr, configuration or exception contents outside
            # the redactor. Project diagnostics are operation text, not instructions.
            reason = str(error)
        finally:
            self.cancel_signal()
            self.cleanup()
            self.journal.status(status, reason=reason)


def supervisor_alive(pid: int) -> bool:
    try:
        state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
        if state == 'Z':
            return False
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, IndexError):
        return False


def runtime_events(after: int) -> dict:
    with STATE.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        owner_path = STATE.with_suffix('.owner.json')
        owner = json.loads(owner_path.read_text()) if owner_path.exists() else None
        if not STATE.exists():
            if owner is None:
                raise FileNotFoundError('Native preview execution is missing')
            if supervisor_alive(owner['pid']):
                return {'execution_id': owner['execution_id'], 'state': 'starting', 'ready': False, 'details': {}, 'cursor': 0, 'events': []}
            journal = Journal(owner['execution_id'], SecretRedactor())
            journal.status('interrupted', reason='Native preview supervisor stopped before creating its journal')
            journal.db.close()
        current = read_events(after)
        if owner and current['state'] not in ('failed', 'stopped', 'interrupted') and not supervisor_alive(owner['pid']):
            journal = Journal(current['execution_id'], SecretRedactor())
            journal.status('interrupted', reason='Native preview supervisor stopped unexpectedly')
            journal.db.close()
            current = read_events(after)
        return current


def start(execution_id: str) -> dict:
    with STATE.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if STATE.exists():
            current = read_events(0)
            if current['execution_id'] != execution_id:
                raise PreviewInstructionsError('Stop the previous preview before starting a new execution')
            return current
        owner_path = STATE.with_suffix('.owner.json')
        if owner_path.exists():
            owner = json.loads(owner_path.read_text())
            if owner['execution_id'] != execution_id:
                raise PreviewInstructionsError('Stop the previous preview before starting a new execution')
            if not supervisor_alive(owner['pid']):
                journal = Journal(execution_id, SecretRedactor())
                journal.status('interrupted', reason='Native preview supervisor stopped before creating its journal')
                journal.db.close()
                return read_events(0)
        else:
            process = subprocess.Popen([sys.executable, __file__, 'supervise', execution_id],
                                       env={**ENV, 'PREVIEW_HELPER_IMAGE': os.environ['PREVIEW_HELPER_IMAGE']},
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            owner_path.write_text(json.dumps({'execution_id': execution_id, 'pid': process.pid}))
            STATE.with_name('preview-supervisor.pid').write_text(str(process.pid))
        return {'execution_id': execution_id, 'state': 'starting', 'ready': False, 'details': {}, 'cursor': 0, 'events': []}


if __name__ == '__main__':
    if sys.argv[1] == 'prepare-sync':
        prepare_sync(Path(sys.argv[2]))
    elif sys.argv[1] == 'events':
        sys.stdout.write(json.dumps(runtime_events(int(sys.argv[2]))) + '\n')
    elif sys.argv[1] == 'start':
        sys.stdout.write(json.dumps(start(sys.argv[2])) + '\n')
    else:
        with STATE.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                plan = json.loads(Path('/run/user/1000/preview-plan.json').read_text())
                supervisor = Supervisor(plan, sys.argv[2])
            except Exception:
                journal = Journal(sys.argv[2], SecretRedactor())
                journal.status('failed', reason='Native preview supervisor could not load its bounded project configuration')
                journal.db.close()
                raise SystemExit(1) from None
        signal.signal(signal.SIGTERM, supervisor.cancel_signal)
        signal.signal(signal.SIGINT, supervisor.cancel_signal)
        supervisor.execute()

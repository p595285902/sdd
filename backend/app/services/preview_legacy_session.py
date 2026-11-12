"""Trusted non-Compose supervisor; project output never leaves its redacted journal."""
from __future__ import annotations

import fcntl
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib import request

import preview_native_session as journal_api
from preview_redaction import SecretRedactor

ROOT = Path('/workspace')
journal_api.STATE = Path('/tmp/preview.sqlite')
PLAN = Path('/tmp/preview-legacy-plan.json')
OWNER = Path('/tmp/preview-legacy-owner.json')
LOCK = Path('/tmp/preview-legacy.lock')
TERMINAL = ('failed', 'stopped', 'interrupted')
# Deliberately do not inherit platform environment or native Docker settings.
ENV = {
    'HOME': '/tmp', 'PATH': '/usr/local/bin:/usr/bin:/bin',
    'HTTP_PROXY': 'http://127.0.0.1:3128', 'HTTPS_PROXY': 'http://127.0.0.1:3128',
    'NO_PROXY': 'localhost,127.0.0.1', 'npm_config_cache': '/tmp/npm',
    'UV_CACHE_DIR': '/tmp/uv', 'PYTHONUNBUFFERED': '1',
}


class LockedRedactor(SecretRedactor):
    """Independent pipe readers share known values, but never mutate buffers together."""

    def __init__(self, values=()):
        super().__init__(values, max_streams=32)
        self.lock = threading.RLock()

    def feed(self, stream, text):
        with self.lock:
            return super().feed(stream, text)

    def finish(self, stream):
        with self.lock:
            return super().finish(stream)

    def redact_json(self, value):
        with self.lock:
            return super().redact_json(value)


class Journal(journal_api.Journal):
    """Reuse bounded native storage/capture, preserving one final status on cleanup."""

    def __init__(self, execution_id, redactor):
        self.final = False
        self.exited = set()
        self.reattached = journal_api.STATE.exists()
        if self.reattached:
            self.redactor = redactor
            self.lock = threading.RLock()
            self.db = sqlite3.connect(journal_api.STATE, check_same_thread=False)
            self.state = json.loads(self.db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
            if self.state['execution_id'] != execution_id:
                self.db.close()
                raise RuntimeError('Stop the previous preview before starting a new execution')
            self.final = self.state['state'] in TERMINAL
        else:
            super().__init__(execution_id, redactor)

    def emit(self, kind, payload):
        # capture() can finish after bounded cleanup. No output may follow final
        # status, and a forced cleanup must not duplicate a reader's exit record.
        with self.lock:
            if self.final or (kind == 'command_exit' and payload['command'] in self.exited):
                return
            super().emit(kind, payload)
            if kind == 'command_exit':
                self.exited.add(payload['command'])
            if kind == 'status' and payload['status'] in TERMINAL:
                self.final = True


def validate_command(command):
    directory = Path(command['cwd'])
    if directory.is_absolute() or '..' in directory.parts:
        raise ValueError('Unsupported preview working directory')
    cwd = (ROOT / directory).resolve(strict=True)
    if not cwd.is_relative_to(ROOT) or not cwd.is_dir():
        raise ValueError('Unsupported preview working directory')
    argv = command['argv']
    if not isinstance(argv, list) or not 1 <= len(argv) <= 24 or any(
        not isinstance(item, str) or not item or '\x00' in item or len(item) > 240 for item in argv
    ):
        raise ValueError('Unsupported preview command')
    if Path(argv[0]).name in ('docker', 'docker-compose') or command.get('env'):
        raise ValueError('Legacy preview commands cannot override runtime controls')
    return cwd, argv


def validate_server(server):
    validate_command(server)
    port = server['port']
    path = server['path']
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError('Unsupported preview port')
    if not isinstance(path, str) or not path.startswith('/') or '//' in path or len(path) > 240:
        raise ValueError('Unsupported preview health path')


class Supervisor:
    capture = journal_api.Supervisor.capture

    def __init__(self, plan, execution_id, *, setup_timeout=60, startup_timeout=12):
        self.plan = plan
        self.setup_timeout, self.startup_timeout = setup_timeout, startup_timeout
        self.cancel = threading.Event()
        self.processes = []
        self.finished_setup = set()
        self.readers = []
        self.secret_error = False
        try:
            commands = [*plan.get('setup', []), *[plan[role] for role in ('api', 'website') if plan.get(role)]]
            journal_api.ROOT = ROOT
            redactor = LockedRedactor(journal_api.known_secrets({'commands': commands}))
        except Exception:
            # Fail closed before any project command; never put the error/value
            # from an unreadable secret source into an unconfigured redactor.
            redactor = LockedRedactor()
            self.secret_error = True
        self.journal = Journal(execution_id, redactor)

    def cancel_signal(self, *_):
        self.cancel.set()

    def run(self, command, index, *, setup=False):
        if self.cancel.is_set():
            raise InterruptedError('Preview was stopped')
        cwd, argv = validate_command(command)
        self.journal.emit('command_start', {'command': index, 'argv': argv, 'cwd': command['cwd'], 'source': command.get('source', {})})
        process = subprocess.Popen(argv, cwd=cwd, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        self.processes.append((index, process))
        reader = threading.Thread(target=self.capture, args=(process, index), daemon=True)
        self.readers.append(reader)
        reader.start()
        if setup:
            deadline = time.monotonic() + self.setup_timeout
            while process.poll() is None:
                if self.cancel.wait(0.05):
                    raise InterruptedError('Preview was stopped during setup')
                if time.monotonic() >= deadline:
                    raise RuntimeError(f'Preview setup command {index + 1} timed out; startup was not executed')
            # Retire completed setup groups now, not hours later when their
            # numeric process IDs could have been reused by unrelated processes.
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    pass
                reader.join(0.5)
            self.finished_setup.add(process.pid)
            if process.returncode:
                raise RuntimeError(f'Preview setup command {index + 1} failed with exit code {process.returncode}; startup was not executed')
        return process

    def healthy(self, server):
        try:
            opener = request.build_opener(request.ProxyHandler({}))
            with opener.open(f"http://127.0.0.1:{server['port']}{server['path']}", timeout=0.5) as response:
                response.read(1024)
            return True
        except (OSError, ValueError):
            return False

    def cleanup(self):
        # Signal whole process groups even if a package-manager parent already
        # exited: its server children still own the inherited pipes and ports.
        for sig, timeout in ((signal.SIGTERM, 2), (signal.SIGKILL, 1)):
            for _, process in self.processes:
                if process.pid in self.finished_setup:
                    continue
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

    def execute(self):
        if self.journal.reattached:
            return
        status, reason = 'failed', 'Preview startup failed'
        try:
            if self.secret_error:
                raise RuntimeError('Project secret configuration could not be loaded safely')
            setup = self.plan['setup']
            if not isinstance(setup, list) or len(setup) > 8:
                raise ValueError('Unsupported preview setup')
            roles = [role for role in ('api', 'website') if self.plan.get(role)]
            if 'api' not in roles:
                raise ValueError('A documented API server is required')
            for command in setup:
                validate_command(command)
            for role in roles:
                validate_server(self.plan[role])
            if len({self.plan[role]['port'] for role in roles}) != len(roles):
                raise ValueError('Website and API require distinct ports')
            for index, command in enumerate(setup):
                self.run(command, index, setup=True)
            servers = [self.run(self.plan[role], len(setup) + index) for index, role in enumerate(roles)]
            deadline = time.monotonic() + self.startup_timeout
            ready = False
            while not self.cancel.wait(0.05):
                for index, process in enumerate(servers):
                    if process.poll() is not None:
                        raise RuntimeError(f'Preview {roles[index]} startup command exited with code {process.returncode}')
                if not ready:
                    if all(self.healthy(self.plan[role]) for role in roles):
                        selected = self.plan.get('website') or self.plan['api']
                        details = {
                            'initial_port': str(selected['port']),
                            'initial_path': self.plan.get('initial_path', selected['path']),
                            'api_port': str(self.plan['api']['port']),
                        }
                        if self.plan.get('website'):
                            details['website_port'] = str(self.plan['website']['port'])
                        self.journal.status('running', ready=True, details=details)
                        ready = True
                    elif time.monotonic() >= deadline:
                        raise RuntimeError('Preview startup timed out waiting for the documented application')
            status, reason = 'stopped', 'Preview workload was stopped'
        except InterruptedError:
            status, reason = 'stopped', 'Preview workload was stopped'
        except Exception as error:
            reason = str(error)
        finally:
            self.cleanup()
            self.journal.status(status, reason=reason)


def alive(pid):
    try:
        os.kill(pid, 0)
        status = Path(f'/proc/{pid}/stat')
        # Orphaned children may remain zombies under a non-reaping container PID 1.
        return not status.exists() or status.read_text().rsplit(') ', 1)[1].split()[0] != 'Z'
    except ProcessLookupError:
        return False


def read_events(after):
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        owner = json.loads(OWNER.read_text()) if OWNER.exists() else None
        if not journal_api.STATE.exists():
            if owner is None:
                raise FileNotFoundError('Legacy preview execution is missing')
            if alive(owner['pid']):
                return {'execution_id': owner['execution_id'], 'state': 'starting', 'ready': False, 'details': {}, 'cursor': 0, 'events': []}
            journal = Journal(owner['execution_id'], LockedRedactor())
            journal.status('interrupted', reason='Preview supervisor stopped before creating its journal')
            journal.db.close()
        current = journal_api.read_events(after)
        if owner and current['state'] not in TERMINAL and not alive(owner['pid']):
            journal = Journal(current['execution_id'], LockedRedactor())
            journal.status('interrupted', reason='Preview supervisor stopped unexpectedly')
            journal.db.close()
            current = journal_api.read_events(after)
        return current


def start(execution_id):
    """Atomic claim survives controller retries before the child creates SQLite."""
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if journal_api.STATE.exists():
            current = journal_api.read_events(0)
            if current['execution_id'] != execution_id:
                raise RuntimeError('Stop the previous preview before starting a new execution')
            return current
        if OWNER.exists():
            owner = json.loads(OWNER.read_text())
            if owner['execution_id'] != execution_id:
                raise RuntimeError('Stop the previous preview before starting a new execution')
            if not alive(owner['pid']):
                journal = Journal(execution_id, LockedRedactor())
                journal.status('interrupted', reason='Preview supervisor stopped before creating its journal')
                journal.db.close()
                return journal_api.read_events(0)
        else:
            process = subprocess.Popen([sys.executable, __file__, 'supervise', execution_id], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            OWNER.write_text(json.dumps({'execution_id': execution_id, 'pid': process.pid}))
        return {'execution_id': execution_id, 'state': 'starting', 'ready': False, 'details': {}, 'cursor': 0, 'events': []}


def stop():
    if not journal_api.STATE.exists() and not OWNER.exists():
        return
    owner = json.loads(OWNER.read_text()) if OWNER.exists() else None
    if owner:
        try:
            os.kill(owner['pid'], signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if journal_api.STATE.exists():
            current = journal_api.read_events(0)
            if current['state'] in TERMINAL:
                return
        time.sleep(0.05)
    execution_id = owner['execution_id'] if owner else journal_api.read_events(0)['execution_id']
    journal = Journal(execution_id, LockedRedactor())
    journal.status('interrupted', reason='Preview supervisor did not finish before workload cleanup')
    journal.db.close()


if __name__ == '__main__':
    action = sys.argv[1]
    if action == 'events':
        sys.stdout.write(json.dumps(read_events(int(sys.argv[2]))) + '\n')
    elif action == 'start':
        sys.stdout.write(json.dumps(start(str(uuid.UUID(sys.argv[2])))) + '\n')
    elif action == 'stop':
        stop()
    else:
        with LOCK.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            supervisor = Supervisor(json.loads(PLAN.read_text()), str(uuid.UUID(sys.argv[2])))
        signal.signal(signal.SIGTERM, supervisor.cancel_signal)
        signal.signal(signal.SIGINT, supervisor.cancel_signal)
        supervisor.execute()

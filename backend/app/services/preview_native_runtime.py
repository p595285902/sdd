"""Trusted platform adapter for per-chat private Docker daemons.

Only provisioning uses the platform Engine. Every project command is executed
inside the outer sandbox against its rootless private socket. Privilege is a
configured deployment exception for trusted projects, never inferred from docs.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote

from app.services.preview_workspace_sync import IGNORED

HELPER_IMAGE = 'python:3.14-slim-bookworm@sha256:c8137f4c460908c8763f281c8f22c431eb5c538514ba9553fc3a89c06b7cfb88'
NATIVE_LABEL = 'sdd.preview.native-execution'
PLATFORM_DOCKER = shutil.which('docker') or '/usr/local/bin/docker'
RUNNER = '/opt/preview/preview_native_session.py'
FORWARDER = '''import select,socket,socketserver
class Handler(socketserver.BaseRequestHandler):
 def handle(self):
  with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as upstream:
   upstream.connect('/registry-socket/proxy.sock')
   while True:
    readable,_,_=select.select((self.request,upstream),[],[],30)
    if not readable: return
    for source in readable:
     data=source.recv(65536)
     if not data: return
     (upstream if source is self.request else self.request).sendall(data)
class Server(socketserver.ThreadingMixIn,socketserver.TCPServer):
 allow_reuse_address=True
 daemon_threads=True
Server(('0.0.0.0',3128),Handler).serve_forever()
'''
UPLOAD = '''import os,shutil,sys,tarfile
from pathlib import Path
root=Path(sys.argv[1])
if root.resolve(strict=True)!=root or not root.is_dir(): raise ValueError('Invalid staging root')
with tarfile.open(fileobj=sys.stdin.buffer,mode='r|') as archive:
 for member in archive:
  parts=Path(member.name).parts
  if not member.isfile() or not parts or Path(member.name).is_absolute() or '..' in parts: raise ValueError('Invalid staging file')
  parent=root
  for part in parts[:-1]:
   parent/=part
   parent.mkdir(exist_ok=True)
   if parent.is_symlink() or not parent.is_dir(): raise ValueError('Redirected staging directory')
  fd=os.open(parent/parts[-1],os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,member.mode & 0o755)
  with os.fdopen(fd,'wb') as out,archive.extractfile(member) as inp: shutil.copyfileobj(inp,out)
'''
APPLY_SOURCE = '''import json,os,shutil,sys,tempfile
from pathlib import Path
stage=Path(sys.argv[1]); root=Path('/workspace')
current=json.loads((stage/'manifest.json').read_text())
manifest=Path('/run/user/1000/preview-sync-manifest.json')
previous=json.loads(manifest.read_text()) if manifest.exists() else {}
def destination(name):
 parts=Path(name).parts
 if not parts or Path(name).is_absolute() or '..' in parts: raise ValueError('Invalid source path')
 parent=root
 for part in parts[:-1]:
  parent/=part
  if parent.is_symlink(): raise ValueError('Redirected workspace directory')
  parent.mkdir(exist_ok=True)
 return parent/parts[-1]
for source in (stage/'files').rglob('*'):
 if source.is_file() and not source.is_symlink():
  name=source.relative_to(stage/'files').as_posix()
  target=destination(name)
  fd,tmp=tempfile.mkstemp(dir=target.parent)
  try:
   with os.fdopen(fd,'wb') as out,source.open('rb') as inp: shutil.copyfileobj(inp,out)
   os.chmod(tmp,source.stat().st_mode & 0o755)
   os.replace(tmp,target)
  finally:
   if os.path.exists(tmp): os.unlink(tmp)
for name in previous.keys()-current.keys():
 target=destination(name)
 if target.is_file() or target.is_symlink(): target.unlink()
manifest.write_text(json.dumps(current))
shutil.rmtree(stage)
'''


def archive_files(files: dict[str, tuple[bytes, int]], *, uid: int = 1000) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for name, (content, mode) in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.uid, info.gid = len(content), mode, uid, uid
            info.mtime = int(time.time())
            archive.addfile(info, io.BytesIO(content))
    return stream.getvalue()


def source_snapshot(checkout: Path) -> dict[str, tuple[bytes, int]]:
    """Use openat/no-follow at every component, not only the leaf file."""
    deadline = time.monotonic() + 2
    result = {}
    total = 0
    flags = os.O_RDONLY | os.O_NOFOLLOW

    def visit(directory: int, parts: tuple[str, ...]):
        nonlocal total
        for name in sorted(os.listdir(directory)):
            if time.monotonic() > deadline:
                raise RuntimeError('Preview source synchronization exceeded its time budget')
            if name in IGNORED or name in ('.docker', '.ssh', '.aws', '.kube') or name.endswith(('.pem', '.key')):
                continue
            metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                continue
            if stat.S_ISDIR(metadata.st_mode):
                fd = os.open(name, flags | os.O_DIRECTORY, dir_fd=directory)
                try:
                    visit(fd, (*parts, name))
                finally:
                    os.close(fd)
            elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                if len(result) >= 10000 or total + metadata.st_size > 64 * 1024 * 1024:
                    raise RuntimeError('Preview source synchronization exceeded its file or byte budget')
                fd = os.open(name, flags | os.O_NONBLOCK, dir_fd=directory)
                try:
                    before = os.fstat(fd)
                    fields = ('st_ino', 'st_dev', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
                    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or any(getattr(before, field) != getattr(metadata, field) for field in fields):
                        raise RuntimeError('Preview source changed before synchronization')
                    content = bytearray()
                    while chunk := os.read(fd, 65536):
                        content.extend(chunk)
                        if len(content) > metadata.st_size or time.monotonic() > deadline:
                            raise RuntimeError('Preview source changed or synchronization timed out')
                    after = os.fstat(fd)
                    if any(getattr(before, field) != getattr(after, field) for field in fields) or len(content) != before.st_size:
                        raise RuntimeError('Preview source changed during synchronization')
                    total += len(content)
                    result['/'.join((*parts, name))] = (bytes(content), metadata.st_mode & 0o755)
                finally:
                    os.close(fd)

    fd = os.open(checkout, flags | os.O_DIRECTORY)
    try:
        visit(fd, ())
    finally:
        os.close(fd)
    return result


def snapshot_secret_values(files: dict[str, tuple[bytes, int]]) -> list[str]:
    """Inspect the exact staged bytes, before watch can observe new credentials."""
    import yaml

    secret_key = re.compile(r'password|passwd|secret|token|api[_-]?key|private[_-]?key|credential', re.I)
    assignment = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*?)\s*$')
    values = []
    budget = 0
    nodes = 0

    def collect(value, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > 10000 or depth > 16:
            raise RuntimeError('Project secret discovery exceeded its structure budget')
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and secret_key.search(key) and isinstance(item, (str, int, float, bool)):
                    values.append(str(item))
                else:
                    collect(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and '=' in item and secret_key.search(item.partition('=')[0]):
                    values.append(item.partition('=')[2])
                else:
                    collect(item, depth + 1)

    for name, (content, _) in files.items():
        try:
            text = content.decode('utf-8')
        except UnicodeError:
            continue
        found = []
        for line in text.splitlines():
            match = assignment.match(line)
            if match and secret_key.search(match[1]):
                found.append(match[2].strip('\"\''))
        configuration = Path(name).suffix in ('.yaml', '.yml', '.env') or Path(name).name.startswith('.env')
        if configuration or found:
            budget += len(content)
            if len(content) > 262144 or budget > 1048576:
                raise RuntimeError('Project secret discovery exceeded its configuration budget')
        values.extend(found)
        if Path(name).suffix in ('.yaml', '.yml'):
            try:
                collect(yaml.safe_load(text))
            except yaml.YAMLError:
                raise RuntimeError('Project configuration could not be inspected before source synchronization') from None
    return values


def replay_events(events: list[dict], after: int, *, limit: int = 100) -> list[dict]:
    """Keep the remainder of an evicted range when replay starts inside a gap."""
    result = []
    for event in events:
        if event['kind'] == 'gap' and event['cursor'] <= after < event['payload']['through_cursor']:
            result.append({**event, 'cursor': after + 1})
        elif event['cursor'] > after:
            result.append(event)
        if len(result) >= limit:
            break
    return result


class NativeRuntime:
    def __init__(self, controller):
        self.c = controller
        self.lock = threading.RLock()
        self.operations: dict[uuid.UUID, threading.RLock] = {}
        self.previous: dict[uuid.UUID, dict] = {}
        self.last: dict[uuid.UUID, dict] = {}
        self.terminal: OrderedDict[uuid.UUID, dict] = OrderedDict()
        self.helper_id: str | None = None

    def operation(self, chat_id):
        with self.lock:
            return self.operations.setdefault(chat_id, threading.RLock())

    def exec(self, chat_id: uuid.UUID, argv: list[str], *, detach=False, limit=1024 * 1024, user='1000:1000') -> bytes:
        code, result = self.c.docker('POST', f'/containers/{self.c.container_name(chat_id)}/exec', {
            'Cmd': argv, 'User': user, 'AttachStdout': not detach, 'AttachStderr': False,
        })
        if code != 201:
            raise RuntimeError('Private Docker sandbox is unavailable')
        if detach:
            if self.c.docker('POST', f"/exec/{result['Id']}/start", {'Detach': True, 'Tty': False})[0] != 200:
                raise RuntimeError('Private Docker supervisor could not start')
            return b''
        connection = self.c.DockerConnection()
        try:
            connection.request('POST', f"/v1.47/exec/{result['Id']}/start", body=b'{"Detach":false,"Tty":true}', headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            output = response.read(limit + 1)
            if response.status != 200 or len(output) > limit:
                raise RuntimeError('Private Docker response exceeded its limit')
        finally:
            connection.close()
        code, state = self.c.docker('GET', f"/exec/{result['Id']}/json")
        if code != 200 or state.get('Running') or state.get('ExitCode') != 0:
            raise RuntimeError('Private Docker operation failed; check the configured native runtime image and privilege policy')
        return output

    def management_env(self):
        return {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/tmp', 'DOCKER_CONFIG': '/controller/empty-docker-config', 'DOCKER_HOST': 'unix://' + self.c.SOCKET}

    def upload(self, chat_id, files, path, *, uid=1000):
        # Engine archive extraction rejects even writable tmpfs destinations on
        # a read-only rootfs. Stream only our regular-file archive to a trusted
        # unprivileged writer instead; do not weaken the sandbox rootfs policy.
        try:
            result = subprocess.run(
                [PLATFORM_DOCKER, 'exec', '-i', '--user', f'{uid}:{uid}', self.c.container_name(chat_id), 'python3', '-c', UPLOAD, path],
                input=archive_files(files, uid=uid), stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=self.management_env(), timeout=30,
            )
            if result.returncode:
                raise RuntimeError('Unable to stage selected-checkout inputs in the private sandbox')
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError('Private sandbox source staging was unavailable or timed out') from error

    def sync(self, chat_id):
        with self.operation(chat_id):
            files = source_snapshot(Path(self.c.WORKSPACE_ROOT) / str(chat_id))
            hashes = {name: hashlib.sha256(value[0]).hexdigest() for name, value in files.items()}
            previous = self.previous.get(chat_id)
            if previous == hashes:
                return
            if previous is None:
                self.exec(chat_id, ['python3', '-c', "from pathlib import Path; p=Path('/run/user/1000/preview-sync-manifest.json'); print(p.read_text() if p.exists() else '{}')"])
            stage = 'preview-sync-' + uuid.uuid4().hex
            changed = {f'{stage}/files/{name}': value for name, value in files.items() if not previous or previous.get(name) != hashes[name]}
            changed[f'{stage}/manifest.json'] = (json.dumps(hashes).encode(), 0o600)
            changed[f'{stage}/secrets.json'] = (json.dumps(snapshot_secret_values(files)).encode(), 0o600)
            self.upload(chat_id, changed, '/tmp')
            # The live supervisor acknowledges the expanded mask set before any
            # source file is exposed to native watch or application processes.
            self.exec(chat_id, ['python3', RUNNER, 'prepare-sync', '/tmp/' + stage])
            self.exec(chat_id, ['python3', '-c', APPLY_SOURCE, '/tmp/' + stage])
            self.previous[chat_id] = hashes

    def seed_helper(self, chat_id):
        # Only the fixed, public trusted forwarding image crosses this boundary.
        # Project Docker commands/builds never address the platform Engine.
        self.c.ensure_image(HELPER_IMAGE)
        code, image = self.c.docker('GET', f'/images/{quote(HELPER_IMAGE, safe="")}/json')
        if code != 200:
            raise RuntimeError('The fixed trusted forwarding image is not available')
        self.helper_id = image['Id']
        env = self.management_env()
        save = subprocess.Popen([PLATFORM_DOCKER, 'image', 'save', HELPER_IMAGE], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        load = None
        try:
            load = subprocess.Popen([PLATFORM_DOCKER, 'exec', '-i', self.c.container_name(chat_id), 'docker', 'image', 'load'], stdin=save.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            save.stdout.close()
            deadline = time.monotonic() + 90
            while load.poll() is None:
                if time.monotonic() > deadline or (self.c.acceptance_reset.enabled and self.c.acceptance_reset.cancel.is_set()):
                    raise RuntimeError('Trusted native-runtime helper transfer was stopped or timed out')
                time.sleep(0.1)
            if save.wait(timeout=5) or load.returncode:
                raise RuntimeError('Unable to provision the fixed trusted native-runtime helper image')
        finally:
            if save.stdout and not save.stdout.closed:
                save.stdout.close()
            for process in (save, load):
                if process is None:
                    continue
                if process.poll() is None:
                    process.kill()
                process.wait()

    def launch(self, chat_id: uuid.UUID, plan: dict, execution_id: str) -> dict:
        execution_id = str(uuid.UUID(execution_id))
        if plan.get('runtime') != 'native-compose' or not isinstance(plan.get('commands'), list) or not 1 <= len(plan['commands']) <= 16:
            raise ValueError('Invalid native Compose plan')
        if os.environ.get('PREVIEW_NATIVE_PRIVILEGED', '').lower() != 'true':
            raise RuntimeError('Native Compose needs an explicitly approved private rootless sandbox policy. Configure PREVIEW_NATIVE_PRIVILEGED=true only for trusted projects on a dedicated Docker host or VM; privileged outer sandboxes are not hostile-code containment.')
        with self.operation(chat_id):
            existing = self.c.inspect(chat_id)
            if existing:
                if existing['Config']['Labels'].get(NATIVE_LABEL) == execution_id:
                    return self.status(chat_id, existing)
                raise RuntimeError('Stop the previous preview before starting a new execution')
            image = os.environ.get('PREVIEW_NATIVE_IMAGE', self.c.PROJECT + '-preview-native:runtime')
            if self.c.docker('GET', f'/images/{quote(image, safe="")}/json')[0] != 200:
                raise RuntimeError('The configured native preview image is missing. Build backend/preview-native.Dockerfile and configure PREVIEW_NATIVE_IMAGE before launching.')
            checkout = Path(self.c.WORKSPACE_ROOT) / str(chat_id)
            if checkout.is_symlink() or not checkout.is_dir():
                raise FileNotFoundError('Development Chat checkout is not ready')
            self.terminal.pop(chat_id, None)
            self.c.legacy.terminal.pop(chat_id, None)
            self.previous.pop(chat_id, None)
            socket_volume = self.c.resource_name(chat_id, 'socket')
            proxy = self.c.resource_name(chat_id, 'registry')
            try:
                if self.c.docker('POST', '/volumes/create', {'Name': socket_volume, 'Labels': self.c.labels(chat_id)})[0] != 201:
                    raise RuntimeError('Unable to provision native acquisition socket')
                with self.c.resource_lock:
                    self.c.ensure_outbound_network()
                    code, _ = self.c.docker('POST', f'/containers/create?name={quote(proxy)}', {
                        'Image': self.c.IMAGE, 'Cmd': ['python', '/controller/preview_registry_proxy.py'], 'Labels': self.c.labels(chat_id),
                        'HostConfig': {'NetworkMode': self.c.outbound_network(), 'Mounts': [{'Type': 'volume', 'Source': socket_volume, 'Target': '/registry-socket'}], 'ReadonlyRootfs': True, 'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'], 'Memory': 67108864, 'NanoCpus': 250000000, 'PidsLimit': 32, 'AutoRemove': True},
                    })
                    if code != 201 or self.c.docker('POST', f'/containers/{proxy}/start')[0] != 204:
                        raise RuntimeError('Unable to provision native bounded acquisition helper')
                code, result = self.c.docker('POST', f'/containers/create?name={quote(self.c.container_name(chat_id))}', {
                    'Image': image, 'User': '1000:1000', 'Cmd': ['dockerd', '--host=unix:///run/user/1000/docker.sock'],
                    'Labels': {**self.c.labels(chat_id), NATIVE_LABEL: execution_id},
                    'Env': ['DOCKER_HOST=unix:///run/user/1000/docker.sock', 'HTTP_PROXY=http://127.0.0.1:3128', 'HTTPS_PROXY=http://127.0.0.1:3128', 'NO_PROXY=localhost,127.0.0.1', 'PREVIEW_HELPER_IMAGE=' + HELPER_IMAGE],
                    'HostConfig': {'Privileged': True, 'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Memory': 1610612736, 'MemorySwap': 1610612736, 'NanoCpus': 500000000, 'PidsLimit': 512,
                        'Mounts': [{'Type': 'volume', 'Source': socket_volume, 'Target': '/registry-socket', 'ReadOnly': True}],
                        'Tmpfs': {'/home/rootless': 'rw,nosuid,nodev,size=32m,uid=1000,gid=1000', '/home/rootless/.local/share/docker': 'rw,nosuid,nodev,size=1024m,uid=1000,gid=1000', '/var/lib/docker': 'rw,nosuid,nodev,size=1m', '/run/user/1000': 'rw,nosuid,nodev,size=16m,uid=1000,gid=1000', '/tmp': 'rw,nosuid,nodev,size=96m,uid=1000,gid=1000', '/workspace': 'rw,nosuid,nodev,size=96m,uid=1000,gid=1000'}},
                })
                if code != 201 or self.c.docker('POST', f"/containers/{result['Id']}/start")[0] != 204:
                    raise RuntimeError('The deployment could not provision its approved private rootless Docker sandbox; no shared-daemon fallback is permitted')
                deadline = time.monotonic() + 30
                while True:
                    try:
                        info = json.loads(self.exec(chat_id, ['docker', 'info', '--format', '{{json .SecurityOptions}}']))
                        if not any('rootless' in value for value in info):
                            raise RuntimeError('The private Docker daemon must remain rootless')
                        break
                    except RuntimeError:
                        if time.monotonic() > deadline:
                            raise RuntimeError('Private rootless Docker could not start within the configured sandbox policy; check the dedicated host and native runtime image') from None
                        time.sleep(0.25)
                self.seed_helper(chat_id)
                # RootlessKit's daemon namespace and the outer CLI namespace
                # have distinct loopbacks. Both need the same bounded socket
                # transport: BuildKit's auth session may run in the CLI.
                self.exec(chat_id, ['python3', '-u', '-c', FORWARDER], detach=True)
                self.exec(chat_id, ['python3', '-c', "import socket,time; deadline=time.monotonic()+5\nwhile True:\n try:\n  socket.create_connection(('127.0.0.1',3128),timeout=1).close(); break\n except OSError:\n  if time.monotonic()>deadline: raise\n  time.sleep(0.05)"])
                self.exec(chat_id, ['docker', 'run', '-d', '--name', 'trusted-acquisition-forwarder', '--pull=never', '--network=host', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=32', '--mount', 'type=bind,source=/registry-socket,target=/registry-socket,readonly', self.helper_id, 'python', '-u', '-c', FORWARDER])
                # Docker's own documented proxy configuration supplies native
                # build arguments; project Compose files are never rewritten.
                proxy_config = json.dumps({'proxies': {'default': {'httpProxy': 'http://172.17.0.1:3128', 'httpsProxy': 'http://172.17.0.1:3128', 'noProxy': 'localhost,127.0.0.1'}}})
                self.exec(chat_id, ['python3', '-c', "from pathlib import Path; import sys; p=Path('/home/rootless/.docker'); p.mkdir(exist_ok=True); (p/'config.json').write_text(sys.argv[1])", proxy_config])
                self.sync(chat_id)
                self.upload(chat_id, {'preview-plan.json': (json.dumps(plan).encode(), 0o600)}, '/run/user/1000')
                self.exec(chat_id, ['env', 'PREVIEW_HELPER_IMAGE=' + self.helper_id, 'python3', RUNNER, 'start', execution_id])
                with self.c.activity_lock:
                    self.c.activity[chat_id] = time.time()
                value = {'execution_id': execution_id, 'state': 'starting', 'ready': False, 'details': {}, 'cursor': 0}
                self.last[chat_id] = value
                return {'runtime': 'native-compose', **value}
            except Exception:
                self.c.stop(chat_id)
                raise

    def status(self, chat_id, container=None):
        container = container or self.c.inspect(chat_id)
        if container and container['Config']['Labels'].get(NATIVE_LABEL):
            execution_id = container['Config']['Labels'][NATIVE_LABEL]
            current = self.last.get(chat_id, {'execution_id': execution_id, 'state': 'starting', 'ready': False, 'details': {}})
            if not container['State'].get('Running'):
                current = {**current, 'state': 'interrupted', 'ready': False}
            return {'id': container['Id'], 'runtime': 'native-compose', **{key: value for key, value in current.items() if key != 'events'}, **(current['details'] if current.get('ready') else {})}
        return None if container else self.terminal.get(chat_id)

    def read(self, chat_id, after):
        return json.loads(self.exec(chat_id, ['python3', RUNNER, 'events', str(after)], limit=1024 * 1024))

    def events(self, chat_id, after=0):
        with self.operation(chat_id):
            container = self.c.inspect(chat_id)
            if container and container['Config']['Labels'].get(NATIVE_LABEL):
                try:
                    current = self.read(chat_id, after)
                except RuntimeError:
                    # A fresh detached supervisor may not have created its journal.
                    return {**self.status(chat_id, container), 'events': []}
                self.last[chat_id] = current
                if current['state'] in ('failed', 'stopped', 'interrupted'):
                    self.preserve(chat_id, current)
                    self.c.stop(chat_id)
                    return self.events(chat_id, after)
                # A terminal status at the end of a later page must not prevent
                # the durable collector from persisting earlier journal pages.
                if current.get('events') and current['events'][-1]['cursor'] < current['cursor']:
                    current = {**current, 'state': 'running', 'ready': False}
                return current
            current = self.terminal.get(chat_id)
            if current:
                events = replay_events(current['events'], after)
                state = current['state'] if not events or events[-1]['cursor'] >= current['cursor'] else 'running'
                return {**current, 'events': events, 'state': state}
            raise FileNotFoundError('Native preview execution is missing')

    def preserve(self, chat_id, current):
        events, cursor = [], 0
        while cursor < current['cursor']:
            page = self.read(chat_id, cursor)
            if not page['events']:
                raise RuntimeError('Native journal ended before its terminal cursor')
            events.extend(page['events'])
            last = page['events'][-1]
            next_cursor = last['payload'].get('through_cursor', last['cursor']) if last['kind'] == 'gap' else last['cursor']
            if next_cursor <= cursor:
                raise RuntimeError('Native journal did not advance')
            cursor = next_cursor
        self.terminal[chat_id] = {**current, 'events': events, 'ready': False}
        self.terminal.move_to_end(chat_id)
        while len(self.terminal) > 64:
            self.terminal.popitem(last=False)

    def before_stop(self, chat_id, container):
        if not container or not container['Config']['Labels'].get(NATIVE_LABEL):
            return
        with self.operation(chat_id):
            if chat_id not in self.terminal:
                try:
                    self.exec(chat_id, ['python3', '-c', "import os,signal; from pathlib import Path; p=Path('/run/user/1000/preview-supervisor.pid'); os.kill(int(p.read_text()),signal.SIGTERM) if p.exists() else None"])
                    deadline = time.monotonic() + 10
                    while True:
                        current = self.read(chat_id, 0)
                        if current['state'] in ('failed', 'stopped', 'interrupted') or time.monotonic() >= deadline:
                            break
                        time.sleep(0.1)
                    if current['state'] not in ('failed', 'stopped', 'interrupted'):
                        current = {**current, 'state': 'stopped', 'ready': False}
                    self.preserve(chat_id, current)
                except RuntimeError:
                    self.terminal[chat_id] = {'execution_id': container['Config']['Labels'][NATIVE_LABEL], 'state': 'interrupted', 'ready': False, 'details': {}, 'events': [], 'cursor': 0}
            self.previous.pop(chat_id, None)
            self.last.pop(chat_id, None)

    def browser_command(self, current, port):
        route = current.get('details', {}).get('routes', {}).get(port)
        if not route or not isinstance(route.get('container'), str) or not route['container'].isalnum():
            raise ValueError('Unregistered application route')
        if self.helper_id is None:
            code, image = self.c.docker('GET', f'/images/{quote(HELPER_IMAGE, safe="")}/json')
            if code != 200:
                raise RuntimeError('The fixed trusted forwarding image is not available')
            self.helper_id = image['Id']
        return ['docker', 'run', '--rm', '-i', '--pull=never', '--network=container:' + route['container'], '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=32', self.helper_id], str(route['target'])

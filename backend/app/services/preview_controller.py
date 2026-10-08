import base64
import http.client
import io
import json
import logging
import os
import socket
import tarfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from app.services.preview_compose import (
    documented_compose,
    staged_build,
    validated_graph,
)

SOCKET = "/var/run/docker.sock"
WORKSPACE_ROOT = "/develop-workspaces"
VOLUME = os.environ["PREVIEW_WORKSPACE_VOLUME"]
PROJECT = os.environ["PREVIEW_PROJECT"]
IMAGE = os.environ["PREVIEW_IMAGE"]
logger = logging.getLogger(__name__)
IDLE_SECONDS = 300
activity: dict[uuid.UUID, float] = {}
ready_services: dict[uuid.UUID, dict[str, str]] = {}
failed_services: set[uuid.UUID] = set()
activity_lock = threading.Lock()
resource_lock = threading.RLock()


class DockerConnection(http.client.HTTPConnection):
    def __init__(self) -> None:
        super().__init__("localhost", timeout=10)

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SOCKET)


def docker(
    method: str, path: str, payload: dict | None = None
) -> tuple[int, dict | list]:
    connection = DockerConnection()
    try:
        body = json.dumps(payload).encode() if payload is not None else None
        connection.request(
            method,
            "/v1.47" + path,
            body=body,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        response = connection.getresponse()
        data = response.read()
        try:
            return response.status, json.loads(data) if data else {}
        except json.JSONDecodeError:
            if response.status < 400:
                raise RuntimeError("Invalid Docker Engine response") from None
            return response.status, {}
    finally:
        connection.close()


def docker_stream(method: str, path: str, body: bytes | None = None, *, content_type: str = "application/json") -> bytes:
    connection = DockerConnection()
    connection.timeout = 120
    try:
        connection.request(method, "/v1.47" + path, body=body, headers={"Content-Type": content_type})
        response = connection.getresponse()
        data = response.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024 or response.status >= 400:
            raise RuntimeError(f"Preview image operation failed ({response.status})")
        for line in data.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                raise RuntimeError("Invalid Docker image response") from None
            if event.get("error") or event.get("errorDetail"):
                raise RuntimeError("Preview image operation failed")
        return data
    finally:
        connection.close()


def stream_into_container(container: str, archive: bytes) -> None:
    if len(archive) > 16 * 1024 * 1024:
        raise ValueError("Dependency build context exceeds setup limits")
    def execute(arguments: list[str]) -> None:
        code, result = docker("POST", f"/containers/{container}/exec", {
            "Cmd": arguments, "User": "65534:65534", "AttachStdout": False, "AttachStderr": False,
        })
        if code != 201 or docker("POST", f"/exec/{result['Id']}/start", {"Detach": True, "Tty": False})[0] != 200:
            raise RuntimeError("Unable to stage preview input")
        deadline = time.monotonic() + 10
        while True:
            code, state = docker("GET", f"/exec/{result['Id']}/json")
            if code != 200 or time.monotonic() >= deadline:
                raise RuntimeError("Preview input staging timed out")
            if not state["Running"]:
                if state["ExitCode"] != 0:
                    raise RuntimeError("Preview input staging failed")
                return
            time.sleep(0.05)

    for offset in range(0, len(archive), 24 * 1024):
        chunk = base64.b64encode(archive[offset:offset + 24 * 1024]).decode("ascii")
        execute(["python", "-c", "import base64,sys; open('/workspace/.preview-input.tar','ab').write(base64.b64decode(sys.argv[1]))", chunk])
    execute(["python", "-c", "import tarfile; tarfile.open('/workspace/.preview-input.tar').extractall('/workspace',filter='data')"])
    execute(["python", "-c", "import os; os.unlink('/workspace/.preview-input.tar')"])
    execute(["python", "-c", "from pathlib import Path; assert Path('/workspace/requirements.txt').is_file() or Path('/workspace/package-lock.json').is_file()"])


def read_dependencies(container: str) -> bytes:
    def output(script: str, *args: str) -> bytes:
        code, result = docker("POST", f"/containers/{container}/exec", {
            "Cmd": ["python", "-c", script, *args], "User": "65534:65534",
            "AttachStdout": True, "AttachStderr": True,
        })
        if code != 201:
            raise RuntimeError("Unable to inspect preview dependencies")
        connection = DockerConnection()
        try:
            connection.request("POST", f"/v1.47/exec/{result['Id']}/start", body=b'{"Detach":false,"Tty":true}', headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            data = response.read(64 * 1024)
            if response.status != 200 or len(data) >= 64 * 1024:
                raise RuntimeError("Preview dependency output exceeded limits")
        finally:
            connection.close()
        code, state = docker("GET", f"/exec/{result['Id']}/json")
        if code != 200 or state["ExitCode"] != 0:
            logger.error("Preview dependency read exit: %s, output: %s", state.get("ExitCode"), data[:512])
            raise RuntimeError("Unable to read preview dependencies")
        return data.strip()

    output("import tarfile\nwith tarfile.open('/workspace/.preview-output.tar','w') as archive:\n archive.add('/workspace/.preview-deps',arcname='.preview-deps')")
    size = int(output("from pathlib import Path; print(Path('/workspace/.preview-output.tar').stat().st_size)"))
    if size > 16 * 1024 * 1024:
        raise ValueError("Preview dependency output exceeds limits")
    return b"".join(base64.b64decode(output(
        "import base64,sys; file=open('/workspace/.preview-output.tar','rb'); file.seek(int(sys.argv[1])); print(base64.b64encode(file.read(24576)).decode())",
        str(offset),
    )) for offset in range(0, size, 24576))


def read_helper_ready(container: str) -> bool:
    code, result = docker("POST", f"/containers/{container}/exec", {
        "Cmd": ["python", "-c", "from pathlib import Path; assert Path('/workspace/.preview-ready').is_file()"],
        "User": "65534:65534", "AttachStdout": False, "AttachStderr": False,
    })
    if code != 201 or docker("POST", f"/exec/{result['Id']}/start", {"Detach": True, "Tty": False})[0] != 200:
        raise RuntimeError("Unable to check preview dependency readiness")
    while True:
        code, state = docker("GET", f"/exec/{result['Id']}/json")
        if code != 200:
            raise RuntimeError("Unable to inspect preview dependency readiness")
        if not state["Running"]:
            return state["ExitCode"] == 0
        time.sleep(0.05)


def container_name(chat_id: uuid.UUID) -> str:
    return f"{PROJECT}-preview-{chat_id}"


def resource_name(chat_id: uuid.UUID, kind: str) -> str:
    return f"{container_name(chat_id)}-{kind}"


def labels(chat_id: uuid.UUID) -> dict[str, str]:
    return {"sdd.preview.chat-id": str(chat_id), "sdd.preview.project": PROJECT}


def outbound_network() -> str:
    return f"{PROJECT}-preview-registry-egress"


def ensure_outbound_network() -> None:
    name = outbound_network()
    code, result = docker("GET", f"/networks/{name}")
    if code == 200:
        if result.get("Labels", {}).get("sdd.preview.project") != PROJECT:
            raise RuntimeError("Preview outbound network name is already in use")
        return
    if code != 404:
        raise RuntimeError(f"Unable to inspect preview outbound network ({code})")
    code, _ = docker("POST", "/networks/create", {
        "Name": name, "Labels": {"sdd.preview.project": PROJECT}, "Internal": False
    })
    if code != 201:
        raise RuntimeError(f"Unable to create preview outbound network ({code})")


def remove_container(name: str) -> None:
    for attempt in range(10):
        code, _ = docker("DELETE", f"/containers/{name}?force=true")
        if code in (204, 404):
            return
        if code != 409 or attempt == 9:
            raise RuntimeError(f"Unable to remove preview container ({code})")
        time.sleep(0.1)


def remove_resource(path: str) -> None:
    for attempt in range(10):
        code, _ = docker("DELETE", path)
        if code in (200, 204, 404):
            return
        if code != 409 or attempt == 9:
            raise RuntimeError(f"Unable to remove preview resource ({code})")
        time.sleep(0.1)


def inspect(chat_id: uuid.UUID) -> dict | None:
    code, result = docker("GET", f"/containers/{container_name(chat_id)}/json")
    if code == 404:
        return None
    if code != 200:
        raise RuntimeError("Unable to inspect preview workload")
    labels = result["Config"]["Labels"]
    if (
        labels.get("sdd.preview.chat-id") != str(chat_id)
        or labels.get("sdd.preview.project") != PROJECT
    ):
        raise RuntimeError("Preview workload name is already in use")
    return result


def status(chat_id: uuid.UUID) -> dict[str, str]:
    container = inspect(chat_id)
    if container is None:
        with activity_lock:
            if chat_id in failed_services:
                return {"state": "failed"}
        raise FileNotFoundError("Preview workload not found")
    result = {"id": container["Id"], "state": container["State"]["Status"]}
    with activity_lock:
        if container["State"]["Running"]:
            result.update(ready_services.get(chat_id, {}))
    return result


def start(chat_id: uuid.UUID) -> dict[str, str]:
    checkout = os.path.join(WORKSPACE_ROOT, str(chat_id))
    if os.path.islink(checkout) or not os.path.isdir(checkout):
        raise FileNotFoundError("Development Chat checkout is not ready")
    documented = documented_compose(Path(checkout))
    if documented is not None:
        graph = validated_graph(Path(checkout), *documented)
        roots = [name for name in documented[1] if not any(
            name in service.get("depends_on", []) for other, service in graph if other != name
        )]
        if len(roots) != 1:
            raise ValueError("Document one website entry service")
        primary = roots[0]
        if not dict(graph)[primary].get("expose"):
            raise ValueError("Documented website port is required")
        staged = {
            name: staged_build(Path(checkout), service["build"])
            for name, service in graph if "build" in service
        }
        return start_compose(chat_id, graph, primary, staged)
    existing = inspect(chat_id)
    if existing is not None:
        if existing["State"]["Running"]:
            return status(chat_id)
        stop(chat_id)
    socket_volume = resource_name(chat_id, "socket")
    proxy = resource_name(chat_id, "registry")
    code, _ = docker("POST", "/volumes/create", {"Name": socket_volume, "Labels": labels(chat_id)})
    if code != 201:
        raise RuntimeError(f"Unable to create preview socket volume ({code})")
    try:
        with resource_lock:
            ensure_outbound_network()
            code, _ = docker("POST", f"/containers/create?name={quote(proxy)}", {
                "Image": IMAGE,
                "Cmd": ["python", "/controller/preview_registry_proxy.py"],
                "Labels": labels(chat_id),
                "HostConfig": {
                    "NetworkMode": outbound_network(),
                    "Mounts": [{"Type": "volume", "Source": socket_volume, "Target": "/registry-socket"}],
                    "ReadonlyRootfs": True,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"],
                    "Memory": 134217728,
                    "NanoCpus": 500000000,
                    "PidsLimit": 32,
                    "AutoRemove": True,
                },
            })
            if code != 201:
                raise RuntimeError(f"Unable to create preview registry proxy ({code})")
            code, _ = docker("POST", f"/containers/{proxy}/start")
            if code != 204:
                raise RuntimeError(f"Unable to start preview registry proxy ({code})")
        result = create_workload(chat_id, socket_volume)
    except (RuntimeError, OSError):
        stop(chat_id)
        raise
    heartbeat(chat_id)
    return result


def ensure_image(image: str) -> None:
    code, _ = docker("GET", f"/images/{quote(image, safe='')}/json")
    if code == 404:
        docker_stream("POST", f"/images/create?fromImage={quote(image, safe='')}")
    elif code != 200:
        raise RuntimeError("Unable to inspect approved preview image")


def compose_image(chat_id: uuid.UUID, service: str, context: bytes, dockerfile: str) -> str:
    tag = f"{PROJECT}-preview-{chat_id}-{service}:staged"
    query = f"/build?t={quote(tag)}&dockerfile={quote(dockerfile)}&networkmode=none&pull=0&nocache=1&rm=1&memory=268435456&cpuquota=100000&cpuperiod=100000&labels={quote(json.dumps(labels(chat_id)))}"
    docker_stream("POST", query, context, content_type="application/x-tar")
    code, image = docker("GET", f"/images/{quote(tag, safe='')}/json")
    if code != 200 or not image.get("Id"):
        raise RuntimeError("Preview build did not produce an image")
    return tag


def compose_dependencies(chat_id: uuid.UUID, service: str, context: bytes, kind: str) -> bytes:
    socket_volume = resource_name(chat_id, "socket")
    proxy = resource_name(chat_id, "registry")
    with resource_lock:
        code, volume = docker("GET", f"/volumes/{socket_volume}")
        if code == 404:
            code, _ = docker("POST", "/volumes/create", {"Name": socket_volume, "Labels": labels(chat_id)})
            if code != 201:
                raise RuntimeError("Unable to create preview dependency socket")
        elif code != 200 or volume.get("Labels") != labels(chat_id):
            raise RuntimeError("Preview dependency socket is not owned by this chat")
        ensure_outbound_network()
        code, existing = docker("GET", f"/containers/{proxy}/json")
        if code == 404:
            code, _ = docker("POST", f"/containers/create?name={quote(proxy)}", {
                "Image": IMAGE, "Cmd": ["python", "/controller/preview_registry_proxy.py"],
                "Labels": labels(chat_id),
                "HostConfig": {
                    "NetworkMode": outbound_network(),
                    "Mounts": [{"Type": "volume", "Source": socket_volume, "Target": "/registry-socket"}],
                    "ReadonlyRootfs": True, "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"], "Memory": 134217728,
                    "NanoCpus": 500000000, "PidsLimit": 32, "AutoRemove": True,
                },
            })
            if code != 201 or docker("POST", f"/containers/{proxy}/start")[0] != 204:
                raise RuntimeError("Unable to start preview dependency proxy")
        else:
            if (code != 200 or any(existing["Config"]["Labels"].get(key) != value for key, value in labels(chat_id).items())
                or existing["HostConfig"]["NetworkMode"] != outbound_network()
                or not any(mount.get("Source") == socket_volume and mount.get("Target") == "/registry-socket"
                           for mount in existing["HostConfig"].get("Mounts", []))
                or not existing["State"]["Running"]):
                raise RuntimeError("Preview dependency proxy is not owned by this chat")
    helper = resource_name(chat_id, f"build-{service}")
    script = """import shutil, subprocess, threading, time
from pathlib import Path
from preview_proxy_client import Server, Forwarder
server = Server(('127.0.0.1', 3128), Forwarder)
threading.Thread(target=server.serve_forever, daemon=True).start()
deadline = time.monotonic() + 60
while not Path('/workspace/requirements.txt' if __import__('sys').argv[1] == 'python' else '/workspace/package-lock.json').exists():
    if time.monotonic() >= deadline:
        raise RuntimeError('Dependency input staging timed out')
    time.sleep(0.1)
command = (['python', '-m', 'pip', 'install', '--no-cache-dir', '--no-compile', '--only-binary=:all:', '--target', '/workspace/.preview-deps/python', '-r', '/workspace/requirements.txt'] if __import__('sys').argv[1] == 'python' else ['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund', '--prefix', '/workspace'])
subprocess.run(command, check=True, timeout=35, cwd='/workspace', stdout=subprocess.DEVNULL)
if __import__('sys').argv[1] == 'node':
    Path('/workspace/.preview-deps').mkdir()
    shutil.move('/workspace/node_modules', '/workspace/.preview-deps/node_modules')
Path('/workspace/.preview-ready').touch()
time.sleep(90)
"""
    code, _ = docker("POST", f"/containers/create?name={quote(helper)}", {
        "Image": IMAGE, "User": "65534:65534", "WorkingDir": "/controller", "Cmd": ["python", "-c", script, kind],
        "Labels": {**labels(chat_id), "sdd.preview.compose-service": f"build-{service}"},
        "Env": ["HOME=/tmp", "PATH=/usr/local/bin:/usr/bin:/bin", "HTTP_PROXY=http://127.0.0.1:3128", "HTTPS_PROXY=http://127.0.0.1:3128", "NO_PROXY=localhost,127.0.0.1", "PIP_DISABLE_PIP_VERSION_CHECK=1", "PIP_INDEX_URL=https://pypi.org/simple", "npm_config_registry=https://registry.npmjs.org/", "npm_config_cache=/tmp/npm"],
        "HostConfig": {
            "NetworkMode": "none", "Mounts": [{"Type": "volume", "Source": socket_volume, "Target": "/registry-socket", "ReadOnly": True}],
            "ReadonlyRootfs": True, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"],
            "Memory": 268435456, "NanoCpus": 1000000000, "PidsLimit": 64,
            "Tmpfs": {"/tmp": "rw,nosuid,size=64m,uid=65534,gid=65534", "/workspace": "rw,nosuid,size=64m,uid=65534,gid=65534"},
        },
    })
    if code != 201:
        raise RuntimeError("Unable to create preview dependency setup")
    if docker("POST", f"/containers/{helper}/start")[0] != 204:
        raise RuntimeError("Unable to start preview dependency setup")
    stream_into_container(helper, context)
    deadline = time.monotonic() + 90
    while True:
        if read_helper_ready(helper):
            break
        code, state = docker("GET", f"/containers/{helper}/json")
        if code != 200:
            raise RuntimeError("Unable to inspect preview dependency setup")
        if not state["State"]["Running"]:
            logger.error("Preview dependency helper exited with code %s", state["State"]["ExitCode"])
            raise ValueError("Unsupported preview dependencies or download source")
        if time.monotonic() >= deadline:
            raise RuntimeError("Preview dependency setup timed out")
        time.sleep(0.25)
    archive = read_dependencies(helper)
    remove_container(helper)
    entries = []
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive)) as staged:
            for member in staged:
                path = Path(member.name)
                if (
                    not path.parts or path.parts[0] != ".preview-deps"
                    or ".." in path.parts or path.is_absolute()
                    or not (member.isfile() or member.isdir())
                ):
                    raise ValueError("Unsupported dependency archive entry")
                if member.isfile():
                    total += member.size
                    if len(entries) >= 2000 or total > 16 * 1024 * 1024:
                        raise ValueError("Preview dependencies exceed limits")
                    entries.append((member.name, staged.extractfile(member).read()))
    except tarfile.TarError:
        raise ValueError("Invalid dependency archive") from None
    if not entries:
        raise ValueError("Empty dependency archive")
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as target, tarfile.open(fileobj=io.BytesIO(context)) as original:
        for member in original:
            target.addfile(member, original.extractfile(member) if member.isfile() else None)
        for path, content in entries:
            entry = tarfile.TarInfo(path)
            entry.size = len(content)
            entry.mode = 0o644
            entry.uid = entry.gid = 65534
            target.addfile(entry, io.BytesIO(content))
    return output.getvalue()


def compose_network(chat_id: uuid.UUID) -> str:
    name = resource_name(chat_id, "compose")
    code, _ = docker("POST", "/networks/create", {
        "Name": name,
        "Labels": labels(chat_id),
        "Internal": True,
        "EnableIPv6": False,
        "Options": {"com.docker.network.bridge.gateway_mode_ipv4": "isolated"},
    })
    if code != 201:
        raise RuntimeError("Unable to create isolated preview network")
    code, result = docker("GET", f"/networks/{name}")
    if code != 200 or not result.get("Internal") or any(
        item.get("Gateway") for item in result.get("IPAM", {}).get("Config", [])
    ) or result.get("Options", {}).get("com.docker.network.bridge.gateway_mode_ipv4") != "isolated":
        raise RuntimeError("Docker did not enforce isolated preview networking")
    return name


def start_compose(
    chat_id: uuid.UUID, graph: list[tuple[str, dict]], primary: str, staged: dict[str, tuple[bytes, str | None, str]]
) -> dict[str, str]:
    existing = inspect(chat_id)
    if existing is not None:
        if existing["State"]["Running"] and existing["Config"]["Labels"].get("sdd.preview.compose-service") == primary:
            return status(chat_id)
        stop(chat_id)
    network = resource_name(chat_id, "compose")
    try:
        for image in {staged[name][2] if name in staged else service["image"] for name, service in graph}:
            ensure_image(image)
        images = {
            name: compose_image(chat_id, name,
                compose_dependencies(chat_id, name, staged[name][0], staged[name][1])
                if staged[name][1] else staged[name][0], service["build"]["dockerfile"])
            if name in staged else service["image"]
            for name, service in graph
        }
        compose_network(chat_id)
        for name, service in graph:
            container = container_name(chat_id) if name == primary else resource_name(chat_id, f"compose-{name}")
            code, result = docker("POST", f"/containers/create?name={quote(container)}", {
                "Image": images[name],
                "User": "65534:65534",
                "Cmd": service["command"],
                "WorkingDir": service.get("working_dir", "/workspace"),
                "Env": ["HOME=/tmp", "PATH=/usr/local/bin:/usr/bin:/bin"],
                "Labels": {**labels(chat_id), "sdd.preview.compose-service": name},
                "HostConfig": {
                    "NetworkMode": network,
                    "Privileged": False,
                    "ReadonlyRootfs": True,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"],
                    "Memory": 268435456,
                    "NanoCpus": 1000000000,
                    "PidsLimit": 64,
                    "Tmpfs": {"/tmp": "rw,nosuid,size=64m,uid=65534,gid=65534"},
                },
                "NetworkingConfig": {"EndpointsConfig": {network: {"Aliases": [name]}}},
            })
            if code != 201:
                raise RuntimeError("Unable to create private Compose service")
            code, _ = docker("POST", f"/containers/{result['Id']}/start")
            if code != 204:
                raise RuntimeError("Unable to start private Compose service")
            for port in service.get("expose", []):
                deadline = time.monotonic() + 15
                while True:
                    base_image = staged[name][2] if name in staged else service["image"]
                    probe_command = (
                        ["node", "-e", "require('net').connect(Number(process.argv[1]),'127.0.0.1').on('connect',()=>process.exit(0)).on('error',()=>process.exit(1))", str(port)]
                        if base_image.startswith("node:") else
                        ["python", "-c", "import socket,sys; socket.create_connection(('127.0.0.1',int(sys.argv[1])),timeout=1).close()", str(port)]
                    )
                    code, probe = docker("POST", f"/containers/{result['Id']}/exec", {
                        "Cmd": probe_command,
                        "AttachStdout": False,
                        "AttachStderr": False,
                    })
                    if code != 201:
                        raise RuntimeError("Unable to check private Compose service readiness")
                    code, _ = docker("POST", f"/exec/{probe['Id']}/start", {"Detach": True, "Tty": False})
                    if code != 200:
                        raise RuntimeError("Unable to start private Compose readiness check")
                    while True:
                        code, state = docker("GET", f"/exec/{probe['Id']}/json")
                        if code != 200:
                            raise RuntimeError("Unable to inspect private Compose readiness check")
                        if not state["Running"] or time.monotonic() >= deadline:
                            break
                        time.sleep(0.1)
                    if not state["Running"] and state["ExitCode"] == 0:
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Private Compose service did not become ready")
                    time.sleep(0.25)
        selected = dict(graph)[primary]
        ports = selected.get("expose", [])
        if not ports:
            raise RuntimeError("Documented website port is required")
        details = {"initial_port": str(ports[0]), "initial_path": "/", "website_port": str(ports[0])}
        for name, service in graph:
            if name != primary and service.get("expose"):
                details["api_port"] = str(service["expose"][0])
                break
        with activity_lock:
            failed_services.discard(chat_id)
            ready_services[chat_id] = details
        heartbeat(chat_id)
        return status(chat_id)
    except (OSError, RuntimeError, ValueError):
        stop(chat_id)
        with activity_lock:
            failed_services.add(chat_id)
        raise


def create_workload(chat_id: uuid.UUID, socket_volume: str) -> dict[str, str]:
    configuration = {
        "Image": IMAGE,
        "Cmd": ["python", "/controller/preview_proxy_client.py"],
        "User": "65534:65534",
        "WorkingDir": "/workspace",
        "Labels": labels(chat_id),
        "Env": ["HOME=/tmp", "PATH=/usr/local/bin:/usr/bin:/bin", "HTTPS_PROXY=http://127.0.0.1:3128", "HTTP_PROXY=http://127.0.0.1:3128", "NO_PROXY=localhost,127.0.0.1", "UV_CACHE_DIR=/tmp/uv", "npm_config_cache=/tmp/npm"],
        "HostConfig": {
            "Mounts": [
                {
                    "Type": "volume",
                    "Source": VOLUME,
                    "Target": "/checkout",
                    "ReadOnly": True,
                    "VolumeOptions": {"Subpath": str(chat_id)},
                },
                {"Type": "volume", "Source": socket_volume, "Target": "/registry-socket", "ReadOnly": True},
            ],
            "NetworkMode": "none",
            "Privileged": False,
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Memory": 268435456,
            "NanoCpus": 1000000000,
            "PidsLimit": 64,
            "Tmpfs": {"/tmp": "rw,nosuid,size=64m", "/workspace": "rw,nosuid,size=256m,uid=65534,gid=65534,mode=0700"},
            "AutoRemove": True,
        },
    }
    code, result = docker(
        "POST",
        f"/containers/create?name={quote(container_name(chat_id))}",
        configuration,
    )
    if code != 201:
        raise RuntimeError(f"Unable to create preview workload ({code})")
    code, _ = docker("POST", f"/containers/{result['Id']}/start")
    if code != 204:
        raise RuntimeError(f"Unable to start preview workload ({code})")
    deadline = time.monotonic() + 5
    while True:
        try:
            run_command(chat_id, {"cwd": ".", "argv": ["python", "-c", "from pathlib import Path; assert Path('/tmp/preview-source-ready').is_file()"]}, timeout=1)
            break
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise RuntimeError("Preview source sync failed or timed out") from None
            time.sleep(0.1)
    with activity_lock:
        failed_services.discard(chat_id)
    return status(chat_id)


def stop(chat_id: uuid.UUID) -> dict[str, str]:
    existing = inspect(chat_id)
    if existing is not None:
        if existing["State"]["Running"]:
            code, _ = docker("POST", f"/containers/{existing['Id']}/stop?t=1")
            if code not in (204, 304, 404):
                raise RuntimeError("Unable to stop preview workload")
        remove_container(existing["Id"])
    filters = quote(json.dumps({"label": [
        f"sdd.preview.project={PROJECT}", f"sdd.preview.chat-id={chat_id}",
        "sdd.preview.compose-service",
    ]}))
    code, containers = docker("GET", f"/containers/json?all=1&filters={filters}")
    if code != 200:
        raise RuntimeError("Unable to list private Compose containers")
    for container in containers:
        if container.get("Labels", {}).get("sdd.preview.chat-id") == str(chat_id):
            remove_container(container["Id"])
    network_name = resource_name(chat_id, "compose")
    code, network = docker("GET", f"/networks/{network_name}")
    if code == 200:
        if network.get("Labels") != labels(chat_id):
            raise RuntimeError("Private Compose network name is already in use")
        remove_resource(f"/networks/{network_name}")
    elif code != 404:
        raise RuntimeError("Unable to inspect private Compose network")
    image_filters = quote(json.dumps({"label": [
        f"sdd.preview.project={PROJECT}", f"sdd.preview.chat-id={chat_id}",
    ]}))
    code, images = docker("GET", f"/images/json?filters={image_filters}")
    if code != 200:
        raise RuntimeError("Unable to list private Compose images")
    for image in images:
        if image.get("Labels") == labels(chat_id):
            remove_resource(f"/images/{quote(image['Id'], safe='')}")
    with resource_lock:
        remove_container(resource_name(chat_id, "registry"))
        code, network = docker("GET", f"/networks/{outbound_network()}")
        if code == 200 and network.get("Labels", {}).get("sdd.preview.project") == PROJECT:
            if not network.get("Containers"):
                remove_resource(f"/networks/{outbound_network()}")
        elif code != 404:
            raise RuntimeError(f"Unable to inspect preview outbound network ({code})")
    remove_resource(f"/volumes/{resource_name(chat_id, 'socket')}")
    with activity_lock:
        activity.pop(chat_id, None)
        ready_services.pop(chat_id, None)
        failed_services.discard(chat_id)
    return {"state": "stopped"}


def restart(chat_id: uuid.UUID) -> dict[str, str]:
    stop(chat_id)
    return start(chat_id)


def run_command(
    chat_id: uuid.UUID, command: dict, *, timeout: float, detached: bool = False
) -> None:
    checkout = Path(WORKSPACE_ROOT, str(chat_id)).resolve(strict=True)
    directory = Path(command["cwd"])
    if directory.is_absolute() or ".." in directory.parts:
        raise RuntimeError("Unsupported preview working directory")
    target = (checkout / directory).resolve(strict=True)
    if not target.is_relative_to(checkout) or not target.is_dir():
        raise RuntimeError("Unsupported preview working directory")
    arguments = command["argv"]
    if not isinstance(arguments, list) or not arguments or any(
        not isinstance(argument, str) or len(argument) > 240 for argument in arguments
    ):
        raise RuntimeError("Unsupported preview command")
    code, result = docker("POST", f"/containers/{container_name(chat_id)}/exec", {
        "Cmd": arguments,
        "WorkingDir": str(Path("/workspace") / directory),
        "AttachStdout": False,
        "AttachStderr": False,
        "Env": ["HOME=/tmp", "HTTPS_PROXY=http://127.0.0.1:3128", "HTTP_PROXY=http://127.0.0.1:3128", "NO_PROXY=localhost,127.0.0.1", "npm_config_cache=/tmp/npm", "UV_CACHE_DIR=/tmp/uv"],
    })
    if code != 201:
        raise RuntimeError("Unable to prepare preview command")
    exec_id = result["Id"]
    code, _ = docker("POST", f"/exec/{exec_id}/start", {"Detach": True, "Tty": False})
    if code != 200:
        raise RuntimeError("Unable to start preview command")
    if detached:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code, state = docker("GET", f"/exec/{exec_id}/json")
        if code != 200:
            raise RuntimeError("Unable to inspect preview command")
        if not state["Running"]:
            if state["ExitCode"] != 0:
                raise RuntimeError("Preview command failed; check documented dependencies")
            return
        time.sleep(0.2)
    raise RuntimeError("Preview command timed out")


def launch(chat_id: uuid.UUID, plan: dict) -> dict[str, str]:
    current = status(chat_id)
    if current["state"] != "running":
        raise FileNotFoundError("Preview workload not running")
    if "initial_port" in current:
        return current
    try:
        for command in plan["setup"]:
            run_command(chat_id, command, timeout=60)
        roles = [role for role in ("api", "website") if plan.get(role)]
        for role in roles:
            server = plan[role]
            run_command(chat_id, server, timeout=5, detached=True)
        for role in roles:
            server = plan[role]
            port = int(server["port"])
            if port < 1024 or port > 65535:
                raise RuntimeError("Unsupported preview port")
            path = server["path"]
            if not isinstance(path, str) or not path.startswith("/") or "//" in path:
                raise RuntimeError("Unsupported preview health path")
            health = {
                "cwd": ".",
                "argv": ["python", "-c", "import sys, urllib.request; urllib.request.build_opener(urllib.request.ProxyHandler({})).open(sys.argv[1], timeout=2).read(1024)", f"http://127.0.0.1:{port}{path}"],
            }
            deadline = time.monotonic() + 12
            while True:
                try:
                    run_command(chat_id, health, timeout=3)
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Preview startup timed out") from None
                    time.sleep(0.25)
        heartbeat(chat_id)
        selected = plan.get("website") or plan["api"]
        details = {
            "initial_port": str(selected["port"]),
            "initial_path": plan.get("initial_path", selected["path"]),
            "api_port": str(plan["api"]["port"]),
        }
        if plan.get("website"):
            details["website_port"] = str(plan["website"]["port"])
        with activity_lock:
            ready_services[chat_id] = details
        return {"state": "running", **details}
    except (OSError, RuntimeError, KeyError, ValueError, TypeError) as error:
        logger.error("Preview launch failed: %s", error)
        stop(chat_id)
        with activity_lock:
            failed_services.add(chat_id)
        raise RuntimeError("Preview startup failed or timed out") from None


def heartbeat(chat_id: uuid.UUID) -> dict[str, str]:
    current = status(chat_id)
    if current["state"] != "running":
        raise FileNotFoundError("Preview workload not running")
    with activity_lock:
        activity[chat_id] = time.time()
    return current


def sweep(now: float | None = None) -> None:
    now = time.time() if now is None else now
    code, containers = docker(
        "GET",
        f"/containers/json?all=1&filters={quote(json.dumps({'label': [f'sdd.preview.project={PROJECT}']}))}",
    )
    if code != 200:
        raise RuntimeError("Unable to list preview workloads")
    for container in containers:
        labels = container.get("Labels", {})
        if labels.get("sdd.preview.project") != PROJECT:
            continue
        try:
            chat_id = uuid.UUID(labels["sdd.preview.chat-id"])
        except KeyError, ValueError:
            continue
        if container["Names"][0].lstrip("/") != container_name(chat_id):
            continue
        checkout = os.path.join(WORKSPACE_ROOT, str(chat_id))
        if os.path.islink(checkout) or not os.path.isdir(checkout):
            stop(chat_id)
            continue
        with activity_lock:
            last_active = activity.get(chat_id)
        if last_active is None:
            last_active = container["Created"]
        if now - last_active >= IDLE_SECONDS:
            stop(chat_id)


def sweep_forever() -> None:
    while True:
        try:
            sweep()
        except OSError, RuntimeError:
            pass
        time.sleep(5)


class Handler(BaseHTTPRequestHandler):
    def respond(self, code: int, payload: dict[str, str]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_workload(self) -> None:
        parts = self.path.split("/")
        if (
            len(parts) not in (3, 4)
            or parts[1] != "workloads"
            or (len(parts) == 4 and parts[3] not in ("activity", "launch"))
        ):
            self.respond(404, {"error": "Not found"})
            return
        try:
            chat_id = uuid.UUID(parts[2])
            if (
                str(chat_id) != parts[2]
                or (parts[-1] != "launch" and self.headers.get("Content-Length", "0") != "0")
            ):
                raise ValueError
        except ValueError:
            self.respond(400, {"error": "Invalid request"})
            return
        try:
            if self.command == "POST" and len(parts) == 4 and parts[3] == "launch":
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 8192:
                    raise ValueError
                result = launch(chat_id, json.loads(self.rfile.read(length)))
            elif self.command == "POST" and len(parts) == 4:
                result = heartbeat(chat_id)
            elif self.command == "POST":
                result = start(chat_id)
            elif self.command == "PUT" and len(parts) == 3:
                result = restart(chat_id)
            elif self.command == "DELETE" and len(parts) == 3:
                result = stop(chat_id)
            elif self.command == "GET" and len(parts) == 3:
                result = status(chat_id)
            else:
                self.respond(405, {"error": "Method not allowed"})
                return
            self.respond(200, result)
        except FileNotFoundError:
            self.respond(404, {"error": "Not found"})
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            logger.info("Invalid preview request: %s", error)
            self.respond(400, {"error": "Invalid preview request"})
        except RuntimeError as error:
            logger.error("Preview request failed: %s", error)
            self.respond(502, {"error": str(error) if os.environ.get("PREVIEW_DIAGNOSTICS") == "1" else "Preview controller unavailable"})

    def do_POST(self) -> None:
        self.handle_workload()

    def do_GET(self) -> None:
        self.handle_workload()

    def do_PUT(self) -> None:
        self.handle_workload()

    def do_DELETE(self) -> None:
        self.handle_workload()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    threading.Thread(target=sweep_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()

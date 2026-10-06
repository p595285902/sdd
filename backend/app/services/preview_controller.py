import http.client
import json
import logging
import os
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

SOCKET = "/var/run/docker.sock"
WORKSPACE_ROOT = "/develop-workspaces"
VOLUME = os.environ["PREVIEW_WORKSPACE_VOLUME"]
PROJECT = os.environ["PREVIEW_PROJECT"]
IMAGE = os.environ["PREVIEW_IMAGE"]
logger = logging.getLogger(__name__)
IDLE_SECONDS = 300
activity: dict[uuid.UUID, float] = {}
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
        if code in (204, 404):
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
        raise FileNotFoundError("Preview workload not found")
    return {"id": container["Id"], "state": container["State"]["Status"]}


def start(chat_id: uuid.UUID) -> dict[str, str]:
    checkout = os.path.join(WORKSPACE_ROOT, str(chat_id))
    if os.path.islink(checkout) or not os.path.isdir(checkout):
        raise FileNotFoundError("Development Chat checkout is not ready")
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


def create_workload(chat_id: uuid.UUID, socket_volume: str) -> dict[str, str]:
    configuration = {
        "Image": IMAGE,
        "Cmd": ["sh", "-c", "cp -R /checkout/. /workspace/ && exec python /controller/preview_proxy_client.py"],
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
    return status(chat_id)


def stop(chat_id: uuid.UUID) -> dict[str, str]:
    existing = inspect(chat_id)
    if existing is not None:
        if existing["State"]["Running"]:
            code, _ = docker("POST", f"/containers/{existing['Id']}/stop?t=1")
            if code not in (204, 304, 404):
                raise RuntimeError("Unable to stop preview workload")
        remove_container(existing["Id"])
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
    if status(chat_id)["state"] != "running":
        raise FileNotFoundError("Preview workload not running")
    try:
        for command in plan["setup"]:
            run_command(chat_id, command, timeout=60)
        for role in ("api", "website"):
            server = plan[role]
            run_command(chat_id, server, timeout=5, detached=True)
        for role in ("api", "website"):
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
        return {"state": "running", "website_port": str(plan["website"]["port"]), "api_port": str(plan["api"]["port"])}
    except (OSError, RuntimeError, KeyError, ValueError, TypeError) as error:
        logger.error("Preview launch failed: %s", error)
        stop(chat_id)
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
        except (ValueError, KeyError, json.JSONDecodeError):
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

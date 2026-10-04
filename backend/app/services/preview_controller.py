import http.client
import json
import os
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

SOCKET = "/var/run/docker.sock"
WORKSPACE_ROOT = "/develop-workspaces"
VOLUME = os.environ["PREVIEW_WORKSPACE_VOLUME"]
PROJECT = os.environ["PREVIEW_PROJECT"]
IMAGE = os.environ["PREVIEW_IMAGE"]
IDLE_SECONDS = 300
activity: dict[uuid.UUID, float] = {}
activity_lock = threading.Lock()


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
        return response.status, json.loads(data) if data else {}
    finally:
        connection.close()


def container_name(chat_id: uuid.UUID) -> str:
    return f"{PROJECT}-preview-{chat_id}"


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
    configuration = {
        "Image": IMAGE,
        "Cmd": ["sleep", "86400"],
        "User": "65534:65534",
        "WorkingDir": "/workspace",
        "Labels": {
            "sdd.preview.chat-id": str(chat_id),
            "sdd.preview.project": PROJECT,
        },
        "Env": ["HOME=/tmp", "PATH=/usr/local/bin:/usr/bin:/bin"],
        "HostConfig": {
            "Mounts": [
                {
                    "Type": "volume",
                    "Source": VOLUME,
                    "Target": "/workspace",
                    "ReadOnly": True,
                    "VolumeOptions": {"Subpath": str(chat_id)},
                }
            ],
            "NetworkMode": "none",
            "Privileged": False,
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Memory": 268435456,
            "NanoCpus": 1000000000,
            "PidsLimit": 64,
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=16m"},
            "AutoRemove": True,
        },
    }
    code, result = docker(
        "POST",
        f"/containers/create?name={quote(container_name(chat_id))}",
        configuration,
    )
    if code != 201:
        raise RuntimeError("Unable to create preview workload")
    code, _ = docker("POST", f"/containers/{result['Id']}/start")
    if code != 204:
        raise RuntimeError("Unable to start preview workload")
    heartbeat(chat_id)
    return status(chat_id)


def stop(chat_id: uuid.UUID) -> dict[str, str]:
    existing = inspect(chat_id)
    if existing is not None:
        if existing["State"]["Running"]:
            code, _ = docker("POST", f"/containers/{existing['Id']}/stop?t=1")
            if code not in (204, 304, 404):
                raise RuntimeError("Unable to stop preview workload")
        code, _ = docker("DELETE", f"/containers/{existing['Id']}?force=true")
        if code not in (204, 404):
            raise RuntimeError("Unable to remove preview workload")
    with activity_lock:
        activity.pop(chat_id, None)
    return {"state": "stopped"}


def restart(chat_id: uuid.UUID) -> dict[str, str]:
    stop(chat_id)
    return start(chat_id)


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
            or (len(parts) == 4 and parts[3] != "activity")
        ):
            self.respond(404, {"error": "Not found"})
            return
        try:
            chat_id = uuid.UUID(parts[2])
            if (
                str(chat_id) != parts[2]
                or self.headers.get("Content-Length", "0") != "0"
            ):
                raise ValueError
        except ValueError:
            self.respond(400, {"error": "Invalid request"})
            return
        try:
            if self.command == "POST" and len(parts) == 4:
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
        except RuntimeError:
            self.respond(502, {"error": "Preview controller unavailable"})

    def do_POST(self) -> None:
        self.handle_workload()

    def do_GET(self) -> None:
        self.handle_workload()

    def do_PUT(self) -> None:
        self.handle_workload()

    def do_DELETE(self) -> None:
        self.handle_workload()


if __name__ == "__main__":
    threading.Thread(target=sweep_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()

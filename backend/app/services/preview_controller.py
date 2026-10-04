import http.client
import json
import os
import socket
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

SOCKET = "/var/run/docker.sock"
WORKSPACE_ROOT = "/develop-workspaces"
VOLUME = os.environ["PREVIEW_WORKSPACE_VOLUME"]
PROJECT = os.environ["PREVIEW_PROJECT"]
IMAGE = os.environ["PREVIEW_IMAGE"]


class DockerConnection(http.client.HTTPConnection):
    def __init__(self) -> None:
        super().__init__("localhost", timeout=10)

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SOCKET)


def docker(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
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
    if labels.get("sdd.preview.chat-id") != str(chat_id) or labels.get(
        "sdd.preview.project"
    ) != PROJECT:
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
        return status(chat_id)
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
        "POST", f"/containers/create?name={quote(container_name(chat_id))}", configuration
    )
    if code != 201:
        raise RuntimeError("Unable to create preview workload")
    code, _ = docker("POST", f"/containers/{result['Id']}/start")
    if code != 204:
        raise RuntimeError("Unable to start preview workload")
    return status(chat_id)


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
        if len(parts) != 3 or parts[1] != "workloads":
            self.respond(404, {"error": "Not found"})
            return
        try:
            chat_id = uuid.UUID(parts[2])
            if str(chat_id) != parts[2] or self.headers.get("Content-Length", "0") != "0":
                raise ValueError
        except ValueError:
            self.respond(400, {"error": "Invalid request"})
            return
        try:
            result = start(chat_id) if self.command == "POST" else status(chat_id)
            self.respond(200, result)
        except FileNotFoundError:
            self.respond(404, {"error": "Not found"})
        except RuntimeError:
            self.respond(502, {"error": "Preview controller unavailable"})

    def do_POST(self) -> None:
        self.handle_workload()

    def do_GET(self) -> None:
        self.handle_workload()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()

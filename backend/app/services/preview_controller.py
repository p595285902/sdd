import base64
import hmac
import http.client
import io
import json
import logging
import os
import re
import select
import socket
import tarfile
import threading
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

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


class ResetControlError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


reset_deadline = threading.local()


def checked_docker_response(method: str, path: str) -> dict | list:
    code, result = docker(method, path)
    if code != 200:
        raise RuntimeError("Unable to verify acceptance Docker ownership")
    return result


def checked_docker(method: str, path: str) -> dict:
    result = checked_docker_response(method, path)
    if not isinstance(result, dict):
        raise RuntimeError("Acceptance Docker inspection is not an object")
    return result


def docker_entries(value: object) -> list[dict]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise RuntimeError("Acceptance Docker resource listing is malformed")
    return value


def checked_docker_list(method: str, path: str) -> list[dict]:
    return docker_entries(checked_docker_response(method, path))


def container_environment(container: dict) -> dict[str, str]:
    return dict(value.split("=", 1) for value in container["Config"].get("Env", []) if "=" in value)


def compose_owned(resource: dict, kind: str, name: str) -> None:
    resource_labels = resource.get("Labels") or {}
    if (resource_labels.get("com.docker.compose.project") != PROJECT
            or resource_labels.get(f"com.docker.compose.{kind}") != name):
        raise RuntimeError("Acceptance resource is not owned by this Compose project")


COMPOSE_IMAGE_LABELS = {f"com.docker.compose.{key}" for key in ("project", "service", "version")}
COMPOSE_INSTANCE_LABELS = {f"com.docker.compose.{key}" for key in ("config-hash", "container-number", "oneoff")}


def compose_instance(resource_labels: dict) -> bool:
    return all(resource_labels.get(key) for key in COMPOSE_INSTANCE_LABELS)


def acceptance_ownership() -> dict:
    """Attest actual Engine objects, not caller-selected scopes or names alone."""
    filters = quote(json.dumps({"label": [f"com.docker.compose.project={PROJECT}"]}))
    containers = checked_docker_list("GET", f"/containers/json?all=1&filters={filters}")
    services = {}
    for service in ("backend", "db", "preview-controller"):
        # Compose build metadata is inherited by preview containers from IMAGE.
        # Only instance markers identify Compose-managed service containers.
        matches = [item for item in containers
                   if (item.get("Labels") or {}).get("com.docker.compose.service") == service
                   and any(key in (item.get("Labels") or {}) for key in COMPOSE_INSTANCE_LABELS)]
        if len(matches) != 1:
            raise RuntimeError("Acceptance main service ownership is ambiguous")
        item = checked_docker("GET", f"/containers/{matches[0]['Id']}/json")
        compose_owned({"Labels": item["Config"].get("Labels")}, "service", service)
        instance_labels = item["Config"].get("Labels") or {}
        if (not compose_instance(instance_labels)
                or instance_labels["com.docker.compose.container-number"] != "1"
                or instance_labels["com.docker.compose.oneoff"].lower() != "false"):
            raise RuntimeError("Acceptance main service is not a verified Compose instance")
        if (instance_labels.get("sdd.preview.chat-id")
                or not item["State"].get("Running")
                or item["State"].get("Health", {}).get("Status", "healthy") != "healthy"):
            raise RuntimeError("Acceptance main service is not healthy and preserved")
        services[service] = item
    backend, database, controller = (services[name] for name in ("backend", "db", "preview-controller"))
    if controller["Config"].get("Hostname") != socket.gethostname():
        raise RuntimeError("Acceptance controller is not this process's Docker container")
    backend_env = container_environment(backend)
    controller_env = container_environment(controller)
    for env in (backend_env, controller_env):
        if (env.get("DEVELOP_ACCEPTANCE_RESET_ENABLED", "").lower() != "true"
                or env.get("ACCEPTANCE_RUN_ID") != PROJECT
                or not hmac.compare_digest(env.get("ACCEPTANCE_RESET_TOKEN", ""), acceptance_reset.token)):
            raise RuntimeError("Acceptance service run credentials do not match")
    if (backend_env.get("DEVELOP_ACCEPTANCE_MODE", "").lower() != "true"
            or backend_env.get("DEVELOP_WORKSPACE_ROOT") != WORKSPACE_ROOT
            or controller_env.get("PREVIEW_PROJECT") != PROJECT
            or controller_env.get("PREVIEW_WORKSPACE_VOLUME") != VOLUME):
        raise RuntimeError("Acceptance service configuration is not confined")
    if any(backend.get("HostConfig", {}).get(key) for key in ("ExtraHosts", "Dns", "DnsSearch", "DnsOptions")):
        raise RuntimeError("Acceptance database DNS must use the inspected Compose topology")
    database_env = container_environment(database)
    url = urlsplit(backend_env.get("DATABASE_URL", ""))
    if (url.scheme != "postgresql" or url.hostname != "db" or url.port != 5432
            or url.path != "/app" or url.query or url.fragment
            or database_env.get("POSTGRES_DB") != "app"):
        raise RuntimeError("Acceptance database configuration does not address the owned database")
    if (unquote(url.username or "") != database_env.get("POSTGRES_USER", "postgres")
            or not hmac.compare_digest(unquote(url.password or ""), database_env.get("POSTGRES_PASSWORD", ""))):
        raise RuntimeError("Acceptance database credentials do not match the owned database")
    if any(hmac.compare_digest(acceptance_reset.token, value) for value in (
        backend_env.get("SECRET_KEY", ""), database_env.get("POSTGRES_PASSWORD", ""),
        backend_env.get("FIRST_SUPERUSER_PASSWORD", ""), backend_env.get("DEMO_GITHUB_TOKEN", ""),
    )):
        raise RuntimeError("Acceptance reset credential is not independent")

    def mount_volume(container: dict, destination: str, writable: bool, key: str | None = None) -> dict:
        mounts = [mount for mount in container.get("Mounts", []) if mount.get("Destination") == destination]
        if len(mounts) != 1 or mounts[0].get("Type") != "volume" or mounts[0].get("RW") is not writable:
            raise RuntimeError("Acceptance storage is not an owned named volume")
        name = mounts[0].get("Name", "")
        volume = checked_docker("GET", f"/volumes/{quote(name, safe='')}")
        volume_key = key or (volume.get("Labels") or {}).get("com.docker.compose.volume")
        if not volume_key or name != f"{PROJECT}_{volume_key}":
            raise RuntimeError("Acceptance named volume identity does not match Compose ownership")
        compose_owned(volume, "volume", volume_key)
        if volume.get("Driver") != "local" or volume.get("Options"):
            raise RuntimeError("Acceptance storage must not redirect to external filesystem roots")
        return {"destination": destination, "volume": name, "compose_project": PROJECT,
                "created_at": volume.get("CreatedAt")}

    workspace = mount_volume(backend, WORKSPACE_ROOT, True, "sdd-develop-workspaces")
    controller_workspace = mount_volume(controller, WORKSPACE_ROOT, False, "sdd-develop-workspaces")
    if workspace["volume"] != VOLUME or controller_workspace["volume"] != VOLUME:
        raise RuntimeError("Acceptance workspace volume does not match the owned mounts")
    agent = mount_volume(backend, "/acceptance-agent-state", True, "sdd-acceptance-agent-state")
    data = mount_volume(database, "/var/lib/postgresql", True, "sdd-db-data")
    networks = {}
    for key in ("default", "preview-control"):
        name = f"{PROJECT}_{key}"
        network = checked_docker("GET", f"/networks/{quote(name, safe='')}")
        compose_owned(network, "network", key)
        if network.get("Name") != name or (key == "preview-control" and not network.get("Internal")):
            raise RuntimeError("Acceptance control network is not confined")
        networks[key] = network
        for container_id in network.get("Containers", {}):
            attached = checked_docker("GET", f"/containers/{container_id}/json")
            attached_labels = attached["Config"].get("Labels") or {}
            if (attached_labels.get("com.docker.compose.project") != PROJECT
                    or not compose_instance(attached_labels) or attached_labels.get("sdd.preview.chat-id")):
                raise RuntimeError("Unrelated or non-Compose container is attached to an acceptance network")
            aliases = attached["NetworkSettings"]["Networks"][name].get("Aliases") or []
            if "db" in aliases and attached["Id"] != database["Id"]:
                raise RuntimeError("Acceptance database network alias is ambiguous")
    for service, keys in (("backend", ("default", "preview-control")), ("db", ("default",)),
                          ("preview-controller", ("preview-control",))):
        attached = services[service]["NetworkSettings"]["Networks"]
        if set(attached) != {networks[key]["Name"] for key in keys}:
            raise RuntimeError("Acceptance service networks differ from the owned topology")
        for key in keys:
            network = networks[key]
            if (attached[network["Name"]].get("NetworkID") != network["Id"]
                    or services[service]["Id"] not in network.get("Containers", {})):
                raise RuntimeError("Acceptance service is not attached to the inspected network")
    if "db" not in (database["NetworkSettings"]["Networks"][networks["default"]["Name"]].get("Aliases") or []):
        raise RuntimeError("Acceptance db host does not resolve to the owned db service")
    if controller.get("HostConfig", {}).get("PortBindings") or any(
        controller.get("NetworkSettings", {}).get("Ports", {}).values()
    ):
        raise RuntimeError("Acceptance controller controls must remain unpublished")
    return {
        "verified": True, "project": PROJECT,
        "database": {"service": "db", "database": "app", "compose_project": PROJECT, "volume": data["volume"]},
        "workspace": workspace, "agent": agent,
        "services": {"backend": backend["Id"], "db": database["Id"], "preview_controller": controller["Id"]},
        "identities": {name: {"id": item["Id"], "started_at": item["State"].get("StartedAt"),
                              "restart_count": item.get("RestartCount", 0)} for name, item in services.items()},
        "networks": {key: {"id": item["Id"], "name": item["Name"]} for key, item in networks.items()},
        "runtime_image": {"id": controller["Image"], "build_labels": {
            key: value for key, value in (controller["Config"].get("Labels") or {}).items()
            if key in COMPOSE_IMAGE_LABELS}},
    }


def scenario_resources(ownership: dict) -> dict[str, list[dict]]:
    """Discover orphans from Engine labels, never from chat rows or routing maps."""
    filters = quote(json.dumps({"label": [f"sdd.preview.project={PROJECT}"]}))
    resources = {}
    for kind, path in (("containers", f"/containers/json?all=1&filters={filters}"),
                       ("networks", f"/networks?filters={filters}"),
                       ("volumes", f"/volumes?filters={filters}"),
                       ("images", f"/images/json?all=1&filters={filters}")):
        if kind == "volumes":
            result = checked_docker("GET", path)
            entries = docker_entries(result.get("Volumes") if result.get("Volumes") is not None else [])
        else:
            entries = checked_docker_list("GET", path)
        resources[kind] = []
        for summary in entries:
            identifier = summary["Name"] if kind == "volumes" else summary["Id"]
            path = f"/{kind}/{quote(identifier, safe='')}" + ("/json" if kind in ("containers", "images") else "")
            entry = checked_docker("GET", path)
            resource_labels = (entry.get("Config", {}).get("Labels") if kind in ("containers", "images") else entry.get("Labels")) or {}
            if resource_labels.get("sdd.preview.project") != PROJECT:
                raise RuntimeError("Preview resource discovery ownership changed")
            chat = resource_labels.get("sdd.preview.chat-id")
            if kind == "networks" and not chat and entry.get("Name") == outbound_network():
                if any(key.startswith("com.docker.compose.") for key in resource_labels) or entry.get("Internal"):
                    raise RuntimeError("Shared preview egress ownership is ambiguous")
                continue  # The one explicitly preserved project-shared egress resource.
            try:
                if str(uuid.UUID(chat)) != chat:
                    raise ValueError
            except (ValueError, TypeError, AttributeError):
                raise RuntimeError("Preview resource has no canonical scenario ownership") from None
            compose_labels = {key: value for key, value in resource_labels.items()
                              if key.startswith("com.docker.compose.")}
            if compose_labels:
                # Only the exact build metadata inherited from our pinned runtime
                # may remain. Instance/config/network/volume labels always refuse
                # deletion, even when a caller also supplies a valid chat UUID.
                if (kind not in ("containers", "images")
                        or compose_labels != ownership["runtime_image"]["build_labels"]
                        or (kind == "containers" and entry.get("Image") != ownership["runtime_image"]["id"])):
                    raise RuntimeError("Refusing to remove Compose-owned preview resources")
            if kind != "images":
                name = entry.get("Name", "").lstrip("/")
                prefix = container_name(uuid.UUID(chat))
                if name != prefix and not name.startswith(prefix + "-"):
                    raise RuntimeError("Scenario resource is outside the owned preview namespace")
            if kind == "containers":
                for mount in entry.get("Mounts", []):
                    if mount.get("Name") in (ownership["workspace"]["volume"], ownership["agent"]["volume"],
                                              ownership["database"]["volume"]):
                        if (mount.get("Name") != ownership["workspace"]["volume"]
                                or mount.get("Destination") != "/checkout" or mount.get("RW") is not False):
                            raise RuntimeError("Refusing to remove a workload with long-lived writable storage")
            if identifier == ownership["runtime_image"]["id"] or identifier in ownership["services"].values() or identifier in (
                ownership["workspace"]["volume"], ownership["agent"]["volume"], ownership["database"]["volume"],
            ) or identifier in {item["id"] for item in ownership["networks"].values()}:
                raise RuntimeError("Refusing to remove a long-lived acceptance resource")
            if kind == "images" and any(
                tag != "<none>:<none>" and not tag.startswith(f"{PROJECT}-preview-{chat}-")
                for tag in entry.get("RepoTags") or []
            ):
                raise RuntimeError("Scenario image has a shared or unrelated tag")
            resources[kind].append(entry)
    owned_containers = {item["Id"] for item in resources["containers"]}
    for network in resources["networks"]:
        if not network.get("Internal") or not set(network.get("Containers", {})).issubset(owned_containers):
            raise RuntimeError("Scenario network is shared with an unowned workload")
    return resources


class AcceptanceReset:
    def __init__(self) -> None:
        self.enabled = os.environ.get("DEVELOP_ACCEPTANCE_RESET_ENABLED", "false").lower() == "true"
        self.run_id = os.environ.get("ACCEPTANCE_RUN_ID", "")
        self.token = os.environ.get("ACCEPTANCE_RESET_TOKEN", "")
        self.timeout = float(os.environ.get("ACCEPTANCE_RESET_TIMEOUT_SECONDS", "60"))
        self.boot_id = str(uuid.uuid4())
        self.condition = threading.Condition()
        self.operation_lock = threading.Lock()
        self.cancel = threading.Event()
        self.active = {"handler": 0, "maintenance": 0, "control": 0}
        self.generation = 0
        self.phase = "admitting"
        self.baseline_verified = False
        self.dirty = True
        self.work_serial = 0
        self.completed_serial = -1
        self.reset_id = None
        self.used_ids: set[str] = set()
        self.expected_generation = None
        self.operation_kind = "reset"
        self.deadline = None
        self.ownership = None

    def authenticate(self, headers) -> None:
        if not self.enabled:
            raise ResetControlError(404, "Not found")
        if (not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", self.token)
                or len(set(self.token)) < 8 or self.run_id != PROJECT
                or not 0 < self.timeout <= 60):
            raise ResetControlError(503, "Acceptance reset configuration is invalid")
        if (not hmac.compare_digest(headers.get("Authorization", "").encode(), f"Bearer {self.token}".encode())
                or not hmac.compare_digest(headers.get("X-Acceptance-Run", "").encode(), self.run_id.encode())):
            raise ResetControlError(403, "Acceptance reset authentication rejected")

    @contextmanager
    def work(self, kind: str):
        if not self.enabled:
            yield
            return
        with self.condition:
            if self.phase not in ("admitting", "ready"):
                raise ResetControlError(503, "Acceptance workload admissions are closed")
            self.active[kind] += 1
            if kind == "handler":
                self.work_serial += 1
                self.dirty = True
                self.baseline_verified = False
        try:
            yield
        finally:
            with self.condition:
                self.active[kind] -= 1
                self.condition.notify_all()

    def state(self) -> dict:
        with self.condition:
            return {"run_id": self.run_id, "generation": self.generation, "phase": self.phase,
                    "boot_id": self.boot_id, "baseline_verified": self.baseline_verified,
                    "active_work": sum(self.active.values()), "ownership": self.ownership or {"verified": False},
                    "reset_id": self.reset_id, "expected_generation": self.expected_generation,
                    "operation": self.operation_kind, "dirty": self.dirty}

    def bounded(self, callback, deadline: float):
        """Return by the total deadline even if an Engine read cannot be interrupted.

        A timed-out worker stays tracked and admissions stay failed/closed. It can
        never publish success or overlap a later generation.
        """
        done = threading.Event()
        result = []
        with self.condition:
            self.active["control"] += 1
        def run():
            reset_deadline.value = deadline
            try:
                result.append((True, callback()))
            except Exception as error:
                result.append((False, error))
            finally:
                with self.condition:
                    self.active["control"] -= 1
                    self.condition.notify_all()
                done.set()
        threading.Thread(target=run, daemon=True).start()
        if not done.wait(max(0, deadline - time.monotonic())):
            raise RuntimeError("Acceptance reset deadline exceeded")
        if not result[0][0]:
            raise result[0][1]
        if time.monotonic() >= deadline:
            raise RuntimeError("Acceptance reset deadline exceeded")
        return result[0][1]

    def verify_ownership(self, deadline: float) -> dict:
        verified = self.bounded(acceptance_ownership, deadline)
        with self.condition:
            if self.ownership is not None and self.ownership != verified:
                raise RuntimeError("Acceptance long-lived resource identities changed")
            self.ownership = verified
        return verified

    def fail(self) -> None:
        with self.condition:
            self.phase = "failed"
            self.baseline_verified = False
            self.cancel.set()
            self.condition.notify_all()

    def diagnostic_state(self) -> dict:
        try:
            self.verify_ownership(time.monotonic() + self.timeout)
        except Exception:
            self.fail()
            raise ResetControlError(503, "Acceptance ownership verification failed") from None
        return self.state()

    def validate_request(self, action: str, payload: dict) -> None:
        keys = {"run_id", "reset_id", "expected_generation", "timeout_seconds"}
        optional = {"operation"} if action == "quiesce" else set()
        if action == "resume":
            keys |= {"generation", "baseline_verified"}
        if not isinstance(payload, dict) or not keys.issubset(payload) or set(payload) - keys - optional:
            raise ResetControlError(400, "Invalid acceptance control request")
        if payload["run_id"] != self.run_id:
            raise ResetControlError(409, "Acceptance run identity mismatch")
        if (not isinstance(payload["reset_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", payload["reset_id"])
                or type(payload["expected_generation"]) is not int or payload["expected_generation"] < 0
                or type(payload["timeout_seconds"]) not in (int, float)
                or not 0 < payload["timeout_seconds"] <= self.timeout
                or payload.get("operation", "reset") not in ("reset", "configuration")):
            raise ResetControlError(400, "Invalid acceptance control request")
        if action == "resume" and (type(payload["generation"]) is not int or payload["baseline_verified"] is not True):
            raise ResetControlError(400, "Verified backend baseline is required")

    def control(self, action: str, payload: dict) -> dict:
        self.validate_request(action, payload)
        if not self.operation_lock.acquire(blocking=False):
            raise ResetControlError(409, "Acceptance control operation already in progress")
        try:
            with self.condition:
                same = payload["reset_id"] == self.reset_id and payload["expected_generation"] == self.expected_generation
                if self.phase == "failed":
                    raise ResetControlError(503, "Acceptance reset is failed and closed")
                if action == "resume" and same:
                    expected_generation = self.expected_generation
                    if expected_generation is None:
                        raise ResetControlError(409, "Acceptance generation is not initialized")
                    wanted = expected_generation + (self.operation_kind == "reset")
                    if payload["generation"] != wanted:
                        raise ResetControlError(409, "Acceptance generation mismatch")
                if same and self.phase == "ready":
                    if self.completed_serial != self.work_serial:
                        raise ResetControlError(409, "Stale acceptance control retry")
                    if action == "quiesce" and payload.get("operation", "reset") != self.operation_kind:
                        raise ResetControlError(409, "Acceptance operation mismatch")
                    if action == "reset" and self.operation_kind != "reset":
                        raise ResetControlError(409, "Configuration cannot clean scenario state")
                    return self.state()
                if action == "quiesce":
                    if same:
                        if payload.get("operation", "reset") != self.operation_kind:
                            raise ResetControlError(409, "Acceptance operation mismatch")
                        return self.state()
                    if (self.phase not in ("admitting", "ready") or payload["expected_generation"] != self.generation
                            or payload["reset_id"] in self.used_ids or len(self.used_ids) >= 1024):
                        raise ResetControlError(409, "Acceptance generation or reset conflict")
                    self.reset_id = payload["reset_id"]
                    self.used_ids.add(self.reset_id)
                    self.expected_generation = payload["expected_generation"]
                    self.operation_kind = payload.get("operation", "reset")
                    self.deadline = time.monotonic() + payload["timeout_seconds"]
                    self.phase = "quiescing"
                    self.baseline_verified = False
                    self.cancel.set()
                elif not same:
                    raise ResetControlError(409, "Acceptance generation or reset conflict")
                elif action == "reset" and (self.operation_kind != "reset" or self.phase not in ("quiesced", "preview_reset")):
                    raise ResetControlError(409, "Acceptance reset requires reset quiescence")
                elif action == "resume" and self.phase != ("preview_reset" if self.operation_kind == "reset" else "quiesced"):
                    raise ResetControlError(409, "Acceptance resume requires completed verification")
                if action == "reset" and self.phase == "preview_reset":
                    return self.state()
                operation_deadline, operation_id = self.deadline, self.reset_id
                if operation_deadline is None or operation_id is None:
                    self.fail()
                    raise ResetControlError(503, "Acceptance operation is not initialized; admissions remain closed")
                deadline = min(operation_deadline, time.monotonic() + payload["timeout_seconds"])
            try:
                ownership = self.verify_ownership(deadline)
                if action == "quiesce":
                    with self.condition:
                        while self.active["handler"] or self.active["maintenance"]:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise RuntimeError("Acceptance drain deadline exceeded")
                            self.condition.wait(remaining)
                        if self.phase == "failed":
                            raise RuntimeError("Acceptance ownership verification failed")
                        self.phase = "quiesced"
                elif action == "reset":
                    with self.condition:
                        self.phase = "cleaning_previews"
                    self.bounded(lambda: self.clean(ownership), deadline)
                    self.verify_ownership(deadline)
                    with self.condition:
                        if self.phase == "failed":
                            raise RuntimeError("Acceptance ownership verification failed")
                        self.phase = "preview_reset"
                else:
                    if self.operation_kind == "reset":
                        resources = self.bounded(lambda: scenario_resources(ownership), deadline)
                        if any(resources.values()):
                            raise RuntimeError("Acceptance preview baseline is not empty")
                        with activity_lock:
                            if activity or ready_services or failed_services:
                                raise RuntimeError("Acceptance controller maps are not empty")
                    with self.condition:
                        if (self.phase == "failed" or time.monotonic() >= deadline
                                or self.active["handler"] or self.active["maintenance"]):
                            raise RuntimeError("Acceptance resume is not quiescent")
                        if payload["generation"] != self.generation:
                            self.used_ids = {operation_id}
                        self.generation = payload["generation"]
                        self.phase = "ready"
                        self.baseline_verified = self.operation_kind == "reset"
                        self.dirty = not self.baseline_verified
                        self.completed_serial = self.work_serial
                        self.cancel.clear()
            except Exception:
                self.fail()
                raise ResetControlError(503, f"Acceptance {action} failed; admissions remain closed") from None
            return self.state()
        finally:
            self.operation_lock.release()

    def clean(self, ownership: dict) -> None:
        resources = scenario_resources(ownership)  # Validate the entire deletion scope first.
        for kind in ("containers", "networks", "volumes", "images"):
            for item in resources[kind]:
                if time.monotonic() >= reset_deadline.value:
                    raise RuntimeError("Acceptance cleanup deadline exceeded")
                identifier = item["Name"] if kind == "volumes" else item["Id"]
                path = f"/{kind}/{quote(identifier, safe='')}"
                if kind == "images":
                    # Remove only attested chat tags; deleting a multiply tagged
                    # image ID would require unsafe force or otherwise fail.
                    for tag in item.get("RepoTags") or []:
                        if tag != "<none>:<none>":
                            remove_resource(f"/images/{quote(tag, safe='')}")
                    remove_resource(path)
                else:
                    remove_resource(path + "?force=true" if kind == "containers" else path)
        if any(scenario_resources(ownership).values()):
            raise RuntimeError("Acceptance scenario resources remain")
        with self.condition:
            if (self.phase != "cleaning_previews" or time.monotonic() >= reset_deadline.value
                    or self.active["handler"] or self.active["maintenance"]):
                raise RuntimeError("Acceptance map cleanup is not quiescent")
            with activity_lock:
                activity.clear()
                ready_services.clear()
                failed_services.clear()


acceptance_reset = AcceptanceReset()


def tracked_maintenance(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with acceptance_reset.work("maintenance"):
            return function(*args, **kwargs)
    return wrapped


class DockerConnection(http.client.HTTPConnection):
    def __init__(self) -> None:
        deadline = getattr(reset_deadline, "value", None)
        remaining = 10 if deadline is None else min(10, deadline - time.monotonic())
        if remaining <= 0:
            raise RuntimeError("Acceptance Docker operation deadline exceeded")
        super().__init__("localhost", timeout=remaining)

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
                details["api_host"] = name
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


def browser_resource(chat_id: uuid.UUID, path: str, requested_port: str | None = None,
                     method: str = "GET", body: bytes = b"", content_type: str = "",
                     cookie: str = "") -> dict:
    current = status(chat_id)
    if current.get("state") != "running" or "initial_port" not in current:
        raise FileNotFoundError("Preview is not ready")
    parsed = urlsplit(path)
    if not path.startswith("/") or path.startswith("//") or parsed.scheme or parsed.netloc or urlsplit(path.lstrip("/")).scheme or len(path) > 2000:
        raise ValueError("Invalid preview path")
    port = requested_port or current["initial_port"]
    if port not in (current.get("website_port"), current.get("api_port"), current["initial_port"]):
        raise ValueError("Unregistered preview port")
    if method not in ("GET", "POST") or len(body) > 32768 or len(content_type) > 200 or len(cookie) > 8192:
        raise ValueError("Invalid preview request")
    host = current.get("api_host", "127.0.0.1") if port == current.get("api_port") else "127.0.0.1"
    script = (
        "import base64,json,sys,urllib.request,urllib.error\n"
        "url='http://'+sys.argv[1]+':'+sys.argv[2]+sys.argv[3]\n"
        "class NoRedirect(urllib.request.HTTPRedirectHandler):\n"
        " def redirect_request(self,request,fp,code,msg,headers,newurl): return None\n"
        "headers={'Content-Type':sys.argv[6]} if sys.argv[6] else {}\n"
        "if sys.argv[7]: headers['Cookie']=sys.argv[7]\n"
        "request=urllib.request.Request(url,data=base64.b64decode(sys.argv[5]) if sys.argv[4]=='POST' else None,headers=headers,method=sys.argv[4])\n"
        "try:\n response=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open(request,timeout=5)\n"
        "except urllib.error.HTTPError as error: response=error\n"
        "with response:\n"
        " body=response.read(2097153)\n"
        " assert len(body)<=2097152\n"
        " print(json.dumps({'status':response.status,'location':response.headers.get('Location',''),'content_type':response.headers.get('Content-Type','application/octet-stream'),'cookies':response.headers.get_all('Set-Cookie',[]),"
        "'body':base64.b64encode(body).decode()}))\n"
    )
    node_script = (
        "(async()=>{const response=await fetch('http://'+process.argv[1]+':'+process.argv[2]+process.argv[3],"
        "{method:process.argv[4],body:process.argv[4]==='POST'?Buffer.from(process.argv[5],'base64'):undefined,headers:{...(process.argv[6]?{'content-type':process.argv[6]}:{}),...(process.argv[7]?{'cookie':process.argv[7]}:{})},redirect:'manual',signal:AbortSignal.timeout(5000)});"
        "const reader=response.body?.getReader(),parts=[];let size=0;"
        "while(reader){const {done,value}=await reader.read();if(done)break;size+=value.length;"
        "if(size>2097152)throw Error('Resource too large');parts.push(value)}"
        "console.log(JSON.stringify({status:response.status,location:response.headers.get('location')||'',content_type:response.headers.get('content-type')||"
        "'application/octet-stream',cookies:response.headers.getSetCookie(),body:Buffer.concat(parts).toString('base64')}))})().catch(()=>process.exit(1))"
    )
    encoded_body = base64.b64encode(body).decode()
    for command in (["python", "-c", script, host, port, path, method, encoded_body, content_type, cookie],
                    ["node", "-e", node_script, host, port, path, method, encoded_body, content_type, cookie]):
        code, result = docker("POST", f"/containers/{container_name(chat_id)}/exec", {
            "Cmd": command, "User": "65534:65534", "AttachStdout": True, "AttachStderr": False,
        })
        if code != 201:
            continue
        connection = DockerConnection()
        try:
            connection.request("POST", f"/v1.47/exec/{result['Id']}/start", body=b'{"Detach":false,"Tty":true}',
                               headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            body = response.read(3 * 1024 * 1024)
            if response.status != 200 or len(body) >= 3 * 1024 * 1024:
                raise RuntimeError("Preview resource exceeded limits")
        finally:
            connection.close()
        code, state = docker("GET", f"/exec/{result['Id']}/json")
        if code == 200 and state["ExitCode"] == 0:
            return json.loads(body)
    raise RuntimeError("Unable to fetch preview resource")


def browser_socket(handler: BaseHTTPRequestHandler, chat_id: uuid.UUID, path: str, port: str) -> None:
    current = status(chat_id)
    if current.get("state") != "running" or not port.isdigit() or port not in (
        current.get("website_port"), current.get("api_port"), current.get("initial_port")
    ):
        raise ValueError("Unregistered preview port")
    parsed = urlsplit(path)
    if not path.startswith("/") or path.startswith("//") or parsed.scheme or parsed.netloc or urlsplit(path.lstrip("/")).scheme or len(path) > 2000:
        raise ValueError("Invalid preview path")
    key = handler.headers.get("Sec-WebSocket-Key", "")
    if len(key) != 24 or handler.headers.get("Sec-WebSocket-Version") != "13":
        raise ValueError("Invalid WebSocket handshake")
    offered = handler.headers.get("Sec-WebSocket-Protocol", "")
    protocols = [value.strip() for value in offered.split(",")] if offered else []
    if len(offered) > 256 or len(protocols) > 8 or any(
        not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", value) for value in protocols
    ):
        raise ValueError("Invalid WebSocket protocols")
    host = current.get("api_host", "127.0.0.1") if port == current.get("api_port") else "127.0.0.1"
    script = (
        "import os,select,socket,sys,tty\n"
        "tty.setraw(0)\n"
        "upstream=socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=5)\n"
        "upstream.settimeout(None)\n"
        "os.write(1,b'READY\\n')\n"
        "while True:\n"
        " readable,_,_=select.select([0,upstream],[],[],30)\n"
        " for source in readable:\n"
        "  data=os.read(0,65536) if source==0 else upstream.recv(65536)\n"
        "  if not data: sys.exit(0)\n"
        "  upstream.sendall(data) if source==0 else os.write(1,data)\n"
    )
    code, result = docker("POST", f"/containers/{container_name(chat_id)}/exec", {
        "Cmd": ["python", "-u", "-c", script, host, port], "User": "65534:65534",
        "AttachStdin": True, "AttachStdout": True, "AttachStderr": False, "Tty": True,
    })
    if code != 201:
        raise RuntimeError("Unable to open private WebSocket")
    connection = DockerConnection()
    try:
        connection.request("POST", f"/v1.47/exec/{result['Id']}/start",
                           body=b'{"Detach":false,"Tty":true}', headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError("Unable to attach private WebSocket")
        upstream_socket = connection.sock or response.fp.raw._sock
        upstream_socket.settimeout(10)
        if response.read(6) != b"READY\n":
            raise RuntimeError("Private WebSocket exec did not start")
        handshake = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                     f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n")
        if protocols:
            handshake += f"Sec-WebSocket-Protocol: {', '.join(protocols)}\r\n"
        handshake += "\r\n"
        upstream_socket.sendall(handshake.encode("ascii"))
        upstream_headers = bytearray()
        while b"\r\n\r\n" not in upstream_headers and len(upstream_headers) < 8192:
            fragment = response.read(1)
            if not fragment:
                raise RuntimeError("Private WebSocket closed during handshake")
            upstream_headers.extend(fragment)
        if not upstream_headers.startswith((b"HTTP/1.1 101 ", b"HTTP/1.0 101 ")):
            raise RuntimeError("Private WebSocket handshake failed")
        if upstream_headers.startswith(b"HTTP/1.0"):
            upstream_headers[:8] = b"HTTP/1.1"
        handler.connection.sendall(upstream_headers)
        upstream_socket.settimeout(0.05)
        try:
            buffered = response.fp.peek(1)
            if buffered:
                handler.connection.sendall(response.fp.read1(len(buffered)))
        except TimeoutError:
            pass
        upstream_socket.settimeout(None)
        handler.connection.settimeout(None)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if acceptance_reset.enabled and acceptance_reset.cancel.is_set():
                return
            readable, _, _ = select.select([handler.connection, upstream_socket], [], [],
                                           0.1 if acceptance_reset.enabled else 10)
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                (upstream_socket if source is handler.connection else handler.connection).sendall(data)
    finally:
        connection.close()


@tracked_maintenance
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
    def respond(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_acceptance_control(self) -> None:
        actions = {"/testing/acceptance/" + action: action for action in ("state", "quiesce", "reset", "resume")}
        action = actions.get(self.path)
        if action is None or self.command != ("GET" if action == "state" else "POST"):
            self.respond(404, {"error": "Not found"})
            return
        try:
            acceptance_reset.authenticate(self.headers)  # Before reading input or changing admissions.
            length = int(self.headers.get("Content-Length", "0"))
            if action == "state":
                if length != 0:
                    raise ResetControlError(400, "Invalid acceptance control request")
                result = acceptance_reset.diagnostic_state()
            else:
                if not 0 < length <= 4096 or self.headers.get("Transfer-Encoding"):
                    raise ResetControlError(400, "Invalid acceptance control request")
                self.connection.settimeout(10)
                def unique_object(pairs):
                    value = {}
                    for key, item in pairs:
                        if key in value:
                            raise ValueError("Duplicate request key")
                        value[key] = item
                    return value
                payload = json.loads(self.rfile.read(length), object_pairs_hook=unique_object)
                result = acceptance_reset.control(action, payload)
            self.respond(200, result)
        except ResetControlError as error:
            self.respond(error.code, {"error": str(error), "phase": acceptance_reset.phase})
        except (ValueError, TypeError, TimeoutError):
            self.respond(400, {"error": "Invalid acceptance control request"})

    def handle_workload(self) -> None:
        if self.path.startswith("/testing/acceptance/"):
            self.handle_acceptance_control()
            return
        if self.command == "GET" and self.path == "/health":
            self.respond(200, {"status": "ok"})
            return
        # Status is an Engine read; browser GET/upgrade executes inside a workload
        # and therefore joins the same barrier as every mutating HTTP handler.
        diagnostic = self.command == "GET" and bool(re.fullmatch(r"/workloads/[0-9a-f-]{36}", self.path))
        try:
            if diagnostic:
                self._handle_workload()
            else:
                with acceptance_reset.work("handler"):
                    self._handle_workload()
        except ResetControlError as error:
            self.respond(error.code, {"error": str(error)})

    def _handle_workload(self) -> None:
        if self.command in ("GET", "POST") and "/browser?" in self.path:
            parts = self.path.split("?", 1)[0].split("/")
            try:
                if len(parts) != 4 or parts[1] != "workloads" or parts[3] != "browser":
                    raise ValueError
                chat_id = uuid.UUID(parts[2])
                if str(chat_id) != parts[2]:
                    raise ValueError
                query = parse_qs(urlsplit(self.path).query)
                paths = query.get("path", [])
                if len(paths) != 1:
                    raise ValueError
                ports = query.get("port", [])
                if len(ports) > 1:
                    raise ValueError
                if self.headers.get("Upgrade", "").lower() == "websocket":
                    if len(ports) != 1:
                        raise ValueError
                    browser_socket(self, chat_id, paths[0], ports[0])
                    return
                payload = {}
                if self.command == "POST":
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 46000:
                        raise ValueError
                    payload = json.loads(self.rfile.read(length))
                    if set(payload) != {"body", "content_type", "cookie"}:
                        raise ValueError
                    payload = {"body": base64.b64decode(payload["body"], validate=True),
                               "content_type": payload["content_type"], "cookie": payload["cookie"]}
                if self.command == "GET":
                    payload["cookie"] = self.headers.get("Cookie", "")
                self.respond(200, browser_resource(chat_id, paths[0], ports[0] if ports else None,
                                                   self.command, **payload))
            except (ValueError, FileNotFoundError, RuntimeError, json.JSONDecodeError):
                logger.exception("Private browser connection rejected")
                self.respond(404, {"error": "Not found"})
            return
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

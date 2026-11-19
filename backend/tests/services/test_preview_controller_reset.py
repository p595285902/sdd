"""Acceptance controller protocol tests. All Docker operations use an in-memory Engine."""

import copy
import importlib
import json
import threading
import uuid
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

RUN = "acceptance-controller-test"
TOKEN = "A9x_2KLp7eZq4VbM8sTn6dRf0wCh3Juy5GQ"


class Engine:
    def __init__(self, worker):
        self.worker = worker
        self.calls = []
        self.removed = []
        self.failure = None
        self.resources = {kind: {} for kind in ("containers", "networks", "volumes", "images")}
        for key in ("sdd-develop-workspaces", "sdd-db-data", "sdd-acceptance-agent-state"):
            name = f"{RUN}_{key}"
            self.resources["volumes"][name] = {
                "Name": name, "CreatedAt": "2026-01-01", "Labels": self.compose_labels("volume", key),
                "Driver": "local", "Options": None,
            }
        backend_env = {
            "DEVELOP_ACCEPTANCE_RESET_ENABLED": "true", "DEVELOP_ACCEPTANCE_MODE": "true",
            "ACCEPTANCE_RUN_ID": RUN, "ACCEPTANCE_RESET_TOKEN": TOKEN,
            "DEVELOP_WORKSPACE_ROOT": "/develop-workspaces",
            "DATABASE_URL": "postgresql://postgres:database-password@db:5432/app",
            "SECRET_KEY": "application-secret", "FIRST_SUPERUSER_PASSWORD": "administrator-password",
        }
        controller_env = {
            "DEVELOP_ACCEPTANCE_RESET_ENABLED": "true", "ACCEPTANCE_RUN_ID": RUN,
            "ACCEPTANCE_RESET_TOKEN": TOKEN, "PREVIEW_PROJECT": RUN,
            "PREVIEW_WORKSPACE_VOLUME": f"{RUN}_sdd-develop-workspaces",
        }
        for service, keys in (("backend", ("default", "preview-control")), ("db", ("default",)),
                              ("preview-controller", ("preview-control",))):
            identifier = f"{service}-id"
            env = backend_env if service == "backend" else controller_env if service == "preview-controller" else {
                "POSTGRES_PASSWORD": "database-password", "POSTGRES_DB": "app",
            }
            mounts = []
            if service in ("backend", "preview-controller"):
                mounts.append(self.mount("sdd-develop-workspaces", "/develop-workspaces", service == "backend"))
            if service == "backend":
                mounts.append(self.mount("sdd-acceptance-agent-state", "/acceptance-agent-state", True))
            if service == "db":
                mounts.append(self.mount("sdd-db-data", "/var/lib/postgresql", True))
            self.resources["containers"][identifier] = {
                "Id": identifier, "Name": f"/{RUN}-{service}-1", "Image": f"{service}-image-id",
                "Config": {"Labels": self.compose_labels("service", service), "Hostname": "controller-host",
                           "Env": [f"{key}={value}" for key, value in env.items()]},
                "State": {"Running": True, "StartedAt": "2026-01-01", "Health": {"Status": "healthy"}},
                "RestartCount": 0, "Mounts": mounts, "HostConfig": {"PortBindings": {}},
                "NetworkSettings": {"Ports": {}, "Networks": {
                    f"{RUN}_{key}": {"NetworkID": f"{key}-id", "Aliases": [service]} for key in keys
                }},
            }
        for key in ("default", "preview-control"):
            identifier = f"{key}-id"
            name = f"{RUN}_{key}"
            self.resources["networks"][identifier] = {
                "Id": identifier, "Name": name, "Internal": key == "preview-control",
                "Labels": self.compose_labels("network", key),
                "Containers": {identifier: {} for identifier, item in self.resources["containers"].items()
                               if name in item["NetworkSettings"]["Networks"]},
            }
        self.resources["networks"]["egress-id"] = {
            "Id": "egress-id", "Name": worker.outbound_network(), "Internal": False,
            "Labels": {"sdd.preview.project": RUN}, "Containers": {},
        }

    @staticmethod
    def compose_labels(kind, name):
        return {"com.docker.compose.project": RUN, f"com.docker.compose.{kind}": name,
                **({"com.docker.compose.config-hash": "a" * 64, "com.docker.compose.container-number": "1",
                    "com.docker.compose.oneoff": "False", "com.docker.compose.version": "2.39.4"}
                   if kind == "service" else {})}

    @staticmethod
    def mount(key, destination, writable):
        return {"Type": "volume", "Name": f"{RUN}_{key}", "Destination": destination, "RW": writable}

    def orphan(self, project=RUN, inherited_compose_labels=False):
        chat = str(uuid.uuid4())
        labels = {"sdd.preview.project": project, "sdd.preview.chat-id": chat}
        container_labels = {**labels, **({"com.docker.compose.project": project,
            "com.docker.compose.service": "preview-controller", "com.docker.compose.version": "2.39.4"}
            if inherited_compose_labels else {})}
        names = []
        for suffix in ("", "-registry", "-build-website", "-compose-api"):
            identifier = f"{project}-preview-{chat}{suffix}"
            self.resources["containers"][identifier] = {
                "Id": identifier, "Name": identifier, "Image": "preview-controller-image-id",
                "Config": {"Labels": container_labels}, "Mounts": [],
            }
            names.append(identifier)
        name = f"{project}-preview-{chat}-compose"
        self.resources["networks"][name] = {
            "Id": name, "Name": name, "Labels": labels, "Internal": True,
            "Containers": {names[0]: {}, names[-1]: {}},
        }
        volume = f"{project}-preview-{chat}-socket"
        self.resources["volumes"][volume] = {"Name": volume, "Labels": labels}
        image = f"sha256:{chat}"
        self.resources["images"][image] = {
            "Id": image, "Config": {"Labels": container_labels}, "RepoTags": [f"{project}-preview-{chat}-website:staged"],
        }
        return uuid.UUID(chat), names + [name, volume, image]

    def label_data(self, kind, item):
        return (item.get("Config", {}).get("Labels") if kind in ("containers", "images") else item.get("Labels")) or {}

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path))
        if self.failure and self.failure(method, path):
            return 500, {}
        url = urlsplit(path)
        parts = [unquote(part) for part in url.path.split("/") if part]
        kind = parts[0]
        resources = self.resources[kind]
        if method == "GET" and (len(parts) == 1 or parts[1] == "json"):
            filters = json.loads(parse_qs(url.query).get("filters", ["{}"])[0])
            entries = []
            for item in resources.values():
                labels = self.label_data(kind, item)
                if all(labels.get(key) == value if "=" in expression else key in labels
                       for expression in filters.get("label", [])
                       for key, _, value in [expression.partition("=")]):
                    summary = copy.deepcopy(item)
                    if kind in ("containers", "images"):
                        summary["Labels"] = labels
                    if kind == "containers":
                        summary["Names"] = [summary["Name"]]
                    entries.append(summary)
            return 200, {"Volumes": entries} if kind == "volumes" else entries
        identifier = parts[1]
        item = resources.get(identifier) or next((item for item in resources.values()
                                                 if item.get("Name") == identifier
                                                 or (kind == "images" and identifier in item.get("RepoTags", []))), None)
        if item is None:
            return 404, {}
        if method == "GET":
            return 200, copy.deepcopy(item)
        assert method == "DELETE"
        if kind == "images":
            if identifier in item.get("RepoTags", []):
                item["RepoTags"].remove(identifier)
                if item["RepoTags"]:
                    return 200, {}
            elif len(item.get("RepoTags", [])) > 1:
                return 409, {}
        key = item.get("Name") if kind == "volumes" else item["Id"]
        self.removed.append(key)
        del resources[key]
        if kind == "containers":
            for network in self.resources["networks"].values():
                network.get("Containers", {}).pop(key, None)
        return 204, {}


@pytest.fixture
def controller(monkeypatch):
    monkeypatch.setenv("PREVIEW_WORKSPACE_VOLUME", f"{RUN}_sdd-develop-workspaces")
    monkeypatch.setenv("PREVIEW_PROJECT", RUN)
    monkeypatch.setenv("PREVIEW_IMAGE", f"{RUN}-preview:runtime")
    monkeypatch.setenv("DEVELOP_ACCEPTANCE_RESET_ENABLED", "true")
    monkeypatch.setenv("ACCEPTANCE_RUN_ID", RUN)
    monkeypatch.setenv("ACCEPTANCE_RESET_TOKEN", TOKEN)
    monkeypatch.setenv("ACCEPTANCE_RESET_TIMEOUT_SECONDS", "60")
    worker = importlib.import_module("app.services.preview_controller")
    monkeypatch.setattr(worker, "PROJECT", RUN)
    monkeypatch.setattr(worker, "VOLUME", f"{RUN}_sdd-develop-workspaces")
    monkeypatch.setattr(worker, "WORKSPACE_ROOT", "/develop-workspaces")
    monkeypatch.setattr(worker.socket, "gethostname", lambda: "controller-host")
    reset = worker.AcceptanceReset()
    monkeypatch.setattr(worker, "acceptance_reset", reset)
    engine = Engine(worker)
    monkeypatch.setattr(worker, "docker", engine)
    monkeypatch.setattr(worker, "activity", {})
    monkeypatch.setattr(worker, "ready_services", {})
    monkeypatch.setattr(worker, "failed_services", set())
    return worker, reset, engine


def request(reset_id="boundary-1", expected_generation=0, timeout=5, **extra):
    return {"run_id": RUN, "reset_id": reset_id, "expected_generation": expected_generation,
            "timeout_seconds": timeout, **extra}


def finish_reset(reset, payload=None):
    payload = payload or request()
    reset.control("quiesce", payload)
    reset.control("reset", payload)
    return reset.control("resume", {**payload, "generation": payload["expected_generation"] + 1, "baseline_verified": True})


@contextmanager
def server(worker):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), worker.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def http_request(address, method, path, payload=None, auth=True, raw=None, headers=None):
    connection = HTTPConnection(*address, timeout=3)
    supplied = {"Authorization": f"Bearer {TOKEN}", "X-Acceptance-Run": RUN} if auth else {}
    supplied.update(headers or {})
    body = raw if raw is not None else json.dumps(payload) if payload is not None else None
    try:
        connection.request(method, path, body, supplied)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


@pytest.mark.parametrize("action,method", [("state", "GET"), ("quiesce", "POST"), ("reset", "POST"), ("resume", "POST"), ("advance-idle-time", "POST")])
def test_controls_absent_outside_acceptance_mode(controller, action, method):
    worker, reset, engine = controller
    reset.enabled = False
    with server(worker) as address:
        code, _ = http_request(address, method, f"/testing/acceptance/{action}", request())
    assert code == 404
    assert not engine.calls
    assert reset.phase == "admitting"


@pytest.mark.parametrize("action", ["quiesce", "advance-idle-time"])
@pytest.mark.parametrize("headers", [None, {"Authorization": "Bearer wrong", "X-Acceptance-Run": RUN},
                                    {"Authorization": f"Bearer {TOKEN}", "X-Acceptance-Run": "other-run"},
                                    {"Authorization": "Bearer é", "X-Acceptance-Run": RUN}])
def test_invalid_auth_cannot_close_admissions_or_inspect_docker(controller, headers, action):
    worker, reset, engine = controller
    with server(worker) as address:
        code, _ = http_request(address, "POST", f"/testing/acceptance/{action}", request(), auth=False, headers=headers)
    assert code == 403
    assert not engine.calls
    assert reset.phase == "admitting"


@pytest.mark.parametrize("extra", [{"project": "other"}, {"database": "other"}, {"root": "/tmp"}])
def test_rejects_caller_scope_before_state_changes(controller, extra):
    worker, reset, engine = controller
    with server(worker) as address:
        code, _ = http_request(address, "POST", "/testing/acceptance/quiesce", request(**extra))
    assert code == 400
    assert not engine.calls
    assert reset.phase == "admitting"


@pytest.mark.parametrize("overrides,code", [({"run_id": "other"}, 409), ({"expected_generation": 42}, 409),
                                          ({"expected_generation": True}, 400), ({"timeout_seconds": float("nan")}, 400),
                                          ({"timeout_seconds": 61}, 400)])
def test_invalid_identity_generation_or_deadline_does_not_mutate(controller, overrides, code):
    _, reset, engine = controller
    with pytest.raises(Exception) as error:
        reset.control("quiesce", {**request(), **overrides})
    assert error.value.code == code
    assert reset.phase == "admitting"
    assert not engine.calls


def test_duplicate_json_keys_rejected_before_mutation(controller):
    worker, reset, engine = controller
    with server(worker) as address:
        code, _ = http_request(address, "POST", "/testing/acceptance/quiesce", raw='{"run_id":"x","run_id":"y"}')
    assert code == 400
    assert reset.phase == "admitting"
    assert not engine.calls


@pytest.mark.parametrize("endpoint,response", [
    ("/containers/json?", {}),
    ("/containers/backend-id/json", []),
    ("/volumes?", []),
    ("/volumes?", {"Volumes": {}}),
    ("/volumes?", {"Volumes": [42]}),
    ("/networks?", [None]),
    ("/images/json?", {}),
])
def test_malformed_engine_response_shapes_fail_closed_before_deletion(controller, monkeypatch, endpoint, response):
    worker, reset, engine = controller
    original = worker.docker

    def malformed(method, path, *args, **kwargs):
        if method == "GET" and path.startswith(endpoint):
            return 200, response
        return original(method, path, *args, **kwargs)

    monkeypatch.setattr(worker, "docker", malformed)
    with pytest.raises(worker.ResetControlError) as error:
        finish_reset(reset)
    assert error.value.code == 503
    assert reset.phase == "failed" and reset.generation == 0
    assert not engine.removed
    assert not reset.baseline_verified


def test_uninitialized_operation_deadline_remains_failed_and_closed(controller):
    worker, reset, engine = controller
    reset.control("quiesce", request())
    reset.deadline = None
    with pytest.raises(worker.ResetControlError) as error:
        reset.control("reset", request())
    assert error.value.code == 503
    assert reset.phase == "failed" and reset.generation == 0
    assert not engine.removed


def test_ownership_attestation_matches_backend_contract_and_is_secret_free(controller):
    _, reset, engine = controller
    state = reset.diagnostic_state()
    ownership = state["ownership"]
    assert ownership["verified"] is True
    assert ownership["services"] == {"backend": "backend-id", "db": "db-id", "preview_controller": "preview-controller-id"}
    assert ownership["database"]["compose_project"] == RUN
    assert ownership["database"]["database"] == "app"
    assert ownership["workspace"]["volume"] == f"{RUN}_sdd-develop-workspaces"
    assert ownership["agent"]["volume"] == f"{RUN}_sdd-acceptance-agent-state"
    assert TOKEN not in json.dumps(state)
    assert "database-password" not in json.dumps(state)
    assert not engine.removed


@pytest.mark.parametrize("tamper", ["db_project", "db_host", "db_volume", "workspace_volume", "agent_volume",
                                    "network_project", "db_alias", "db_alias_collision", "controller_published",
                                    "controller_hostname", "backend_token", "db_password", "workspace_rw",
                                    "db_hosts_override", "volume_bind_options"])
def test_docker_ownership_must_be_proven_before_destructive_cleanup(controller, tamper):
    worker, reset, engine = controller
    backend = engine.resources["containers"]["backend-id"]
    database = engine.resources["containers"]["db-id"]
    controller_container = engine.resources["containers"]["preview-controller-id"]
    if tamper == "db_project":
        database["Config"]["Labels"]["com.docker.compose.project"] = "other"
    elif tamper == "db_host":
        backend["Config"]["Env"] = [value.replace("@db:", "@foreign:") for value in backend["Config"]["Env"]]
    elif tamper in ("db_volume", "workspace_volume", "agent_volume"):
        key = {"db_volume": "sdd-db-data", "workspace_volume": "sdd-develop-workspaces", "agent_volume": "sdd-acceptance-agent-state"}[tamper]
        engine.resources["volumes"][f"{RUN}_{key}"]["Labels"]["com.docker.compose.project"] = "other"
    elif tamper == "network_project":
        engine.resources["networks"]["default-id"]["Labels"]["com.docker.compose.project"] = "other"
    elif tamper == "db_alias":
        database["NetworkSettings"]["Networks"][f"{RUN}_default"]["Aliases"] = ["not-db"]
    elif tamper == "db_alias_collision":
        backend["NetworkSettings"]["Networks"][f"{RUN}_default"]["Aliases"].append("db")
    elif tamper == "controller_published":
        controller_container["HostConfig"]["PortBindings"] = {"8090/tcp": [{"HostPort": "8090"}]}
    elif tamper == "controller_hostname":
        controller_container["Config"]["Hostname"] = "not-this-controller"
    elif tamper == "backend_token":
        backend["Config"]["Env"] = [value.replace(TOKEN, "incorrect") for value in backend["Config"]["Env"]]
    elif tamper == "db_password":
        database["Config"]["Env"] = [value.replace("database-password", "incorrect") for value in database["Config"]["Env"]]
    elif tamper == "workspace_rw":
        backend["Mounts"][0]["RW"] = False
    elif tamper == "db_hosts_override":
        backend["HostConfig"]["ExtraHosts"] = ["db:192.0.2.42"]
    elif tamper == "volume_bind_options":
        engine.resources["volumes"][f"{RUN}_sdd-develop-workspaces"]["Options"] = {"device": "/home/unrelated", "o": "bind"}
    with pytest.raises(Exception) as error:
        reset.control("quiesce", request())
    assert error.value.code == 503
    assert reset.phase == "failed"
    assert not engine.removed
    with pytest.raises(worker.ResetControlError):
        with reset.work("handler"):
            pytest.fail("Unsafe ownership must leave admissions closed")


def test_reset_discovers_all_orphans_preserves_stack_and_unrelated_resources(controller):
    worker, reset, engine = controller
    chat, owned = engine.orphan()
    _, unrelated = engine.orphan(project="unrelated-project")
    worker.activity[chat] = 1
    worker.ready_services[chat] = {"website_port": "8000"}
    worker.failed_services.add(chat)
    state = finish_reset(reset)
    assert set(engine.removed) == set(owned)
    assert not set(engine.removed).intersection(unrelated)
    assert "egress-id" in engine.resources["networks"]
    assert {"backend-id", "db-id", "preview-controller-id"}.issubset(engine.resources["containers"])
    assert {f"{RUN}_{key}" for key in ("sdd-develop-workspaces", "sdd-db-data", "sdd-acceptance-agent-state")}.issubset(engine.resources["volumes"])
    assert state["generation"] == 1
    assert state["baseline_verified"] is True
    assert state["active_work"] == 0
    assert not worker.activity and not worker.ready_services and not worker.failed_services
    assert all(method != "DELETE" or any(path.startswith(f"/{kind}/") for kind in engine.resources)
               for method, path in engine.calls)


@pytest.mark.parametrize("kind", ["handler", "maintenance"])
def test_actual_completion_barrier_waits_for_late_mutations(controller, kind):
    worker, reset, engine = controller
    entered, release, complete = threading.Event(), threading.Event(), threading.Event()
    chat = uuid.uuid4()
    def prior_work():
        with reset.work(kind):
            entered.set()
            assert release.wait(3)
            worker.ready_services[chat] = {"late": "write"}
            engine.orphan()
        complete.set()
    thread = threading.Thread(target=prior_work)
    thread.start()
    assert entered.wait(1)
    quiesced = threading.Event()
    errors = []
    def quiesce():
        try:
            reset.control("quiesce", request())
            quiesced.set()
        except Exception as error:
            errors.append(error)
    control = threading.Thread(target=quiesce)
    control.start()
    assert reset.cancel.wait(1)
    assert not quiesced.is_set()
    assert not engine.removed
    assert not complete.is_set()
    with pytest.raises(worker.ResetControlError):
        with reset.work("handler"):
            pytest.fail("Closed admissions must not yield")
    release.set()
    thread.join(2)
    control.join(2)
    assert not errors
    assert complete.is_set() and quiesced.is_set()
    reset.control("reset", request())
    assert not worker.ready_services
    assert engine.removed


def test_real_http_handler_and_sweep_use_same_barrier(controller, monkeypatch):
    worker, reset, _ = controller
    entered, release = threading.Event(), threading.Event()
    def start(_chat):
        entered.set()
        assert release.wait(3)
        return {"state": "running"}
    monkeypatch.setattr(worker, "start", start)
    monkeypatch.setattr(worker, "status", lambda chat: {"state": "running"})
    with server(worker) as address:
        handler = threading.Thread(target=lambda: http_request(address, "POST", f"/workloads/{uuid.uuid4()}"))
        handler.start()
        assert entered.wait(1)
        coordinator = threading.Thread(target=lambda: reset.control("quiesce", request()))
        coordinator.start()
        assert reset.cancel.wait(1)
        assert reset.active["handler"] == 1
        assert http_request(address, "POST", f"/workloads/{uuid.uuid4()}")[0] == 503
        assert http_request(address, "GET", "/health")[0] == 200
        assert http_request(address, "GET", f"/workloads/{uuid.uuid4()}")[0] == 200
        assert http_request(address, "GET", "/testing/acceptance/state")[0] == 200
        with pytest.raises(worker.ResetControlError):
            worker.sweep()
        release.set()
        handler.join(2)
        coordinator.join(2)
    assert reset.phase == "quiesced"
    assert reset.active["handler"] == 0


def test_drain_timeout_is_terminal_and_does_not_clear_maps(controller):
    worker, reset, engine = controller
    chat = uuid.uuid4()
    worker.activity[chat] = 1
    with reset.work("maintenance"):
        with pytest.raises(worker.ResetControlError) as error:
            reset.control("quiesce", request(timeout=0.05))
        assert error.value.code == 503
        assert reset.phase == "failed"
        assert reset.active["maintenance"] == 1
        assert worker.activity == {chat: 1}
        assert not engine.removed
    assert reset.active["maintenance"] == 0
    with pytest.raises(worker.ResetControlError):
        reset.control("quiesce", request("another"))


def test_blocked_docker_cleanup_returns_by_deadline_and_late_worker_cannot_reopen(controller, monkeypatch):
    worker, reset, engine = controller
    chat, _ = engine.orphan()
    worker.activity[chat] = 1
    reset.control("quiesce", request(timeout=1))
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = worker.remove_resource
    def removal(path):
        entered.set()
        assert release.wait(3)
        try:
            original(path)
        finally:
            finished.set()
    monkeypatch.setattr(worker, "remove_resource", removal)
    with pytest.raises(worker.ResetControlError):
        reset.control("reset", request(timeout=0.05))
    assert entered.is_set()
    assert reset.phase == "failed" and not reset.baseline_verified
    assert reset.active["control"] == 1
    assert worker.activity == {chat: 1}
    release.set()
    assert finished.wait(1)
    with reset.condition:
        assert reset.condition.wait_for(lambda: reset.active["control"] == 0, timeout=1)
    assert reset.phase == "failed"
    assert worker.activity == {chat: 1}
    with pytest.raises(worker.ResetControlError):
        reset.control("resume", request(generation=1, baseline_verified=True))


@pytest.mark.parametrize("tamper", ["shared_network", "shared_image_tag", "compose_label", "missing_chat", "invalid_chat"])
def test_ambiguous_deletion_scope_fails_before_removing_any_resource(controller, tamper):
    worker, reset, engine = controller
    chat, owned = engine.orphan()
    if tamper == "shared_network":
        engine.resources["networks"][owned[-3]]["Containers"]["backend-id"] = {}
    elif tamper == "shared_image_tag":
        engine.resources["images"][owned[-1]]["RepoTags"].append("unrelated:latest")
    else:
        labels = engine.resources["containers"][owned[0]]["Config"]["Labels"]
        if tamper == "compose_label":
            labels["com.docker.compose.project"] = RUN
        elif tamper == "missing_chat":
            labels.pop("sdd.preview.chat-id")
        else:
            labels["sdd.preview.chat-id"] = "unsafe"
    worker.activity[chat] = 1
    reset.control("quiesce", request())
    with pytest.raises(worker.ResetControlError):
        reset.control("reset", request())
    assert reset.phase == "failed"
    assert not engine.removed
    assert worker.activity == {chat: 1}


def test_partial_cleanup_failure_never_clears_maps_or_reports_baseline(controller):
    worker, reset, engine = controller
    chat, _ = engine.orphan()
    worker.failed_services.add(chat)
    reset.control("quiesce", request())
    engine.failure = lambda method, path: method == "DELETE" and path.startswith("/volumes/")
    with pytest.raises(worker.ResetControlError):
        reset.control("reset", request())
    assert engine.removed
    assert worker.failed_services == {chat}
    assert reset.phase == "failed"
    assert reset.generation == 0 and not reset.baseline_verified


def test_resume_requires_backend_verification_and_correct_generation(controller):
    worker, reset, engine = controller
    payload = request()
    reset.control("quiesce", payload)
    with pytest.raises(worker.ResetControlError) as error:
        reset.control("resume", {**payload, "generation": 1, "baseline_verified": True})
    assert error.value.code == 409
    reset.control("reset", payload)
    for extra in ({"generation": 1, "baseline_verified": False}, {"generation": 42, "baseline_verified": True}):
        with pytest.raises(worker.ResetControlError):
            reset.control("resume", {**payload, **extra})
        assert reset.phase == "preview_reset"
    assert not engine.removed
    assert reset.control("resume", {**payload, "generation": 1, "baseline_verified": True})["phase"] == "ready"


def test_retry_safe_only_until_new_scenario_work_starts(controller):
    worker, reset, engine = controller
    state = finish_reset(reset)
    deletes = list(engine.removed)
    for action in ("quiesce", "reset", "resume"):
        payload = request(generation=1, baseline_verified=True) if action == "resume" else request()
        assert reset.control(action, payload) == state
    assert engine.removed == deletes
    with reset.work("handler"):
        _, owned = engine.orphan()
        for action in ("quiesce", "reset", "resume"):
            payload = request(generation=1, baseline_verified=True) if action == "resume" else request()
            with pytest.raises(worker.ResetControlError) as error:
                reset.control(action, payload)
            assert error.value.code == 409
            assert reset.active["handler"] == 1
            assert not reset.cancel.is_set()
            assert reset.generation == 1
        assert set(owned).isdisjoint(engine.removed)
        assert reset.phase == "ready"
    assert finish_reset(reset, request("boundary-2", expected_generation=1))["generation"] == 2


def test_configuration_quiescence_preserves_scenario_and_cannot_delete_it(controller):
    worker, reset, engine = controller
    chat, _ = engine.orphan()
    worker.ready_services[chat] = {"website_port": "8000"}
    payload = request(operation="configuration")
    reset.control("quiesce", payload)
    plain = request()
    with pytest.raises(worker.ResetControlError) as error:
        reset.control("reset", plain)
    assert error.value.code == 409
    state = reset.control("resume", {**plain, "generation": 0, "baseline_verified": True})
    assert state["generation"] == 0
    assert state["dirty"] and not state["baseline_verified"]
    assert worker.ready_services[chat]
    assert not engine.removed
    reset.control("quiesce", request("configuration-2", operation="configuration"))
    reset.control("resume", request("configuration-2", generation=0, baseline_verified=True))
    with pytest.raises(worker.ResetControlError):
        reset.control("quiesce", payload)
    assert reset.phase == "ready"
    assert finish_reset(reset, request("real-reset"))["generation"] == 1


def test_service_identity_change_after_cleanup_prevents_resume(controller):
    worker, reset, engine = controller
    reset.control("quiesce", request())
    reset.control("reset", request())
    engine.resources["containers"]["db-id"]["RestartCount"] = 1
    with pytest.raises(worker.ResetControlError):
        reset.control("resume", request(generation=1, baseline_verified=True))
    assert reset.phase == "failed" and reset.generation == 0


def test_owned_multitag_images_are_removed_without_force(controller):
    _, reset, engine = controller
    chat, owned = engine.orphan()
    engine.resources["images"][owned[-1]]["RepoTags"].append(f"{RUN}-preview-{chat}-api:staged")
    assert finish_reset(reset)["baseline_verified"]
    assert owned[-1] in engine.removed
    image_deletes = [path for method, path in engine.calls if method == "DELETE" and path.startswith("/images/")]
    assert len(image_deletes) == 3
    assert all("force" not in path for path in image_deletes)


def test_live_previews_inherit_build_labels_without_becoming_compose_instances(controller):
    worker, reset, engine = controller
    initial = reset.diagnostic_state()["ownership"]
    chat, owned = engine.orphan(inherited_compose_labels=True)
    worker.ready_services[chat] = {"website_port": "8000"}
    # Match real Compose-built preview images: Docker merges project/service/version
    # image labels into registry, workload and helper containers at create time.
    with reset.work("handler"):
        assert worker.acceptance_ownership() == initial
        assert reset.diagnostic_state()["ownership"] == initial
        assert reset.phase == "admitting"
        assert reset.active["handler"] == 1
    state = finish_reset(reset)
    assert state["ownership"] == initial
    assert state["baseline_verified"]
    assert set(engine.removed) == set(owned)
    assert not worker.ready_services


@pytest.mark.parametrize("marker", ["config-hash", "container-number", "oneoff", "network", "volume"])
def test_compose_instance_labels_cannot_become_scenario_ownership(controller, marker):
    worker, reset, engine = controller
    chat, owned = engine.orphan(inherited_compose_labels=True)
    labels = engine.resources["containers"][owned[0]]["Config"]["Labels"]
    # A real extra Compose instance is not one of our pinned main services, but
    # cannot become deletable by acquiring chat labels or a preview-like name.
    labels["com.docker.compose.service"] = "fixture-compose-service"
    labels[f"com.docker.compose.{marker}"] = "instance-owned"
    worker.activity[chat] = 1
    reset.control("quiesce", request())
    with pytest.raises(worker.ResetControlError):
        reset.control("reset", request())
    assert reset.phase == "failed" and not reset.baseline_verified
    assert not engine.removed
    assert worker.activity == {chat: 1}


@pytest.mark.parametrize("service", ["backend", "db", "preview-controller"])
def test_pinned_main_compose_instances_remain_undeletable_with_chat_labels(controller, service):
    worker, reset, engine = controller
    item = engine.resources["containers"][f"{service}-id"]
    item["Config"]["Labels"].update({"sdd.preview.project": RUN, "sdd.preview.chat-id": str(uuid.uuid4())})
    with pytest.raises(worker.ResetControlError):
        reset.control("quiesce", request())
    assert reset.phase == "failed"
    assert f"{service}-id" in engine.resources["containers"]
    assert not engine.removed


@pytest.mark.parametrize("marker", ["config-hash", "container-number", "oneoff"])
def test_main_instance_attestation_requires_all_real_instance_markers(controller, marker):
    worker, reset, engine = controller
    engine.resources["containers"]["preview-controller-id"]["Config"]["Labels"].pop(f"com.docker.compose.{marker}")
    with pytest.raises(worker.ResetControlError):
        reset.control("quiesce", request())
    assert reset.phase == "failed" and not engine.removed


@pytest.mark.parametrize("tamper", ["wrong_image", "wrong_namespace", "writable_workspace", "database_mount", "control_attachment"])
def test_inherited_build_labels_require_pinned_image_and_safe_storage_network_scope(controller, tamper):
    worker, reset, engine = controller
    _, owned = engine.orphan(inherited_compose_labels=True)
    item = engine.resources["containers"][owned[0]]
    if tamper == "wrong_image":
        item["Image"] = "unrelated-image-id"
    elif tamper == "wrong_namespace":
        item["Name"] = "unrelated-container-name"
    elif tamper == "writable_workspace":
        item["Mounts"] = [engine.mount("sdd-develop-workspaces", "/checkout", True)]
    elif tamper == "database_mount":
        item["Mounts"] = [engine.mount("sdd-db-data", "/data", False)]
    else:
        engine.resources["networks"]["preview-control-id"]["Containers"][item["Id"]] = {}
        item["NetworkSettings"] = {"Networks": {f"{RUN}_preview-control": {"Aliases": []}}}
        with pytest.raises(worker.ResetControlError):
            reset.control("quiesce", request())
        assert reset.phase == "failed" and not engine.removed
        return
    reset.control("quiesce", request())
    with pytest.raises(worker.ResetControlError):
        reset.control("reset", request())
    assert reset.phase == "failed" and not engine.removed


def test_inherited_labels_allow_only_readonly_checkout_access_to_stack_workspace(controller):
    _, reset, engine = controller
    _, owned = engine.orphan(inherited_compose_labels=True)
    engine.resources["containers"][owned[0]]["Mounts"] = [engine.mount("sdd-develop-workspaces", "/checkout", False)]
    assert finish_reset(reset)["baseline_verified"]
    assert set(engine.removed) == set(owned)
    assert f"{RUN}_sdd-develop-workspaces" in engine.resources["volumes"]


def test_actual_sweeper_is_tracked_until_final_mutation(controller, monkeypatch):
    worker, reset, engine = controller
    chat, _ = engine.orphan()
    entered, release = threading.Event(), threading.Event()
    def docker(method, path, payload=None):
        if method == "GET" and path.startswith("/containers/json") and "sdd.preview.project" in unquote(path):
            entered.set()
            assert release.wait(3)
        return engine(method, path, payload)
    monkeypatch.setattr(worker, "docker", docker)
    monkeypatch.setattr(worker.os.path, "isdir", lambda path: False)
    monkeypatch.setattr(worker, "stop", lambda chat: worker.ready_services.update({chat: {"late": "sweep"}}))
    sweeper = threading.Thread(target=worker.sweep)
    sweeper.start()
    assert entered.wait(1)
    assert reset.active["maintenance"] == 1
    control = threading.Thread(target=lambda: reset.control("quiesce", request()))
    control.start()
    assert reset.cancel.wait(1)
    assert reset.phase == "quiescing" and not engine.removed
    release.set()
    sweeper.join(2)
    control.join(2)
    assert reset.active["maintenance"] == 0 and reset.phase == "quiesced"
    assert worker.ready_services[chat] == {"late": "sweep"}
    reset.control("reset", request())
    assert not worker.ready_services


def test_conflicting_control_does_not_replace_active_reset(controller):
    worker, reset, _ = controller
    reset.control("quiesce", request())
    with pytest.raises(worker.ResetControlError) as error:
        reset.control("quiesce", request("other-boundary"))
    assert error.value.code == 409
    assert reset.reset_id == "boundary-1" and reset.phase == "quiesced"
    reset.operation_lock.acquire()
    try:
        with pytest.raises(worker.ResetControlError) as error:
            reset.control("reset", request())
        assert error.value.code == 409
    finally:
        reset.operation_lock.release()


@pytest.mark.parametrize("compose", [False, True])
def test_status_marks_only_actual_compose_runtime(controller, monkeypatch, compose):
    worker, _, _ = controller
    chat_id = uuid.uuid4()
    labels = {"sdd.preview.compose-service": "api"} if compose else {}
    monkeypatch.setattr(worker, "inspect", lambda _: {
        "Id": "runtime-id", "State": {"Status": "running", "Running": True},
        "Config": {"Labels": labels},
    })
    worker.ready_services[chat_id] = {"initial_port": "8766", "initial_path": "/"}
    result = worker.status(chat_id)
    assert (result.get("runtime") == "compose") is compose
    assert result["initial_port"] == "8766"
    if not compose:
        assert result == {
            "id": "runtime-id", "state": "running", "initial_port": "8766", "initial_path": "/",
        }


def idle_request(seconds=1, generation=0, **extra):
    return {"run_id": RUN, "expected_generation": generation, "seconds": seconds, **extra}


def idle_workload(controller, monkeypatch):
    worker, _, engine = controller
    chat, owned = engine.orphan()
    # Native nested resources live inside the outer daemon, not on this Engine.
    for identifier in owned[2:4]:
        engine.resources["containers"].pop(identifier)
    engine.resources["networks"].pop(owned[4])
    engine.resources["images"].pop(owned[6])
    owned = [owned[0], owned[1], owned[5]]
    isdir = worker.os.path.isdir
    monkeypatch.setattr(worker.os.path, "isdir", lambda path: str(path).startswith("/develop-workspaces/") or isdir(path))
    container = engine.resources["containers"][owned[0]]
    container.update(Created=1000, State={"Running": False})
    container["Config"]["Labels"][worker.NATIVE_LABEL] = str(uuid.uuid4())
    monkeypatch.setattr(worker.native, "sync", lambda _chat: None)
    monkeypatch.setattr(worker.native, "before_stop", lambda *_args: None)
    monkeypatch.setattr(worker.legacy, "before_stop", lambda *_args: None)
    return chat, owned


def test_private_idle_clock_advances_real_sweep_and_heartbeat_renews(controller, monkeypatch):
    worker, reset, engine = controller
    finish_reset(reset)
    monkeypatch.setattr(worker.time, "time", lambda: 1000.0)
    chat, owned = idle_workload(controller, monkeypatch)
    output = []
    monkeypatch.setattr(worker.native, "events", lambda chat: output.append(chat))
    monkeypatch.setattr(worker, "status", lambda _chat: {"state": "running"})
    worker.heartbeat(chat)
    real_deadline = worker.time.monotonic() + 60
    with server(worker) as address:
        code, result = http_request(address, "POST", "/testing/acceptance/advance-idle-time", idle_request(299, 1))
        assert code == 200 and result["advanced_seconds"] == 299
        assert result["idle_time_offset_seconds"] == 299 and result["idle_time"] == 1299
        assert result["generation"] == 1 and result["boot_id"] == reset.boot_id
        assert result["dirty"] and not result["baseline_verified"] and not result["active_work"]
        assert output and worker.activity[chat] == 1000  # Output never renews activity.
        assert not engine.removed and worker.IDLE_SECONDS == 300
        worker.heartbeat(chat)
        assert worker.activity[chat] == 1299
        code, result = http_request(address, "POST", "/testing/acceptance/advance-idle-time", idle_request(299, 1))
        assert code == 200 and result["idle_time"] == 1598
        assert worker.activity[chat] == 1299 and not engine.removed
        code, result = http_request(address, "POST", "/testing/acceptance/advance-idle-time", idle_request(1, 1))
        assert code == 200 and result["idle_time"] == 1599
    assert set(engine.removed) == set(owned) | {"egress-id"} and chat not in worker.activity
    assert 0 < real_deadline - worker.time.monotonic() <= 60
    restored = finish_reset(reset, request("after-idle", expected_generation=1))
    assert restored["idle_time_offset_seconds"] == 0 and restored["baseline_verified"]
    assert worker.idle_time() == 1000


@pytest.mark.parametrize("overrides,code", [
    ({"run_id": "other"}, 409), ({"expected_generation": 1}, 409),
    ({"expected_generation": True}, 400), ({"expected_generation": -1}, 400),
    ({"seconds": True}, 400), ({"seconds": "300"}, 400), ({"seconds": None}, 400),
    ({"seconds": 0}, 400), ({"seconds": -1}, 400), ({"seconds": 3601}, 400),
    ({"seconds": float("nan")}, 400), ({"seconds": float("inf")}, 400),
    ({"seconds": -float("inf")}, 400), ({"root": "/"}, 400), ({"chat_id": str(uuid.uuid4())}, 400),
])
def test_invalid_idle_advance_cannot_mutate_or_inspect(controller, overrides, code):
    worker, reset, engine = controller
    before = reset.state()
    with pytest.raises(worker.ResetControlError) as error:
        reset.advance_idle_time({**idle_request(), **overrides})
    assert error.value.code == code
    assert reset.state() == before and not engine.calls


@pytest.mark.parametrize("phase", ["quiescing", "quiesced", "cleaning_previews", "preview_reset", "failed"])
def test_idle_advance_rejects_closed_admission(controller, phase):
    worker, reset, engine = controller
    reset.phase = phase
    with pytest.raises(worker.ResetControlError) as error:
        reset.advance_idle_time(idle_request())
    assert error.value.code == 503
    assert reset.idle_time_offset_seconds == 0 and not engine.calls
    assert reset.phase == phase and reset.work_serial == 0


def test_idle_advance_is_owned_tracked_and_serialized_with_reset(controller, monkeypatch):
    worker, reset, _ = controller
    entered, release = threading.Event(), threading.Event()
    original_sweep = worker.sweep
    def sweep():
        entered.set()
        assert release.wait(3)
        assert reset.active["handler"] == 1 and reset.active["control"] == 1
        original_sweep()
    monkeypatch.setattr(worker, "sweep", sweep)
    result = []
    advancing = threading.Thread(target=lambda: result.append(reset.advance_idle_time(idle_request(300))))
    advancing.start()
    assert entered.wait(1)
    try:
        assert reset.dirty and not reset.baseline_verified and reset.work_serial == 1
        assert reset.ownership["verified"]
        for operation in (lambda: reset.control("quiesce", request()), lambda: reset.advance_idle_time(idle_request())):
            with pytest.raises(worker.ResetControlError) as error:
                operation()
            assert error.value.code == 409
    finally:
        release.set()
        advancing.join(2)
    assert result[0]["idle_time_offset_seconds"] == 300 and not result[0]["active_work"]
    assert finish_reset(reset)["idle_time_offset_seconds"] == 0


def test_idle_advance_invalidates_reset_retry_and_ownership_failure_is_closed(controller):
    worker, reset, engine = controller
    finish_reset(reset)
    reset.advance_idle_time(idle_request(0.5, 1))
    with pytest.raises(worker.ResetControlError) as error:
        reset.control("quiesce", request())
    assert error.value.code == 409
    engine.resources["containers"]["db-id"]["RestartCount"] += 1
    with pytest.raises(worker.ResetControlError) as error:
        reset.advance_idle_time(idle_request(300, 1))
    assert error.value.code == 503 and reset.phase == "failed"
    assert reset.idle_time_offset_seconds == 0.5 and not engine.removed
    assert not reset.baseline_verified and not any(reset.active.values())


def test_idle_clock_creation_fallback_handles_workloads_created_after_advancement(controller, monkeypatch):
    worker, reset, engine = controller
    monkeypatch.setattr(worker.time, "time", lambda: 1000.0)
    monkeypatch.setattr(worker.native, "events", lambda _chat: None)
    first, owned = idle_workload(controller, monkeypatch)
    reset.advance_idle_time(idle_request(299))
    assert worker.activity[first] == 1000 and not engine.removed
    second, second_owned = idle_workload(controller, monkeypatch)
    reset.advance_idle_time(idle_request(1))
    assert set(engine.removed) == set(owned) | {"egress-id"}
    assert not set(engine.removed).intersection(second_owned)
    assert worker.activity[second] == 1299 and second_owned[0] in engine.resources["containers"]


def test_idle_clock_is_real_in_production_and_reset_requires_zero_offset(controller, monkeypatch):
    worker, reset, _ = controller
    monkeypatch.setattr(worker.time, "time", lambda: 1000.0)
    reset.idle_time_offset_seconds = 500
    reset.enabled = False
    assert worker.idle_time() == 1000 and worker.IDLE_SECONDS == 300
    reset.enabled = True
    reset.control("quiesce", request())
    reset.control("reset", request())
    assert reset.idle_time_offset_seconds == 0
    reset.idle_time_offset_seconds = 1
    with pytest.raises(worker.ResetControlError):
        reset.control("resume", request(generation=1, baseline_verified=True))
    assert reset.phase == "failed" and not reset.baseline_verified


def test_native_launch_initial_activity_uses_controller_idle_clock(controller, monkeypatch, tmp_path):
    worker, reset, _ = controller
    chat = uuid.uuid4()
    (tmp_path / str(chat)).mkdir()
    monkeypatch.setattr(worker, "WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("PREVIEW_NATIVE_PRIVILEGED", "true")
    monkeypatch.setattr(worker, "inspect", lambda _chat: None)
    monkeypatch.setattr(worker, "ensure_outbound_network", lambda: None)
    monkeypatch.setattr(worker, "docker", lambda method, path, *_args: (
        200 if method == "GET" else 201 if "create" in path else 204, {"Id": "native-container"},
    ))
    runtime = worker.NativeRuntime(worker)
    runtime.helper_id = "trusted-helper"
    monkeypatch.setattr(worker, "native", runtime)
    monkeypatch.setattr(runtime, "seed_helper", lambda _chat: None)
    monkeypatch.setattr(runtime, "sync", lambda _chat: None)
    monkeypatch.setattr(runtime, "upload", lambda *_args: None)
    monkeypatch.setattr(runtime, "exec", lambda *_args, **_kwargs: b'["rootless"]')
    monkeypatch.setattr(worker.time, "time", lambda: 1000.0)
    reset.idle_time_offset_seconds = 321
    runtime.launch(chat, {"runtime": "native-compose", "commands": [{}]}, str(uuid.uuid4()))
    assert worker.activity[chat] == 1321


def test_owned_reset_closes_native_event_readers_before_clearing_runtime_maps(controller, monkeypatch):
    from types import SimpleNamespace

    worker, reset, _ = controller
    chat = uuid.uuid4()
    closed = []
    def close():
        assert reset.phase == "cleaning_previews"
        assert chat in worker.native.last
        closed.append(chat)
    monkeypatch.setattr(worker.native, "readers", {chat: SimpleNamespace(close=close)})
    monkeypatch.setattr(worker.native, "last", {chat: {"state": "running"}})
    monkeypatch.setattr(worker.native, "browser_helpers", {(chat, '8765'): ('application', 'trusted-forwarder')})
    state = finish_reset(reset)
    assert closed == [chat] and not worker.native.readers and not worker.native.last
    assert not worker.native.browser_helpers
    assert state["baseline_verified"] and not state["active_work"]

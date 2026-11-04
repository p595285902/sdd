import asyncio
import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.requests import ClientDisconnect

from app.api.routes import testing_acceptance, testing_agent
from app.core.config import Settings, settings
from app.core.security import get_password_hash, verify_password
from app.models import DevelopmentChat, DevelopmentMessage, Item, User
from app.services import acceptance_reset as reset_module
from app.services.acceptance_reset import (
    AcceptanceResetCoordinator,
    ControlError,
    OwnedStorage,
    confined_environment,
    restore_database,
    verify_database,
)
from app.services.acceptance_work import (
    AcceptanceAdmissionMiddleware,
    AdmissionClosed,
    CompletionStreamingResponse,
    WorkBarrier,
    current_work,
)
from app.services.develop_agent import AgentCommandRunner, minimal_agent_environment
from app.services.develop_preview_runtime import PreviewController
from app.services.develop_turns import DevelopTurnManager, TurnTerminalState

TOKEN = "independent-run-secret-with-256-bits-of-material"


def configuration(**overrides):
    data = settings.model_dump(exclude={"emails_enabled"})
    data.update(DEVELOP_ACCEPTANCE_MODE=True, DEVELOP_ACCEPTANCE_RESET_ENABLED=True,
                DEVELOP_FAKE_SETUP_RUNNER=True, OPENAI_BASE_URL="http://127.0.0.1:8000/api/v1/testing/llm/v1",
                ACCEPTANCE_RUN_ID="acceptance-owned", ACCEPTANCE_RESET_TOKEN=TOKEN,
                DATABASE_URL="postgresql://postgres:owned-db-password@db:5432/app",
                DEVELOP_WORKSPACE_ROOT=Path("/develop-workspaces"),
                ACCEPTANCE_AGENT_ROOT=Path("/acceptance-agent-state"),
                DEMO_GITHUB_REPO="https://github.com/example/demo", DEMO_GITHUB_TOKEN="repository-secret",
                FIRST_SUPERUSER_PASSWORD="baseline-admin-password",
                ACCEPTANCE_RESET_TIMEOUT_SECONDS=2)
    data.update(overrides)
    return Settings.model_validate(data)


def sqlite_database(tmp_path):
    database = create_engine(f"sqlite:///{tmp_path / 'state.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(database)
    with database.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('baseline-revision')"))
    return database


def seed(database, cfg):
    with Session(database) as session:
        admin = User(email=cfg.FIRST_SUPERUSER, hashed_password=get_password_hash("changed-password"),
                     is_active=False, is_superuser=False, concurrent_agent_turn_limit=9, full_name="changed")
        other = User(email="scenario@example.com", hashed_password="bad")
        session.add_all([admin, other])
        session.flush()
        chat = DevelopmentChat(title="dirty", owner_id=other.id, workspace_ready=True, agent_session_id="ses_old")
        session.add(chat)
        session.flush()
        session.add_all([Item(title="dirty", owner_id=other.id), DevelopmentMessage(role="user", content="dirty", chat_id=chat.id)])
        session.commit()


def attestation(cfg):
    run = cfg.ACCEPTANCE_RUN_ID
    return {"verified": True, "project": run,
            "database": {"service": "db", "database": "app", "compose_project": run, "volume": run + "_sdd-db-data"},
            "workspace": {"destination": "/develop-workspaces", "volume": run + "_sdd-develop-workspaces", "compose_project": run},
            "agent": {"destination": "/acceptance-agent-state", "volume": run + "_sdd-acceptance-agent-state", "compose_project": run},
            "services": {"backend": "backend-container", "db": "db-container", "preview_controller": "controller-container"}}


class Controller:
    def __init__(self, cfg):
        self.cfg, self.generation, self.phase = cfg, 0, "admitting"
        self.calls = []
        self.ownership = attestation(cfg)
        self.fail = None
        self.baseline = False

    def acceptance_state(self, **kwargs):
        return {"run_id": self.cfg.ACCEPTANCE_RUN_ID, "generation": self.generation,
                "phase": self.phase, "boot_id": "controller-boot", "ownership": self.ownership,
                "active_work": 0, "baseline_verified": self.baseline}

    def acceptance_control(self, action, **kwargs):
        self.calls.append((action, kwargs))
        assert 0 < kwargs["timeout_seconds"] <= self.cfg.ACCEPTANCE_RESET_TIMEOUT_SECONDS
        if self.fail == action:
            raise RuntimeError("SECRET controller password " + TOKEN)
        if action == "quiesce":
            self.phase = "quiesced"
            self.operation = kwargs.get("operation", "reset")
            self.baseline = False
        if action == "reset":
            self.phase = "preview_reset"
        if action == "resume":
            self.generation = kwargs["generation"]
            self.phase = "ready"
            self.baseline = self.operation == "reset"
        return self.acceptance_state()


def coordinator(tmp_path, monkeypatch, **overrides):
    cfg = configuration(**overrides)
    control = AcceptanceResetCoordinator(cfg)
    for name in ("workspace", "agent"):
        root = tmp_path / name
        root.mkdir()
        setattr(control, name, OwnedStorage(root, cfg.ACCEPTANCE_RUN_ID))
    database = sqlite_database(tmp_path)
    controller = Controller(cfg)
    # Orchestration exercises real SQLite transactions and filesystem cleanup;
    # Docker/fixed production scope is tested independently below, not bypassed in implementation.
    def validate(client, engine, deadline):
        assert monotonic() < deadline
        assert engine is database
        state = client.acceptance_state()
        assert state["generation"] == control.barrier.generation
        control._controller_boot = state["boot_id"]
        control.workspace.validate()
        control.agent.validate()
    monkeypatch.setattr(control, "_validate_ownership", validate)
    return control, controller, database


def reset(control, controller, database, reset_id="reset-1", generation=0, **kwargs):
    return control.operate(reset_id=reset_id, expected_generation=generation, controller=controller, database=database, **kwargs)


@pytest.mark.parametrize("override", [
    {"ACCEPTANCE_RESET_TOKEN": "short"}, {"ACCEPTANCE_RESET_TOKEN": None},
    {"ACCEPTANCE_RESET_TOKEN": "baseline-admin-password"}, {"ACCEPTANCE_RUN_ID": "../other"},
    {"DATABASE_URL": "postgresql://postgres:owned-db-password@other:5432/app"},
    {"DATABASE_URL": "postgresql://postgres:owned-db-password@db:5432/production"},
    {"DATABASE_URL": "postgresql://postgres:owned-db-password@db:5432/app?host=other"},
    {"DEVELOP_WORKSPACE_ROOT": Path("/tmp/arbitrary")}, {"ACCEPTANCE_AGENT_ROOT": Path("/root")},
    {"ACCEPTANCE_RESET_TIMEOUT_SECONDS": 0},
])
def test_reset_settings_reject_unowned_scope(override):
    with pytest.raises(ValidationError):
        configuration(**override)


def test_production_configuration_stays_environment_backed(monkeypatch):
    monkeypatch.setattr(settings, "DEVELOP_ACCEPTANCE_RESET_ENABLED", False)
    assert reset_module.effective_repository() == (settings.DEMO_GITHUB_REPO, settings.DEMO_GITHUB_TOKEN)
    assert confined_environment({"HOME": "/ordinary-home"}) == {"HOME": "/ordinary-home"}


def test_authentication_and_body_scope_rejected_without_mutation(tmp_path, monkeypatch):
    control, controller, database = coordinator(tmp_path, monkeypatch)
    marker = control.workspace.root / "fixture"
    marker.write_text("keep")
    monkeypatch.setattr(testing_acceptance, "acceptance_reset", control)
    calls = []
    monkeypatch.setattr(control, "operate", lambda **kwargs: calls.append(kwargs) or control.state())
    app = FastAPI()
    app.include_router(testing_acceptance.router, prefix="/api/v1")
    client = TestClient(app)
    good = {"Authorization": "Bearer " + TOKEN, "X-Acceptance-Run": control.settings.ACCEPTANCE_RUN_ID}
    body = {"run_id": control.settings.ACCEPTANCE_RUN_ID, "reset_id": "one", "expected_generation": 0}
    for headers in ({}, {**good, "Authorization": "Bearer wrong"}, {**good, "X-Acceptance-Run": "other"}):
        assert client.post("/api/v1/testing/acceptance/reset", headers=headers, json=body).status_code in (401, 409)
    for bad in ({**body, "run_id": "other"}, {**body, "root": "/"}, {**body, "expected_generation": True}, {**body, "database": "other"}):
        assert client.post("/api/v1/testing/acceptance/reset", headers=good, json=bad).status_code in (409, 422)
    assert client.get("/api/v1/testing/acceptance/state", headers={"Authorization": "Bearer " + TOKEN}).status_code == 409
    assert client.get("/api/v1/testing/acceptance/state?root=/", headers=good).status_code == 422
    assert client.get("/api/v1/testing/acceptance/state", headers=good).json()["run_id"] == control.settings.ACCEPTANCE_RUN_ID
    assert not calls and marker.read_text() == "keep" and control.barrier.open
    assert TOKEN not in json.dumps(client.get("/api/v1/testing/acceptance/state", headers=good).json())
    assert controller.calls == []


def test_protected_http_state_observes_live_timing_override_and_verified_reset(tmp_path, monkeypatch):
    from app.api.routes import develop

    control, controller, database = coordinator(
        tmp_path, monkeypatch, DEVELOP_TURN_TIMEOUT_SECONDS=15, DEVELOP_TURN_PRESENCE_GRACE_SECONDS=0.3,
    )
    monkeypatch.setattr(testing_acceptance, "acceptance_reset", control)
    monkeypatch.setattr(testing_acceptance, "engine", database)
    monkeypatch.setattr(testing_agent, "settings", control.settings)
    monkeypatch.setattr(develop, "preview_controller", controller)
    app = FastAPI()
    app.include_router(testing_acceptance.router, prefix="/api/v1")
    app.include_router(testing_agent.router, prefix="/api/v1")
    app.add_middleware(AcceptanceAdmissionMiddleware, barrier=control.barrier, prefix="/api/v1")
    headers = {"Authorization": "Bearer " + TOKEN, "X-Acceptance-Run": control.settings.ACCEPTANCE_RUN_ID}
    baseline = {"timeout_seconds": 15, "grace_seconds": 0.3}
    override = {"timeout_seconds": 2, "grace_seconds": 1.0}
    with TestClient(app) as client:
        assert client.get("/api/v1/testing/acceptance/state", headers=headers).json()["timing"] == baseline
        response = client.post("/api/v1/testing/llm/turns/control", json=override)
        assert response.status_code == 200
        assert client.get("/api/v1/testing/acceptance/state", headers=headers).json()["timing"] == override
        response = client.post("/api/v1/testing/acceptance/reset", headers=headers, json={
            "run_id": control.settings.ACCEPTANCE_RUN_ID, "reset_id": "live-timing", "expected_generation": 0,
        })
        assert response.status_code == 200, response.json()
        assert response.json()["timing"] == baseline and response.json()["baseline_verified"]
        state = client.get("/api/v1/testing/acceptance/state", headers=headers).json()
        assert state["timing"] == baseline and state["generation"] == 1 and state["baseline_verified"]
        assert TOKEN not in json.dumps(state) and "password" not in json.dumps(state)


def test_disabled_auth_control_is_absent():
    control = AcceptanceResetCoordinator(configuration(DEVELOP_ACCEPTANCE_RESET_ENABLED=False))
    with pytest.raises(ControlError) as error:
        control.authenticate("Bearer " + TOKEN, control.settings.ACCEPTANCE_RUN_ID)
    assert error.value.status_code == 404


@pytest.mark.parametrize("deleted_admin", [False, True])
def test_database_restoration_is_canonical_and_preserves_migration(tmp_path, deleted_admin):
    cfg = configuration()
    database = sqlite_database(tmp_path)
    seed(database, cfg)
    if deleted_admin:
        with Session(database) as session:
            admin = session.exec(select(User).where(User.email == cfg.FIRST_SUPERUSER)).one()
            session.delete(admin)
            session.commit()
    snapshot = restore_database(database, cfg, monotonic() + 5)
    verify_database(database, cfg, snapshot)
    with Session(database) as session:
        user = session.exec(select(User)).one()
        assert verify_password(cfg.FIRST_SUPERUSER_PASSWORD, user.hashed_password)[0]
        assert user.is_active and user.is_superuser and user.concurrent_agent_turn_limit == cfg.DEVELOP_USER_CONCURRENT_TURN_LIMIT_DEFAULT
        assert session.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "baseline-revision"


def test_database_transaction_rolls_back_all_deletes_on_insert_failure(tmp_path):
    cfg = configuration()
    database = sqlite_database(tmp_path)
    seed(database, cfg)
    def fail(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith("INSERT INTO user"):
            raise RuntimeError("injected insert failure")
    event.listen(database, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError):
            restore_database(database, cfg, monotonic() + 5)
    finally:
        event.remove(database, "before_cursor_execute", fail)
    with Session(database) as session:
        assert len(session.exec(select(User)).all()) == 2
        assert len(session.exec(select(Item)).all()) == 1
        assert len(session.exec(select(DevelopmentChat)).all()) == 1
        assert len(session.exec(select(DevelopmentMessage)).all()) == 1


def test_storage_cleans_orphans_without_following_symlinks(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "sentinel").write_text("unchanged")
    (root / ".credential-orphan").mkdir()
    (root / ".credential-orphan" / "secret").write_text("old")
    (root / "orphan-checkout").mkdir()
    (root / "orphan-checkout" / "outside").symlink_to(outside, target_is_directory=True)
    (root / "link").symlink_to(outside, target_is_directory=True)
    storage = OwnedStorage(root, "owned")
    identity = root.stat().st_ino
    storage.clean(monotonic() + 2)
    storage.verify()
    assert root.stat().st_ino == identity
    assert (outside / "sentinel").read_text() == "unchanged"


def test_storage_rejects_root_and_marker_symlinks_and_owner_change(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(RuntimeError):
        OwnedStorage(alias, "owned").validate()
    (root / reset_module.OWNER_FILE).symlink_to(tmp_path / "unrelated")
    with pytest.raises(RuntimeError):
        OwnedStorage(root, "owned").validate()
    (root / reset_module.OWNER_FILE).unlink()
    (root / reset_module.OWNER_FILE).write_text('{"run_id":"other"}')
    with pytest.raises(RuntimeError):
        OwnedStorage(root, "owned").clean(monotonic() + 1)
    (root / reset_module.OWNER_FILE).unlink()
    os.mkfifo(root / reset_module.OWNER_FILE)
    with pytest.raises(RuntimeError):
        OwnedStorage(root, "owned").validate()


def test_environment_confines_home_xdg_temporary_and_config_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DEVELOP_ACCEPTANCE_MODE", True)
    monkeypatch.setattr(settings, "DEVELOP_ACCEPTANCE_RESET_ENABLED", True)
    monkeypatch.setattr(settings, "ACCEPTANCE_AGENT_ROOT", tmp_path)
    source = {"HOME": "/root", "XDG_CONFIG_HOME": "/outside", "TMPDIR": "/tmp", "OPENCODE_CONFIG": "/outside/config", "DEMO_GITHUB_TOKEN": "never-pass", "ACCEPTANCE_RESET_TOKEN": TOKEN, "DATABASE_URL": "never-pass"}
    confined = confined_environment(source)
    environment = minimal_agent_environment(source, provider_key="provider", provider_base_url=None)
    for key in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR", "TMPDIR"):
        assert Path(environment[key]).is_relative_to(tmp_path)
    assert "OPENCODE_CONFIG" not in confined and "DEMO_GITHUB_TOKEN" not in environment
    assert "ACCEPTANCE_RESET_TOKEN" not in confined and "DATABASE_URL" not in confined
    (tmp_path / "home").rmdir()
    (tmp_path / "home").symlink_to("/root", target_is_directory=True)
    with pytest.raises(RuntimeError):
        confined_environment(source)


def test_owned_scope_requires_complete_docker_attestation(tmp_path):
    cfg = configuration()
    control = AcceptanceResetCoordinator(cfg)
    control.workspace = OwnedStorage(tmp_path / "work", cfg.ACCEPTANCE_RUN_ID)
    control.agent = OwnedStorage(tmp_path / "agent", cfg.ACCEPTANCE_RUN_ID)
    control.workspace.root.mkdir()
    control.agent.root.mkdir()
    controller = Controller(cfg)
    database = SimpleNamespace(url=make_url(str(cfg.DATABASE_URL)))
    controller.ownership = {"verified": True, "project": cfg.ACCEPTANCE_RUN_ID}
    with pytest.raises(RuntimeError, match="Database ownership"):
        control._validate_ownership(controller, database, monotonic() + 1)
    assert not (control.workspace.root / reset_module.OWNER_FILE).exists()
    controller.ownership = attestation(cfg)
    control._validate_ownership(controller, database, monotonic() + 1)
    controller.ownership["services"]["db"] = "replacement"
    with pytest.raises(RuntimeError, match="identity changed"):
        control._validate_ownership(controller, database, monotonic() + 1)


def test_reset_verifies_every_baseline_and_safe_retries(tmp_path, monkeypatch):
    control, controller, database = coordinator(tmp_path, monkeypatch)
    seed(database, control.settings)
    (control.workspace.root / "orphan").write_text("old")
    (control.agent.root / "session").write_text("old")
    testing_agent.fake_llm_state.configure([testing_agent.FakeLlmReply(kind="text", text="old")])
    testing_agent.fake_llm_state.take({"old": "request"})
    control.configuration = "unavailable"
    control.settings.DEVELOP_TURN_TIMEOUT_SECONDS = 1
    result = reset(control, controller, database)
    assert result["phase"] == "ready" and result["generation"] == 1 and result["baseline_verified"]
    assert result["reset_id"] == "reset-1" and result["active_work"] == {}
    assert result["configuration"] == "available"
    assert [entry["phase"] for entry in result["phases"]] == [
        "validating_ownership", "quiescing", "cleaning_previews", "cleaning_files",
        "resetting_database", "restoring_controls", "verifying",
    ]
    assert all(entry["milliseconds"] >= 0 for entry in result["phases"])
    assert [action for action, _ in controller.calls] == ["quiesce", "reset", "resume"]
    assert reset(control, controller, database) == result
    assert len(controller.calls) == 3
    work = control.barrier.admit("scenario")
    try:
        assert not control.state()["baseline_verified"]
        for generation in (0, 1):
            with pytest.raises(ControlError, match="Stale reset"):
                reset(control, controller, database, generation=generation)
            assert not work.cancelled.is_set()
            assert control.barrier.counts() == {"scenario": 1}
            assert control.barrier.generation == 1
        assert control.barrier.open and len(controller.calls) == 3
    finally:
        control.barrier.finish(work)


def test_cached_retry_rejects_controller_process_replacement_without_recurring_cleanup(tmp_path, monkeypatch):
    control, controller, database = coordinator(tmp_path, monkeypatch)
    reset(control, controller, database)
    original = controller.acceptance_state
    monkeypatch.setattr(controller, "acceptance_state", lambda **kwargs: {**original(**kwargs), "boot_id": "replacement-boot"})
    with pytest.raises(ControlError, match="retry identity"):
        reset(control, controller, database)
    assert control.phase == "failed" and not control.barrier.open
    assert control.barrier.generation == 1 and len(controller.calls) == 3


def test_configuration_transition_preserves_real_database_and_files(tmp_path, monkeypatch):
    control, controller, database = coordinator(tmp_path, monkeypatch)
    reset(control, controller, database)
    (control.workspace.root / "fixture").write_text("keep")
    with Session(database) as session:
        user = session.exec(select(User)).one()
        item = Item(title="keep", owner_id=user.id)
        session.add(item)
        session.commit()
        item_id = item.id
    for mode in ("unavailable", "available"):
        result = reset(control, controller, database, reset_id=uuid.uuid4().hex, generation=1, mode=mode)
        assert result["configuration"] == mode and result["generation"] == 1
        assert (control.workspace.root / "fixture").read_text() == "keep"
        with Session(database) as session:
            assert session.get(Item, item_id).title == "keep"
    assert controller.calls[3][1]["operation"] == "configuration"
    for generation in (0, 1):
        with pytest.raises(ControlError):
            reset(control, controller, database, generation=generation)


def test_quiescing_phase_is_published_only_after_mutating_admissions_close(tmp_path, monkeypatch):
    control, controller, database = coordinator(tmp_path, monkeypatch)
    original_phase = control._phase

    def observe_phase(phase, deadline):
        if phase == "quiescing":
            assert not control.barrier.open
        original_phase(phase, deadline)

    monkeypatch.setattr(control, "_phase", observe_phase)
    reset(control, controller, database)


def test_actual_thread_finally_completion_precedes_cleanup(tmp_path, monkeypatch):
    control, controller, database = coordinator(tmp_path, monkeypatch)
    running, in_finally, release_finally = threading.Event(), threading.Event(), threading.Event()
    checkout = control.workspace.root / "active"
    checkout.write_text("old")
    work_ref = []
    def worker():
        work = current_work.get()
        work_ref.append(work)
        running.set()
        try:
            assert work.cancelled.wait(1)
        finally:
            in_finally.set()
            assert release_finally.wait(1)
            checkout.write_text("late completion")
    control.barrier.start_thread(worker, {})
    assert running.wait(1)
    result = []
    thread = threading.Thread(target=lambda: result.append(reset(control, controller, database)))
    thread.start()
    assert in_finally.wait(1)
    assert checkout.exists() and controller.calls == []
    assert control.state()["phase"] == "quiescing" and not control.barrier.open
    with pytest.raises(AdmissionClosed):
        control.barrier.admit("new setup")
    with pytest.raises(ControlError) as error:
        reset(control, controller, database, reset_id="conflicting")
    assert error.value.status_code == 409
    release_finally.set()
    thread.join(3)
    assert not thread.is_alive() and result[0]["baseline_verified"]
    assert not checkout.exists() and control.barrier.counts() == {}


def test_deadline_is_finite_fail_closed_and_cannot_late_reopen(tmp_path, monkeypatch):
    control, controller, database = coordinator(tmp_path, monkeypatch, ACCEPTANCE_RESET_TIMEOUT_SECONDS=0.05)
    work = control.barrier.admit("stuck-provider")
    (control.workspace.root / "keep").write_text("still dirty")
    started = monotonic()
    with pytest.raises(ControlError) as error:
        reset(control, controller, database)
    assert monotonic() - started < 0.5 and error.value.status_code in (503, 504)
    assert control.phase == "failed" and not control.barrier.open and controller.calls == []
    control.barrier.finish(work)
    if control._operation:
        control._operation.join(1)
    assert control.phase == "failed" and not control.barrier.open
    assert (control.workspace.root / "keep").exists()
    with pytest.raises(ControlError):
        reset(control, controller, database, reset_id="again")


@pytest.mark.parametrize("failure", ["reset", "resume", "files", "database", "verification"])
def test_partial_failure_never_acknowledges_or_exposes_secrets(tmp_path, monkeypatch, failure):
    control, controller, database = coordinator(tmp_path, monkeypatch)
    if failure in ("reset", "resume"):
        controller.fail = failure
    elif failure == "files":
        monkeypatch.setattr(control.workspace, "clean", lambda deadline: (_ for _ in ()).throw(OSError(TOKEN)))
    elif failure == "database":
        monkeypatch.setattr(reset_module, "restore_database", lambda *args: (_ for _ in ()).throw(RuntimeError(TOKEN)))
    else:
        monkeypatch.setattr(reset_module, "verify_database", lambda *args: (_ for _ in ()).throw(RuntimeError(TOKEN)))
    with pytest.raises(ControlError) as error:
        reset(control, controller, database)
    assert TOKEN not in str(error.value)
    assert control.phase == "failed" and not control.baseline_verified and not control.barrier.open
    assert control.barrier.generation == 0 and control._cached is None
    assert control.failure_phase == {"reset": "cleaning_previews", "resume": "verifying", "files": "cleaning_files", "database": "resetting_database", "verification": "verifying"}[failure]


def test_asgi_request_tracks_response_stream_and_generator_finally():
    barrier = WorkBarrier()
    events = []
    def content():
        try:
            events.append("yield")
            yield "one"
        finally:
            events.append("finally")
    source = content()
    async def app(scope, receive, send):
        response = CompletionStreamingResponse(source)
        await response(scope, receive, send)
        events.append("app-finally")
    middleware = AcceptanceAdmissionMiddleware(app, barrier=barrier, prefix="/api/v1")
    async def execute():
        async def receive():
            await anyio.sleep_forever()
        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                assert barrier.counts() == {"http": 1}
                raise OSError("client disconnected")
        with pytest.raises(ClientDisconnect):
            await middleware({"type": "http", "path": "/api/v1/develop/chats", "asgi": {"spec_version": "2.4"}}, receive, send)
    asyncio.run(execute())
    assert events == ["yield", "finally"] and barrier.counts() == {}


def test_asgi_sync_thread_and_dependency_finally_are_joined():
    barrier = WorkBarrier()
    entered, cancelled, release = threading.Event(), threading.Event(), threading.Event()
    async def app(_scope, _receive, _send):
        def sync_request():
            work = current_work.get()
            entered.set()
            assert work.cancelled.wait(1)
            try:
                cancelled.set()
            finally:
                assert release.wait(1)
        await anyio.to_thread.run_sync(sync_request)
    middleware = AcceptanceAdmissionMiddleware(app, barrier=barrier, prefix="/api/v1")
    async def execute():
        async def noop(*args):
            pass
        task = asyncio.create_task(middleware({"type": "http", "path": "/api/v1/users"}, noop, noop))
        await anyio.to_thread.run_sync(entered.wait, 1)
        barrier.close()
        await anyio.to_thread.run_sync(cancelled.wait, 1)
        with pytest.raises(TimeoutError):
            await anyio.to_thread.run_sync(barrier.drain, monotonic() + 0.02)
        release.set()
        await task
        barrier.drain(monotonic() + 1)
    asyncio.run(execute())
    assert barrier.counts() == {}


def test_turn_timers_are_joined_before_capacity_baseline():
    manager = DevelopTurnManager()
    turn = manager.start_turn(chat_id=uuid.uuid4(), user_id=uuid.uuid4(), user_limit=2,
                              presence_mode="continue_in_background", replay_limit=20, timeout_seconds=20)
    manager.cancel_all()
    assert turn.cancel_event.is_set()
    manager.finish_turn(turn, TurnTerminalState.stopped)
    manager.drain(monotonic() + 1)
    assert not any(timer.is_alive() for timer in turn._timers)
    assert not manager._active_by_user


@pytest.mark.parametrize(("acceptance_mode", "reset_enabled"), [("true", "false"), ("false", "false"), ("false", "true")])
def test_reset_routes_are_not_registered_without_explicit_opt_in(acceptance_mode, reset_enabled):
    env = dict(os.environ)
    env.update(DEVELOP_ACCEPTANCE_MODE=acceptance_mode, DEVELOP_ACCEPTANCE_RESET_ENABLED=reset_enabled,
               DEVELOP_FAKE_SETUP_RUNNER="true", OPENAI_BASE_URL="http://127.0.0.1:8000/api/v1/testing/llm/v1")
    script = """
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.main import api_router
app = FastAPI()
app.include_router(api_router, prefix='/api/v1')
with TestClient(app) as client:
    for method, path in [('GET','state'),('POST','reset'),('PATCH','configuration')]:
        response = client.request(method, '/api/v1/testing/acceptance/' + path)
        assert response.status_code == 404, response.status_code
"""
    subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).parents[2], env=env, check=True, capture_output=True, timeout=20)


def test_preview_fetch_drain_keeps_health_available_and_joins_actual_rpc(monkeypatch):
    import httpx
    from fastapi import Request

    from app.api.routes import develop

    monkeypatch.setattr(settings, "DEVELOP_ACCEPTANCE_MODE", True)
    monkeypatch.setattr(settings, "DEVELOP_ACCEPTANCE_RESET_ENABLED", True)
    chat_id = uuid.uuid4()
    monkeypatch.setattr(develop, "_require_browser_host", lambda request: "http://preview")
    monkeypatch.setattr(develop, "_service_host", lambda request: None)
    monkeypatch.setattr(develop, "_browser_claims", lambda credential, session: chat_id)
    entered, release = threading.Event(), threading.Event()
    barrier = WorkBarrier()
    def fetch(*args):
        assert args[0] == chat_id
        assert current_work.get().kind == "http"
        entered.set()
        assert release.wait(1)
        return {"content_type": "text/plain", "body": b"old", "status": 200}
    monkeypatch.setattr(develop.preview_controller, "fetch", fetch)
    app = FastAPI()
    @app.get("/old-preview")
    async def preview(request: Request):
        return await develop.browser_preview_resource(request=request, session=None, chat_id=chat_id, asset_path="")
    @app.get("/api/v1/utils/health-check/")
    def health():
        return True
    app.add_middleware(AcceptanceAdmissionMiddleware, barrier=barrier, prefix="/api/v1")
    async def execute():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            task = asyncio.create_task(client.get("/old-preview"))
            assert await anyio.to_thread.run_sync(entered.wait, 1)
            barrier.close()
            assert (await asyncio.wait_for(client.get("/api/v1/utils/health-check/"), timeout=0.3)).status_code == 200
            with pytest.raises(TimeoutError):
                await anyio.to_thread.run_sync(barrier.drain, monotonic() + 0.02)
            release.set()
            assert (await task).content == b"old"
            barrier.drain(monotonic() + 1)
    asyncio.run(execute())


def test_provider_request_is_actually_cancelled_and_drained_before_reply_reset(monkeypatch):
    import httpx

    barrier = WorkBarrier()
    started = threading.Event()
    original_take = testing_agent.fake_llm_state.take
    def take(request):
        reply = original_take(request)
        started.set()
        return reply
    monkeypatch.setattr(testing_agent.fake_llm_state, "take", take)
    testing_agent.fake_llm_state.configure([testing_agent.FakeLlmReply(kind="delay", text="old", delay_seconds=30)])
    app = FastAPI()
    app.include_router(testing_agent.router, prefix="/api/v1")
    app.add_middleware(AcceptanceAdmissionMiddleware, barrier=barrier, prefix="/api/v1")
    async def execute():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            task = asyncio.create_task(client.post("/api/v1/testing/llm/v1/responses", json={"input": "old"}))
            assert await anyio.to_thread.run_sync(started.wait, 1)
            assert barrier.counts() == {"provider": 1}
            barrier.close()
            response = await asyncio.wait_for(task, timeout=1)
            await anyio.to_thread.run_sync(barrier.drain, monotonic() + 1)
            assert response.status_code == 503
            assert testing_agent.fake_llm_state.requests()
            testing_agent.fake_llm_state.configure([])
            assert testing_agent.fake_llm_state.baseline_verified()
    asyncio.run(execute())


def test_exited_agent_process_does_not_complete_until_pipe_callback_finally_joins(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DEVELOP_ACCEPTANCE_MODE", True)
    monkeypatch.setattr(settings, "DEVELOP_ACCEPTANCE_RESET_ENABLED", True)
    barrier = WorkBarrier()
    callback_entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    completion = tmp_path / "late-completion"
    def on_line(line):
        assert line == "real-output"
        callback_entered.set()
        try:
            assert release.wait(2)
        finally:
            completion.write_text("complete")
    def execute():
        AgentCommandRunner().run([sys.executable, "-c", "print('real-output')"], cwd=tmp_path,
                                 env=dict(os.environ), timeout_seconds=2, on_stdout_line=on_line)
        returned.set()
    thread = barrier.start_thread(execute, {})
    assert callback_entered.wait(1)
    barrier.close()
    with pytest.raises(TimeoutError):
        barrier.drain(monotonic() + 0.02)
    assert not returned.is_set() and not completion.exists()
    release.set()
    thread.join(2)
    barrier.drain(monotonic() + 1)
    assert completion.read_text() == "complete" and returned.is_set()


def test_websocket_cancellation_joins_child_finally_before_request_removal():
    barrier = WorkBarrier()
    entered, closing, release = threading.Event(), threading.Event(), threading.Event()
    async def app(_scope, _receive, _send):
        async def child():
            entered.set()
            try:
                await anyio.sleep_forever()
            finally:
                closing.set()
                with anyio.CancelScope(shield=True):
                    assert await anyio.to_thread.run_sync(release.wait, 1)
        async with anyio.create_task_group() as group:
            group.start_soon(child)
    middleware = AcceptanceAdmissionMiddleware(app, barrier=barrier, prefix="/api/v1")
    async def execute():
        async def noop(*args):
            pass
        task = asyncio.create_task(middleware({"type": "websocket", "path": "/api/v1/develop/socket"}, noop, noop))
        assert await anyio.to_thread.run_sync(entered.wait, 1)
        barrier.close()
        assert await anyio.to_thread.run_sync(closing.wait, 1)
        with pytest.raises(TimeoutError):
            await anyio.to_thread.run_sync(barrier.drain, monotonic() + 0.02)
        release.set()
        await task
        assert barrier.counts() == {}
    asyncio.run(execute())


def test_controller_http_client_uses_independent_header_and_bounded_body(monkeypatch, tmp_path):
    import httpx

    cfg = configuration()
    for field in ("DEVELOP_ACCEPTANCE_MODE", "DEVELOP_ACCEPTANCE_RESET_ENABLED", "ACCEPTANCE_RUN_ID", "ACCEPTANCE_RESET_TOKEN"):
        monkeypatch.setattr(settings, field, getattr(cfg, field))
    captured = []
    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"run_id": cfg.ACCEPTANCE_RUN_ID})
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)))
    client = PreviewController(root=tmp_path, url="http://preview-controller:8090")
    client.acceptance_control("resume", run_id=cfg.ACCEPTANCE_RUN_ID, reset_id="one", expected_generation=0,
                              timeout_seconds=1.5, generation=1, baseline_verified=True)
    request = captured[0]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["X-Acceptance-Run"] == cfg.ACCEPTANCE_RUN_ID
    assert TOKEN not in str(request.url) and TOKEN not in request.content.decode()
    assert json.loads(request.content)["timeout_seconds"] == 1.5
    with pytest.raises(ValueError):
        client.acceptance_control("arbitrary", run_id="other", reset_id="one", expected_generation=0, timeout_seconds=1)

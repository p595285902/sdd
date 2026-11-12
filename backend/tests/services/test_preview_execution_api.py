import threading
import uuid
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.api import deps
from app.api.routes import develop
from app.models import DevelopmentChat, DevelopmentMessage, PreviewExecution, User
from app.services.preview_execution_lifecycle import PreviewExecutionLifecycle
from app.services.preview_executions import (
    PreviewEventInput,
    append_events,
    read_events,
    set_terminal_status,
)
from tests.services.test_preview_executions import chat_id as chat_id
from tests.services.test_preview_executions import preview_engine as preview_engine


class ApiController:
    def __init__(self) -> None:
        self.launches: list[tuple[uuid.UUID, dict[str, Any], str]] = []
        self.stops: list[uuid.UUID] = []
        self.runtime: dict[str, Any] = {"state": "stopped"}
        self.journal: dict[str, Any] = {
            "events": [],
            "state": "starting",
            "ready": False,
        }

    def status(self, _chat_id: uuid.UUID) -> dict[str, Any]:
        return self.runtime

    def native_launch(
        self, chat: uuid.UUID, plan: dict[str, Any], execution: str
    ) -> dict[str, Any]:
        self.launches.append((chat, plan, execution))
        self.runtime = {
            "state": "starting",
            "runtime": "native-compose",
            "execution_id": execution,
        }
        self.journal = {
            "events": [],
            "state": "starting",
            "ready": False,
            "execution_id": execution,
        }
        return self.runtime

    def stop(self, chat: uuid.UUID) -> dict[str, Any]:
        self.stops.append(chat)
        self.runtime = {"state": "stopped"}
        return self.runtime

    def events(self, _chat: uuid.UUID, _after: int) -> dict[str, Any]:
        return self.journal


class NativePlan:
    def as_dict(self) -> dict[str, Any]:
        return {
            "runtime": "native-compose",
            "commands": [
                {
                    "cwd": ".",
                    "argv": ["docker", "compose", "watch"],
                    "env": {},
                    "source": {"path": "README.md", "line": 1},
                }
            ],
            "application": {"port": 18080},
            "sources": [{"path": "README.md"}],
        }


@pytest.fixture
def api_environment(
    preview_engine: Engine,
    chat_id: uuid.UUID,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, ApiController, uuid.UUID, Path]]:
    root = tmp_path / "workspaces"
    checkout = root / str(chat_id)
    checkout.mkdir(parents=True)
    (checkout / "README.md").write_text("docker compose watch\n", encoding="utf-8")
    with Session(preview_engine) as session, session.begin():
        chat = session.get(DevelopmentChat, chat_id)
        chat.workspace_ready = True
        owner = session.get(User, chat.owner_id)
        session.expunge(owner)
    controller = ApiController()
    lifecycle = PreviewExecutionLifecycle(preview_engine, controller)
    monkeypatch.setattr(develop, "preview_controller", controller)
    monkeypatch.setattr(develop, "preview_lifecycle", lifecycle)
    monkeypatch.setattr(lifecycle, "start", lambda: None)
    monkeypatch.setattr(lifecycle, "stop", lambda: None)
    monkeypatch.setattr(
        develop, "resolve_native_plan", lambda *_args, **_kwargs: NativePlan()
    )
    monkeypatch.setattr(develop.settings, "DEVELOP_WORKSPACE_ROOT", root)

    def get_session() -> Generator[Session]:
        with Session(preview_engine) as session:
            yield session

    app = FastAPI()
    app.include_router(develop.router)
    app.dependency_overrides[deps.get_db] = get_session
    app.dependency_overrides[deps.get_current_user] = lambda: owner
    with TestClient(app) as client:
        yield client, controller, chat_id, checkout


def test_launch_owns_durable_operation_before_runtime_and_no_assistant_turn(
    api_environment, preview_engine: Engine
) -> None:
    client, controller, chat_id, _checkout = api_environment
    result = client.post(f"/develop/chats/{chat_id}/preview/launch", json={})
    assert result.status_code == 200
    execution = result.json()["execution"]
    assert execution["chat_id"] == str(chat_id)
    assert execution["status"] == "starting" and not execution["ready"]
    assert execution["workflow"]["runtime"] == "native-compose"
    assert len(controller.launches) == 1
    assert controller.launches[0][2] == execution["id"]
    assert (
        client.post(f"/develop/chats/{chat_id}/preview/launch", json={}).json()[
            "execution"
        ]["id"]
        == execution["id"]
    )
    assert len(controller.launches) == 1
    with Session(preview_engine) as session:
        assert len(session.exec(select(PreviewExecution)).all()) == 1
        assert session.exec(select(DevelopmentMessage)).all() == []


def test_legacy_launch_receives_durable_execution_id_and_preserves_api_entrypoint(
    api_environment, preview_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, controller, chat_id, _checkout = api_environment
    payload = {
        "setup": [], "website": None,
        "api": {"cwd": ".", "argv": ["python", "-m", "app"], "port": 8765, "path": "/health"},
    }
    starts, launches = [], []
    monkeypatch.setattr(develop, "resolve_native_plan", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(develop, "resolve_preview_plan", lambda **_kwargs: SimpleNamespace(website=None, model_dump=lambda: dict(payload)))
    monkeypatch.setattr(develop, "classify_workspace", lambda **_kwargs: SimpleNamespace(kind="api_documentation", entry_point="/docs"))
    monkeypatch.setattr(develop.settings, "OPENAI_API_KEY", SecretStr("local-unit-provider-key"))
    monkeypatch.setattr(controller, "start", lambda chat: starts.append(chat), raising=False)

    def launch(chat, raw):
        with Session(preview_engine) as session:
            execution = session.get(PreviewExecution, uuid.UUID(raw["execution_id"]))
            assert execution is not None and execution.chat_id == chat
            assert execution.workflow_snapshot["initial_path"] == "/docs"
        launches.append(raw)
        return {"state": "starting"}

    monkeypatch.setattr(controller, "launch", launch, raising=False)
    result = client.post(f"/develop/chats/{chat_id}/preview/launch", json={})
    assert result.status_code == 200
    execution_id = result.json()["execution"]["id"]
    assert starts == [chat_id]
    assert launches[0]["execution_id"] == execution_id
    assert launches[0]["initial_path"] == "/docs"
    assert launches[0]["api"] == payload["api"]
    retry = client.post(f"/develop/chats/{chat_id}/preview/launch", json={})
    assert retry.json()["execution"]["id"] == execution_id
    assert len(launches) == 1 and len(starts) == 1


def test_visible_activity_accepts_native_status_metadata(api_environment, monkeypatch) -> None:
    client, controller, chat_id, _checkout = api_environment
    status = {
        "state": "running", "ready": True, "cursor": 211, "dropped_bytes": 0,
        "details": {"initial_port": "8765", "initial_path": "/"},
        "routes": {"8765": {"service": "website", "target": 8765}},
    }
    calls = []

    def activity(chat):
        calls.append(chat)
        return status

    monkeypatch.setattr(controller, "activity", activity, raising=False)
    response = client.post(f"/develop/chats/{chat_id}/preview/activity")
    assert response.status_code == 200
    assert response.json() == status
    assert calls == [chat_id]
    assert not controller.launches


def test_concurrent_launch_requests_reattach_to_single_runtime(api_environment) -> None:
    client, controller, chat_id, _checkout = api_environment
    barrier = threading.Barrier(2)
    responses: list[Any] = []

    def launch() -> None:
        barrier.wait(timeout=5)
        responses.append(
            client.post(f"/develop/chats/{chat_id}/preview/launch", json={})
        )

    workers = [threading.Thread(target=launch) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
    assert all(not worker.is_alive() for worker in workers)
    assert [response.status_code for response in responses] == [200, 200]
    assert len({response.json()["execution"]["id"] for response in responses}) == 1
    assert len(controller.launches) == 1


def test_restart_stops_old_attempt_records_reason_and_creates_new_one(
    api_environment, preview_engine: Engine
) -> None:
    client, controller, chat_id, _checkout = api_environment
    first = client.post(f"/develop/chats/{chat_id}/preview/launch", json={}).json()[
        "execution"
    ]
    second_response = client.post(f"/develop/chats/{chat_id}/preview/restart")
    assert second_response.status_code == 200
    second = second_response.json()["execution"]
    assert second["id"] != first["id"]
    assert controller.stops == [chat_id]
    assert len(controller.launches) == 2
    with Session(preview_engine) as session:
        old = session.get(PreviewExecution, uuid.UUID(first["id"]))
        assert old.status == "stopped"
        assert "Restart" in read_events(session, old.id)[-1].payload["reason"]


@pytest.mark.parametrize("gap", [False, True])
def test_restart_drains_all_stopped_pages_before_replacing_owner(
    api_environment, preview_engine: Engine, monkeypatch, gap
) -> None:
    client, controller, chat_id, _checkout = api_environment
    first = client.post(f"/develop/chats/{chat_id}/preview/launch", json={}).json()["execution"]
    start = 201 if gap else 1
    events = ([{"cursor": 1, "kind": "gap", "payload": {"through_cursor": 200}}] if gap else [])
    events += [{"cursor": cursor, "kind": "stdout", "payload": {"text": f"output {cursor}"}} for cursor in range(start, 301)]
    events += [
        {"cursor": 301, "kind": "command_exit", "payload": {"command": 0, "exit_code": 0}},
        {"cursor": 302, "kind": "status", "payload": {"status": "stopped", "ready": False}},
    ]
    cursors = []

    def paged_events(_chat, after):
        cursors.append(after)
        return {"execution_id": first["id"], "cursor": 302,
                "events": [event for event in events if event["cursor"] > after][:99]}

    monkeypatch.setattr(controller, "events", paged_events)
    response = client.post(f"/develop/chats/{chat_id}/preview/restart")
    assert response.status_code == 200
    assert response.json()["execution"]["id"] != first["id"]
    assert len(cursors) >= 2
    with Session(preview_engine) as session:
        old = session.get(PreviewExecution, uuid.UUID(first["id"]))
        assert old.controller_cursor == 302 and old.status == "stopped"
        retained = read_events(session, old.id, limit=1000)
        assert any(event.kind == "command_exit" and event.payload["exit_code"] == 0 for event in retained)
        assert any(event.payload.get("text") == "output 300" for event in retained)
        assert "Restart" in retained[-1].payload["reason"]


def test_context_and_status_do_not_launch_resolve_remote_or_create_attempt(
    api_environment, preview_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, controller, chat_id, _checkout = api_environment

    def forbidden(*_args, **_kwargs):
        pytest.fail("Read-only request invoked a model or runtime mutation")

    monkeypatch.setattr(develop, "resolve_preview_plan", forbidden)
    for endpoint in ("context", "status"):
        response = client.get(f"/develop/chats/{chat_id}/preview/{endpoint}")
        assert response.status_code == 200
        assert response.json()["state"] == "stopped"
    assert not controller.launches and not controller.stops
    with Session(preview_engine) as session:
        assert not session.exec(select(PreviewExecution)).all()


def test_missing_instructions_and_answer_are_operation_only_and_save_without_launch(
    api_environment, preview_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, controller, chat_id, _checkout = api_environment
    monkeypatch.setattr(develop, "resolve_native_plan", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(develop.settings, "OPENAI_API_KEY", None)
    failed = client.post(f"/develop/chats/{chat_id}/preview/launch", json={})
    assert failed.status_code == 200
    assert failed.json()["state"] == "needs_instructions"
    assert failed.json()["execution"]["status"] == "failed"
    saved = client.post(
        f"/develop/chats/{chat_id}/preview/launch",
        json={"answer": "docker compose watch", "pointer": "docs/development.md"},
    )
    assert saved.status_code == 200 and saved.json()["state"] == "stopped"
    assert not controller.launches
    received: list[dict[str, Any]] = []

    def resolve(*_args, **kwargs):
        received.append(kwargs)
        return NativePlan()

    monkeypatch.setattr(develop, "resolve_native_plan", resolve)
    launched = client.post(f"/develop/chats/{chat_id}/preview/launch", json={})
    assert launched.status_code == 200
    assert received == [
        {"pointer": "docs/development.md", "answer": "docker compose watch"}
    ]
    assert len(controller.launches) == 1
    with Session(preview_engine) as session:
        assert not session.exec(select(DevelopmentMessage)).all()


def test_owner_scope_covers_launch_restart_status_context_history_events_stream(
    api_environment, preview_engine: Engine
) -> None:
    client, _controller, owned_chat_id, _checkout = api_environment
    execution_id = client.post(
        f"/develop/chats/{owned_chat_id}/preview/launch", json={}
    ).json()["execution"]["id"]
    with Session(preview_engine) as session, session.begin():
        outsider = User(email="outsider@example.test", hashed_password="unused")
        session.add(outsider)
        session.flush()
        other_chat = DevelopmentChat(
            owner_id=outsider.id, title="Other", workspace_ready=True
        )
        session.add(other_chat)
        session.flush()
        other_id = other_chat.id
    for endpoint in ("launch", "restart", "start"):
        assert (
            client.post(
                f"/develop/chats/{other_id}/preview/{endpoint}", json={}
            ).status_code
            == 404
        )
    for endpoint in (
        "context",
        "status",
        "executions",
        f"executions/{execution_id}/events",
        f"executions/{execution_id}/stream",
    ):
        assert (
            client.get(f"/develop/chats/{other_id}/preview/{endpoint}").status_code
            == 404
        )
    assert (
        client.get(
            f"/develop/chats/{owned_chat_id}/preview/executions/{uuid.uuid4()}/events"
        ).status_code
        == 404
    )


def test_history_event_cursor_and_sse_use_already_durable_rows(
    api_environment, preview_engine: Engine
) -> None:
    client, _controller, chat_id, _checkout = api_environment
    execution_id = uuid.UUID(
        client.post(f"/develop/chats/{chat_id}/preview/launch", json={}).json()[
            "execution"
        ]["id"]
    )
    with Session(preview_engine) as session, session.begin():
        append_events(
            session,
            execution_id,
            [PreviewEventInput(1, "stdout", {"text": "hello <script>"})],
        )
        set_terminal_status(session, execution_id, "stopped", reason="idle expired")
    history = client.get(f"/develop/chats/{chat_id}/preview/executions").json()["data"]
    assert history[0]["id"] == str(execution_id)
    assert history[0]["status"] == "stopped"
    events_url = f"/develop/chats/{chat_id}/preview/executions/{execution_id}"
    page = client.get(events_url + "/events?after=1").json()
    assert [event["sequence"] for event in page["data"]] == [2, 3]
    assert not page["has_more"] and page["next_sequence"] == 3
    stream = client.get(events_url + "/stream?after=2")
    assert stream.status_code == 200
    assert "event: preview-event\n" in stream.text and "id: 3\n" in stream.text
    assert "id: 2\n" not in stream.text
    assert client.get(events_url + "/events?after=-1").status_code == 422


def test_workflow_command_metadata_redacted_but_runtime_receives_original_plan(
    api_environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, controller, chat_id, checkout = api_environment
    (checkout / ".env").write_text(
        "DATABASE_PASSWORD=project-credential\nPORT=18080\n", encoding="utf-8"
    )

    class PlanWithSecret(NativePlan):
        def as_dict(self):
            plan = super().as_dict()
            plan["commands"][0]["argv"] += ["--password=project-credential"]
            return plan

    monkeypatch.setattr(
        develop, "resolve_native_plan", lambda *_args, **_kwargs: PlanWithSecret()
    )
    result = client.post(f"/develop/chats/{chat_id}/preview/launch", json={})
    assert result.status_code == 200
    assert "project-credential" not in result.text
    assert "project-credential" in str(controller.launches[0][1])
    assert result.json()["execution"]["workflow"]["application"]["port"] == 18080

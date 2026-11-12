import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from app.models import PreviewExecution
from app.services.acceptance_work import WorkBarrier
from app.services.preview_execution_lifecycle import (
    PreviewExecutionLifecycle,
    known_secret_redactor,
)
from app.services.preview_executions import (
    PreviewEventInput,
    append_events,
    read_events,
    set_terminal_status,
)
from tests.services.test_preview_executions import _create
from tests.services.test_preview_executions import chat_id as chat_id
from tests.services.test_preview_executions import preview_engine as preview_engine


class FakeController:
    def __init__(self) -> None:
        self.result: dict[str, Any] = {"events": [], "state": "running", "ready": False}
        self.missing = False
        self.calls: list[tuple[uuid.UUID, int]] = []

    def events(self, chat: uuid.UUID, after: int) -> dict[str, Any]:
        self.calls.append((chat, after))
        if self.missing:
            request = httpx.Request("GET", "http://controller/events")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("missing", request=request, response=response)
        return self.result


def test_collector_commits_output_and_readiness_independently_of_watch(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    execution_id = _create(preview_engine, chat_id)
    controller = FakeController()
    controller.result = {
        "execution_id": str(execution_id),
        "state": "running",
        "ready": True,
        "events": [
            {
                "cursor": 1,
                "kind": "command_start",
                "payload": {"argv": ["compose", "watch"]},
            },
            {"cursor": 2, "kind": "stdout", "payload": {"text": "building"}},
            {
                "cursor": 3,
                "kind": "status",
                "payload": {"status": "running", "ready": True},
            },
        ],
    }
    lifecycle = PreviewExecutionLifecycle(preview_engine, controller)
    lifecycle.collect(execution_id)
    lifecycle.collect(execution_id)
    with Session(preview_engine) as session:
        execution = session.get(PreviewExecution, execution_id)
        assert (
            execution is not None and execution.status == "running" and execution.ready
        )
        assert execution.finished_at is None
        assert execution.controller_cursor == 3
        assert len(read_events(session, execution_id)) == 4
    assert controller.calls == [(chat_id, 0), (chat_id, 3)]


def test_missing_runtime_reconciles_interrupted_without_launch_or_reprovision(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    execution_id = _create(preview_engine, chat_id)
    controller = FakeController()
    controller.missing = True
    lifecycle = PreviewExecutionLifecycle(
        preview_engine, controller, launch_grace_seconds=0
    )
    lifecycle.scan_once()
    with Session(preview_engine) as session:
        execution = session.get(PreviewExecution, execution_id)
        assert execution is not None and execution.status == "interrupted"
        events = read_events(session, execution_id)
        assert events[-1].payload["status"] == "interrupted"
        assert "missing" in events[-1].payload["reason"]
    lifecycle.scan_once()
    assert controller.calls == [(chat_id, 0)]


def test_fresh_unprovisioned_creation_has_short_reconciliation_grace(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    execution_id = _create(preview_engine, chat_id)
    controller = FakeController()
    controller.missing = True
    PreviewExecutionLifecycle(preview_engine, controller).collect(execution_id)
    with Session(preview_engine) as session:
        assert session.get(PreviewExecution, execution_id).status == "starting"


def test_stale_runtime_identity_never_attaches_another_attempts_events(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    execution_id = _create(preview_engine, chat_id)
    controller = FakeController()
    controller.result = {
        "execution_id": str(uuid.uuid4()),
        "events": [
            {"cursor": 1, "kind": "stdout", "payload": {"text": "wrong runtime"}},
        ],
    }
    PreviewExecutionLifecycle(
        preview_engine, controller, launch_grace_seconds=0
    ).collect(execution_id)
    with Session(preview_engine) as session:
        assert session.get(PreviewExecution, execution_id).status == "interrupted"
        assert "wrong runtime" not in str(
            [event.payload for event in read_events(session, execution_id)]
        )


def test_stream_replays_only_committed_events_after_cursor_and_finishes_terminal(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    execution_id = _create(preview_engine, chat_id)
    with Session(preview_engine) as session, session.begin():
        execution = session.get(PreviewExecution, execution_id)
        owner_id = execution.chat.owner_id
        append_events(
            session,
            execution_id,
            [PreviewEventInput(1, "stdout", {"text": "<script>safe text</script>"})],
        )
        set_terminal_status(session, execution_id, "stopped", reason="idle expired")
    lifecycle = PreviewExecutionLifecycle(preview_engine, FakeController())
    frames = list(lifecycle.stream(chat_id, execution_id, owner_id, after=1))
    assert len(frames) == 2
    assert all("event: preview-event\n" in frame for frame in frames)
    assert '"kind":"stdout"' in frames[0]
    assert "id: 2\n" in frames[0]
    assert '"status":"stopped"' in frames[-1]
    assert list(lifecycle.stream(chat_id, execution_id, uuid.uuid4(), after=0)) == []


@pytest.mark.parametrize("commit", [False, True])
def test_stream_never_delivers_uncommitted_or_rolled_back_output(
    preview_engine: Engine, chat_id: uuid.UUID, commit: bool
) -> None:
    execution_id = _create(preview_engine, chat_id)
    lifecycle = PreviewExecutionLifecycle(preview_engine, FakeController(), poll_interval=0)
    with Session(preview_engine) as writer:
        owner_id = writer.get(PreviewExecution, execution_id).chat.owner_id
        append_events(writer, execution_id, [
            PreviewEventInput(1, "stdout", {"text": "transactional output"})
        ])
        stream = lifecycle.stream(chat_id, execution_id, owner_id, after=1)
        try:
            # append_events has flushed, but the independent reader must not
            # expose this event until its writer's transaction commits.
            assert next(stream) == ": heartbeat\n\n"
            if commit:
                writer.commit()
                frame = next(stream)
                assert "id: 2\n" in frame and '"text":"transactional output"' in frame
            else:
                writer.rollback()
                assert next(stream) == ": heartbeat\n\n"
        finally:
            stream.close()


def test_reset_barrier_cancels_and_drains_collector_without_late_writes(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    execution_id = _create(preview_engine, chat_id)
    entered, release = threading.Event(), threading.Event()
    controller = FakeController()

    def blocked_events(_chat: uuid.UUID, _after: int) -> dict[str, Any]:
        entered.set()
        assert release.wait(5)
        return {
            "events": [
                {"cursor": 1, "kind": "stdout", "payload": {"text": "late output"}}
            ],
            "state": "running",
        }

    controller.events = blocked_events
    barrier = WorkBarrier()
    lifecycle = PreviewExecutionLifecycle(
        preview_engine, controller, barrier=barrier, poll_interval=0.01
    )
    lifecycle.start()
    try:
        assert entered.wait(5)
        assert barrier.counts() == {"preview-reconciliation": 1}
        barrier.close()
        release.set()
        barrier.drain(time.monotonic() + 5)
        assert barrier.counts() == {}
        with Session(preview_engine) as session:
            assert len(read_events(session, execution_id)) == 1
    finally:
        release.set()
        lifecycle.stop()


def test_known_secrets_cover_inline_env_default_and_explicit_env_files(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text("PASSWORD=default-secret\n", encoding="utf-8")
    (tmp_path / "service.env").write_text("TOKEN='file-secret'\n", encoding="utf-8")
    (tmp_path / "override.env").write_text('API_KEY="flag-secret"\n', encoding="utf-8")
    (tmp_path / "compose.yml").write_text(
        "services:\n  app:\n    env_file: service.env\n    environment:\n      API_KEY: literal-secret\n      PORT: 8765\n      DB_HOST: db\n",
        encoding="utf-8",
    )
    plan = {
        "commands": [
            {
                "cwd": ".",
                "argv": ["docker", "compose", "--env-file", "override.env", "watch"],
                "env": {"SECRET": "inline-secret"},
            }
        ]
    }
    redactor = known_secret_redactor(tmp_path, plan)
    for value in (
        "default-secret",
        "file-secret",
        "flag-secret",
        "inline-secret",
        "literal-secret",
    ):
        assert redactor.redact(value) == "[REDACTED]"
    assert redactor.redact("db:8765") == "db:8765"


def test_documented_environment_preparation_precedes_file_existence_validation(tmp_path):
    template = tmp_path / ".env.example"
    template.write_text("PASSWORD=prepared-project-secret\n", encoding="utf-8")
    (tmp_path / "compose.yml").write_text(
        "services:\n  api:\n    image: example\n    env_file: .env\n", encoding="utf-8"
    )
    plan = {"commands": [
        {"cwd": ".", "argv": ["cp", ".env.example", ".env"]},
        {"cwd": ".", "argv": ["docker", "compose", "--env-file", ".env", "watch"]},
    ]}
    # Both pre-discovery and source-backed inspection precede project setup.
    known_secret_redactor(tmp_path)
    known_secret_redactor(tmp_path, plan)
    assert not (tmp_path / ".env").exists()
    (tmp_path / ".env").write_bytes(template.read_bytes())
    assert known_secret_redactor(tmp_path, plan).redact("prepared-project-secret") == "[REDACTED]"


@pytest.mark.parametrize("native", [False, True])
def test_literal_command_overrides_are_masked_in_both_workflow_shapes(tmp_path, native):
    command = {"cwd": ".", "argv": ["docker", "compose", "run", "-e", "TOKEN=command-secret", "api"]}
    workflow = {"commands": [command]} if native else {"setup": [command], "website": None, "api": None}
    redactor = known_secret_redactor(tmp_path, workflow)
    assert "command-secret" not in str(redactor.redact_json(workflow))
    assert redactor.redact("command-secret") == "[REDACTED]"


def test_known_secret_collection_does_not_read_symlinks_or_outside_checkout(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    outside = tmp_path / "outside.env"
    outside.write_text("SECRET=outside-value\n", encoding="utf-8")
    (checkout / ".env").symlink_to(outside)
    with pytest.raises(ValueError, match="symlinks"):
        known_secret_redactor(checkout)
    (checkout / ".env").unlink()
    (checkout / "compose.yml").write_text(
        "services:\n  app:\n    env_file: ../outside.env\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="escapes"):
        known_secret_redactor(checkout)


def test_known_secret_collection_fails_closed_on_oversized_configuration(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text("SECRET=" + "x" * 262145, encoding="utf-8")
    with pytest.raises(ValueError, match="limit"):
        known_secret_redactor(tmp_path)

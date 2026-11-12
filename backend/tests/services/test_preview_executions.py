import importlib.util
import threading
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, event, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    DevelopmentChat,
    DevelopmentMessage,
    PreviewExecution,
    PreviewExecutionEvent,
    User,
)
from app.services.preview_executions import (
    PreviewEventInput,
    append_events,
    get_active_execution,
    get_execution_for_chat,
    get_or_create_active_execution,
    list_executions,
    read_events,
    set_terminal_status,
    set_workflow_snapshot,
)
from app.services.preview_redaction import SecretRedactor


@pytest.fixture
def preview_engine(tmp_path: Path) -> Generator[Engine]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'preview.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def chat_id(preview_engine: Engine) -> uuid.UUID:
    with Session(preview_engine) as session, session.begin():
        owner = User(email="preview-owner@example.test", hashed_password="unused")
        session.add(owner)
        session.flush()
        chat = DevelopmentChat(owner_id=owner.id, title="Preview")
        session.add(chat)
        session.flush()
        return chat.id


def _create(engine: Engine, chat_id: uuid.UUID) -> uuid.UUID:
    with Session(engine) as session, session.begin():
        execution, created = get_or_create_active_execution(session, chat_id)
        assert created
        return execution.id


def test_get_or_create_has_stable_identity_and_no_assistant_message(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    with Session(preview_engine) as session, session.begin():
        first, created = get_or_create_active_execution(
            session, chat_id, {"argv": ["compose", "watch"]}
        )
        assert created
        execution_id, timestamp = first.id, first.created_at
        assert first.last_sequence == 1
    with Session(preview_engine) as session, session.begin():
        again, created = get_or_create_active_execution(
            session, chat_id, {"ignored": True}
        )
        assert not created
        assert again.id == execution_id
        assert again.created_at.replace(tzinfo=None) == timestamp.replace(tzinfo=None)
        assert again.workflow_snapshot == {"argv": ["compose", "watch"]}
        assert not session.exec(select(DevelopmentMessage)).all()
        assert read_events(session, execution_id)[0].payload == {
            "status": "starting",
            "ready": False,
        }


def test_helpers_never_commit_callers_transaction(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    with Session(preview_engine) as session:
        get_or_create_active_execution(session, chat_id)
        session.rollback()
    with Session(preview_engine) as session:
        assert get_active_execution(session, chat_id) is None
        assert not session.exec(select(PreviewExecutionEvent)).all()


def test_concurrent_launches_share_one_execution_after_transaction_lock(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    barrier = threading.Barrier(2)
    results: list[tuple[uuid.UUID, bool]] = []
    errors: list[Exception] = []

    def launch() -> None:
        try:
            with Session(preview_engine) as session, session.begin():
                barrier.wait(timeout=5)
                execution, created = get_or_create_active_execution(session, chat_id)
                results.append((execution.id, created))
        except Exception as error:
            errors.append(error)

    workers = [threading.Thread(target=launch) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=15)
    assert all(not worker.is_alive() for worker in workers)
    assert errors == []
    assert len({execution_id for execution_id, _ in results}) == 1
    assert sorted(created for _, created in results) == [False, True]


def test_partial_unique_index_blocks_bypassed_concurrent_creators(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    barrier = threading.Barrier(2)
    results: list[str] = []

    def insert() -> None:
        try:
            with Session(preview_engine) as session, session.begin():
                barrier.wait(timeout=5)
                session.add(PreviewExecution(chat_id=chat_id))
                session.flush()
            results.append("created")
        except IntegrityError:
            results.append("conflict")

    workers = [threading.Thread(target=insert) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=15)
    assert all(not worker.is_alive() for worker in workers)
    assert sorted(results) == ["conflict", "created"]
    index = next(index for index in PreviewExecution.__table__.indexes if index.unique)
    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "UNIQUE INDEX" in ddl
    assert "WHERE status IN ('starting', 'running')" in ddl


def test_terminal_attempt_releases_active_slot_and_history_is_chat_scoped(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    first_id = _create(preview_engine, chat_id)
    with Session(preview_engine) as session, session.begin():
        set_terminal_status(
            session, first_id, "failed", reason="initialization exited 1"
        )
        next_execution, created = get_or_create_active_execution(session, chat_id)
        assert created
        assert next_execution.id != first_id
        history = list_executions(session, chat_id)
        assert [execution.id for execution in history] == [next_execution.id, first_id]
        older = list_executions(
            session, chat_id, before=(history[0].created_at, history[0].id)
        )
        assert [execution.id for execution in older] == [first_id]
        assert get_execution_for_chat(session, uuid.uuid4(), first_id) is None
        assert list_executions(session, uuid.uuid4()) == []


def test_cursors_deduplicate_and_replay_stays_ordered(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    execution_id = _create(preview_engine, chat_id)
    incoming = [
        PreviewEventInput(1, "command_start", {"argv": ["compose", "watch"]}),
        PreviewEventInput(2, "stdout", {"text": "building"}),
        PreviewEventInput(3, "stderr", {"text": "warning"}),
    ]
    with Session(preview_engine) as session, session.begin():
        persisted = append_events(session, execution_id, incoming)
        assert [event.sequence for event in persisted] == [2, 3, 4]
        ids = [event.id for event in persisted]
    with Session(preview_engine) as session, session.begin():
        assert append_events(session, execution_id, incoming) == []
        replayed = read_events(session, execution_id, after_sequence=1)
        assert [event.id for event in replayed] == ids
        assert [
            event.kind for event in read_events(session, execution_id, after_sequence=2)
        ] == ["stdout", "stderr"]
        execution = session.get(PreviewExecution, execution_id)
        assert execution is not None
        assert execution.controller_cursor == 3
        assert execution.last_sequence == 4


@pytest.mark.parametrize("duplicate", ["sequence", "controller_cursor"])
def test_event_database_uniqueness(
    preview_engine: Engine, chat_id: uuid.UUID, duplicate: str
) -> None:
    execution_id = _create(preview_engine, chat_id)
    with Session(preview_engine) as session, session.begin():
        append_events(
            session, execution_id, [PreviewEventInput(1, "stdout", {"text": "hello"})]
        )
    with (
        pytest.raises(IntegrityError),
        Session(preview_engine) as session,
        session.begin(),
    ):
        session.add(
            PreviewExecutionEvent(
                execution_id=execution_id,
                sequence=2 if duplicate == "sequence" else 99,
                controller_cursor=1 if duplicate == "controller_cursor" else 99,
                kind="stdout",
            )
        )
        session.flush()


def test_unmarked_controller_gap_rolls_back_but_explicit_gap_is_replayable(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    execution_id = _create(preview_engine, chat_id)
    with (
        pytest.raises(ValueError, match="unmarked gap"),
        Session(preview_engine) as session,
        session.begin(),
    ):
        append_events(
            session, execution_id, [PreviewEventInput(2, "stdout", {"text": "lost"})]
        )
    with Session(preview_engine) as session, session.begin():
        result = append_events(
            session,
            execution_id,
            [
                PreviewEventInput(1, "gap", {"through_cursor": 8}),
                PreviewEventInput(9, "stdout", {"text": "tail"}),
            ],
        )
        assert [event.kind for event in result] == ["gap", "stdout"]
        assert (
            append_events(
                session,
                execution_id,
                [PreviewEventInput(5, "stdout", {"text": "retry"})],
            )
            == []
        )
        execution = session.get(PreviewExecution, execution_id)
        assert execution is not None and execution.controller_cursor == 9


def test_retention_preserves_commands_exit_terminal_and_explicit_truncation(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    execution_id = _create(preview_engine, chat_id)
    with Session(preview_engine) as session, session.begin():
        append_events(
            session,
            execution_id,
            [
                PreviewEventInput(
                    1,
                    "command_start",
                    {"argv": ["compose", "run"], "cwd": "app", "source": "README:8"},
                ),
                PreviewEventInput(2, "stdout", {"text": "a" * 9}),
                PreviewEventInput(3, "stderr", {"text": "b" * 9}),
                PreviewEventInput(4, "command_exit", {"exit_code": 1}),
                PreviewEventInput(
                    5, "status", {"status": "failed", "reason": "setup failed"}
                ),
            ],
            retention_bytes=10,
        )
        execution = session.get(PreviewExecution, execution_id)
        assert execution is not None
        assert execution.retained_output_bytes == 9
        assert execution.truncated_bytes == 9
        assert execution.status == "failed"
        assert execution.finished_at is not None
        events = read_events(session, execution_id)
        assert [event.kind for event in events] == [
            "status",
            "command_start",
            "stderr",
            "command_exit",
            "status",
            "truncated",
        ]
        assert events[-1].payload["total_dropped_bytes"] == 9
        assert events[-2].payload["status"] == "failed"
        assert events[-3].payload["exit_code"] == 1
        # Evicted controller cursor 2 cannot recreate lost rows on a retry.
        assert (
            append_events(
                session,
                execution_id,
                [PreviewEventInput(2, "stdout", {"text": "replayed"})],
                retention_bytes=10,
            )
            == []
        )


def test_oversized_unicode_output_and_zero_retention_are_explicit(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    execution_id = _create(preview_engine, chat_id)
    with Session(preview_engine) as session, session.begin():
        events = append_events(
            session,
            execution_id,
            [PreviewEventInput(1, "stdout", {"text": "秘密秘密"})],
            retention_bytes=4,
        )
        assert events[0].payload["text"] == "密"
        assert events[1].payload["total_dropped_bytes"] == 9
        events = append_events(
            session,
            execution_id,
            [PreviewEventInput(2, "stderr", {"text": "sensitive already redacted"})],
            retention_bytes=0,
        )
        execution = session.get(PreviewExecution, execution_id)
        assert execution is not None and execution.retained_output_bytes == 0
        assert events[-1].kind == "truncated"
        all_events = read_events(session, execution_id)
        assert sum(event.kind == "truncated" for event in all_events) == 1
        assert all(not event.payload.get("text") for event in all_events)


def test_empty_output_event_count_is_bounded(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    execution_id = _create(preview_engine, chat_id)
    with Session(preview_engine) as session, session.begin():
        append_events(
            session,
            execution_id,
            [PreviewEventInput(i, "stdout", {"text": ""}) for i in range(1, 21)],
            output_event_limit=3,
        )
        events = read_events(session, execution_id)
        assert sum(event.kind == "stdout" for event in events) == 3
        assert events[-1].kind == "truncated"
        assert events[-1].payload["dropped_events"] == 17


def test_readiness_does_not_finish_watch_and_terminal_first_outcome_wins(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    execution_id = _create(preview_engine, chat_id)
    with Session(preview_engine) as session, session.begin():
        append_events(
            session,
            execution_id,
            [PreviewEventInput(1, "status", {"status": "running", "ready": True})],
        )
        execution = session.get(PreviewExecution, execution_id)
        assert execution is not None and execution.ready
        assert execution.status == "running" and execution.finished_at is None
        assert get_active_execution(session, chat_id).id == execution_id
        set_terminal_status(
            session, execution_id, "interrupted", reason="sandbox missing"
        )
        sequence = execution.last_sequence
        finished_at = execution.finished_at
        set_terminal_status(session, execution_id, "stopped")
        assert execution.last_sequence == sequence
        assert execution.finished_at is not None and finished_at is not None
        assert execution.finished_at.replace(tzinfo=None) == finished_at.replace(
            tzinfo=None
        )
        assert execution.status == "interrupted" and not execution.ready
        assert get_active_execution(session, chat_id) is None
    with (
        pytest.raises(ValueError, match="terminal"),
        Session(preview_engine) as session,
        session.begin(),
    ):
        append_events(
            session,
            execution_id,
            [PreviewEventInput(2, "status", {"status": "running"})],
        )


def test_model_rejects_ready_starting_and_unknown_status(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    for values in ({"ready": True}, {"status": "bogus"}):
        with (
            pytest.raises(IntegrityError),
            Session(preview_engine) as session,
            session.begin(),
        ):
            session.add(PreviewExecution(chat_id=chat_id, **values))
            session.flush()


def test_metadata_and_diagnostics_are_redacted_before_persistence(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    redactor = SecretRedactor(["known-secret"])
    with Session(preview_engine) as session, session.begin():
        execution, _ = get_or_create_active_execution(
            session, chat_id, {"source": "README known-secret"}, redactor=redactor
        )
        set_workflow_snapshot(
            session,
            execution.id,
            {"argv": ["--password=known-secret"]},
            redactor=redactor,
        )
        append_events(
            session,
            execution.id,
            [
                PreviewEventInput(
                    1,
                    "command_start",
                    {
                        "argv": ["known-secret"],
                        "source": "known-secret",
                        "cwd": "known-secret",
                    },
                )
            ],
            redactor=redactor,
        )
        set_terminal_status(
            session,
            execution.id,
            "failed",
            reason="error known-secret",
            redactor=redactor,
        )
        assert "known-secret" not in str(execution.workflow_snapshot)
        assert "known-secret" not in str(
            [event.payload for event in read_events(session, execution.id)]
        )


def test_chat_deletion_cascades_through_execution_and_events(
    preview_engine: Engine, chat_id: uuid.UUID
) -> None:
    _create(preview_engine, chat_id)
    with preview_engine.begin() as connection:
        # Raw SQL proves the FK, not just ORM cascade configuration, enforces it.
        connection.execute(
            text("DELETE FROM developmentchat WHERE id = :id"), {"id": chat_id.hex}
        )
    with Session(preview_engine) as session:
        assert not session.exec(select(PreviewExecution)).all()
        assert not session.exec(select(PreviewExecutionEvent)).all()


def test_additive_migration_matches_models_and_downgrades_without_chat_loss(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    base_tables = [
        table
        for name, table in SQLModel.metadata.tables.items()
        if not name.startswith("previewexecution")
    ]
    SQLModel.metadata.create_all(engine, tables=base_tables)
    migration_path = (
        Path(__file__).parents[2]
        / "app/alembic/versions/b7a46d91e250_add_preview_executions.py"
    )
    spec = importlib.util.spec_from_file_location("preview_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        schema = inspect(connection)
        for model in (PreviewExecution, PreviewExecutionEvent):
            actual = {
                column["name"] for column in schema.get_columns(model.__tablename__)
            }
            assert actual == set(model.__table__.columns.keys())
        indexes = schema.get_indexes("previewexecution")
        assert any(
            index["name"] == "uq_previewexecution_active_chat" and index["unique"]
            for index in indexes
        )
        assert (
            schema.get_foreign_keys("previewexecution")[0]["options"]["ondelete"]
            == "CASCADE"
        )
        with Operations.context(context):
            migration.downgrade()
        assert "developmentchat" in inspect(connection).get_table_names()
        assert "previewexecution" not in inspect(connection).get_table_names()
    engine.dispose()

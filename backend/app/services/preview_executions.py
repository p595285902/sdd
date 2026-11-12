"""Transactional preview persistence, independent of messages and Agent Turns.

All mutators FLUSH ONLY. The caller owns commit/rollback and must commit before
provisioning a runtime or acknowledging/streaming returned events. Mutators lock
the owning DevelopmentChat row for the duration of that transaction; the partial
unique index is a second, database-level single-active guard. SQLite uses a
no-op chat UPDATE because SELECT FOR UPDATE is not supported there.

These are internal persistence helpers, not an authorization boundary: routes
must first authorize the existing DevelopmentChat owner. Never log inputs here.
Output must already pass through the runtime's chunk-spanning SecretRedactor;
passing a redactor also masks standalone workflow/source/argv metadata defensively.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlmodel import Session, col, select

from app.models import (
    DevelopmentChat,
    PreviewExecution,
    PreviewExecutionEvent,
    PreviewExecutionStatus,
    get_datetime_utc,
)
from app.services.preview_redaction import SecretRedactor

ACTIVE_STATUSES = (PreviewExecutionStatus.starting, PreviewExecutionStatus.running)
TERMINAL_STATUSES = (
    PreviewExecutionStatus.failed,
    PreviewExecutionStatus.stopped,
    PreviewExecutionStatus.interrupted,
)
DEFAULT_OUTPUT_RETENTION_BYTES = 256 * 1024
DEFAULT_OUTPUT_EVENT_LIMIT = 1024
MAX_BATCH_EVENTS = 100
MAX_METADATA_BYTES = 64 * 1024
MAX_OUTPUT_CHUNK_BYTES = 64 * 1024
EVENT_KINDS = frozenset(
    {"command_start", "stdout", "stderr", "command_exit", "status", "gap"}
)


@dataclass(frozen=True)
class PreviewEventInput:
    cursor: int
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


def _safe_json(
    value: dict[str, Any], redactor: SecretRedactor | None
) -> dict[str, Any]:
    # Copy to avoid retaining mutable caller dictionaries containing raw values.
    value = (redactor or SecretRedactor()).redact_json(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        result = json.loads(encoded)
    except TypeError, ValueError:
        raise ValueError("Preview metadata must be JSON serializable") from None
    if not isinstance(result, dict):
        raise ValueError("Preview metadata must be an object")
    return result


def _metadata_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _lock_chat(session: Session, chat_id: uuid.UUID) -> DevelopmentChat:
    if session.get_bind().dialect.name == "sqlite":
        session.execute(
            update(DevelopmentChat)
            .where(col(DevelopmentChat.id) == chat_id)
            .values(id=chat_id)
            .execution_options(synchronize_session=False)
        )
    chat = session.exec(
        select(DevelopmentChat)
        .where(DevelopmentChat.id == chat_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if chat is None:
        raise LookupError("Development Chat not found")
    return chat


def _lock_execution(session: Session, execution_id: uuid.UUID) -> PreviewExecution:
    chat_id = session.exec(
        select(PreviewExecution.chat_id).where(PreviewExecution.id == execution_id)
    ).first()
    if chat_id is None:
        raise LookupError("Preview execution not found")
    _lock_chat(session, chat_id)
    execution = session.exec(
        select(PreviewExecution)
        .where(PreviewExecution.id == execution_id)
        .execution_options(populate_existing=True)
    ).first()
    if execution is None:
        raise LookupError("Preview execution not found")
    return execution


def _add_event(
    session: Session,
    execution: PreviewExecution,
    *,
    kind: str,
    payload: dict[str, Any],
    controller_cursor: int | None = None,
    output_bytes: int = 0,
) -> PreviewExecutionEvent:
    execution.last_sequence += 1
    execution.updated_at = get_datetime_utc()
    event = PreviewExecutionEvent(
        execution_id=execution.id,
        sequence=execution.last_sequence,
        controller_cursor=controller_cursor,
        kind=kind,
        payload=payload,
        output_bytes=output_bytes,
    )
    session.add(event)
    session.add(execution)
    return event


def get_active_execution(
    session: Session, chat_id: uuid.UUID
) -> PreviewExecution | None:
    """Read only; does not launch, lock or provision anything."""
    return session.exec(
        select(PreviewExecution).where(
            PreviewExecution.chat_id == chat_id,
            col(PreviewExecution.status).in_(ACTIVE_STATUSES),
        )
    ).first()


def get_execution_for_chat(
    session: Session, chat_id: uuid.UUID, execution_id: uuid.UUID
) -> PreviewExecution | None:
    return session.exec(
        select(PreviewExecution).where(
            PreviewExecution.chat_id == chat_id, PreviewExecution.id == execution_id
        )
    ).first()


def get_or_create_active_execution(
    session: Session,
    chat_id: uuid.UUID,
    workflow_snapshot: dict[str, Any] | None = None,
    *,
    redactor: SecretRedactor | None = None,
) -> tuple[PreviewExecution, bool]:
    """Return (execution, created); only the committed creator may initialize.

    Locks last until caller commit/rollback, including when reattaching. Do not
    catch a database exception and continue using an un-rolled-back transaction.
    An explicit restart must stop the old runtime and terminalize its execution
    before creating a replacement; this helper never stops or restarts anything.
    """
    _lock_chat(session, chat_id)
    execution = get_active_execution(session, chat_id)
    if execution is not None:
        return execution, False
    snapshot = _safe_json(workflow_snapshot or {}, redactor)
    if _metadata_size(snapshot) > MAX_METADATA_BYTES:
        raise ValueError("Preview workflow exceeds metadata limit")
    execution = PreviewExecution(chat_id=chat_id, workflow_snapshot=snapshot)
    session.add(execution)
    session.flush()
    _add_event(
        session,
        execution,
        kind="status",
        payload={"status": PreviewExecutionStatus.starting.value, "ready": False},
    )
    session.flush()
    return execution, True


def set_workflow_snapshot(
    session: Session,
    execution_id: uuid.UUID,
    workflow_snapshot: dict[str, Any],
    *,
    redactor: SecretRedactor | None = None,
) -> PreviewExecution:
    """Attach the resolved source-backed plan to a just-starting operation."""
    execution = _lock_execution(session, execution_id)
    if execution.status != PreviewExecutionStatus.starting:
        raise ValueError("Only a starting execution may receive its workflow")
    snapshot = _safe_json(workflow_snapshot, redactor)
    if _metadata_size(snapshot) > MAX_METADATA_BYTES:
        raise ValueError("Preview workflow exceeds metadata limit")
    execution.workflow_snapshot = snapshot
    execution.updated_at = get_datetime_utc()
    session.add(execution)
    session.flush()
    return execution


def _apply_status(execution: PreviewExecution, payload: dict[str, Any]) -> None:
    try:
        status = PreviewExecutionStatus(payload.get("status", execution.status))
    except ValueError:
        raise ValueError("Invalid preview execution status") from None
    if execution.status in TERMINAL_STATUSES and status != execution.status:
        raise ValueError("A terminal preview execution cannot change status")
    if (
        execution.status == PreviewExecutionStatus.running
        and status == PreviewExecutionStatus.starting
    ):
        raise ValueError("A running preview execution cannot return to starting")
    ready = payload.get("ready", execution.ready)
    if not isinstance(ready, bool):
        raise ValueError("Preview readiness must be boolean")
    if status in TERMINAL_STATUSES:
        ready = False
        execution.finished_at = execution.finished_at or get_datetime_utc()
    if ready and status != PreviewExecutionStatus.running:
        raise ValueError("Only a running preview execution may be ready")
    execution.status = status
    execution.ready = ready
    payload["status"] = status.value
    payload["ready"] = ready


def _retain_output(
    session: Session,
    execution: PreviewExecution,
    *,
    retention_bytes: int,
    output_event_limit: int,
    dropped_bytes: int,
) -> None:
    # Only output is evicted. Command starts/exits and status/diagnostic events
    # are retained, even if a single output chunk exceeds the entire allowance.
    session.flush()
    output = list(
        session.exec(
            select(PreviewExecutionEvent)
            .where(
                PreviewExecutionEvent.execution_id == execution.id,
                col(PreviewExecutionEvent.kind).in_(("stdout", "stderr")),
            )
            .order_by(col(PreviewExecutionEvent.sequence))
        ).all()
    )
    total = sum(event.output_bytes for event in output)
    remaining_count = len(output)
    dropped_events = 0
    for event in output:
        if total <= retention_bytes and remaining_count <= output_event_limit:
            break
        total -= event.output_bytes
        remaining_count -= 1
        dropped_bytes += event.output_bytes
        dropped_events += 1
        session.delete(event)
    execution.retained_output_bytes = total
    if not dropped_bytes and not dropped_events:
        return
    execution.truncated_bytes += dropped_bytes
    # One cumulative durable marker bounds marker growth too. Its new sequence
    # makes subsequent omissions visible even to an already-connected browser.
    for previous in session.exec(
        select(PreviewExecutionEvent).where(
            PreviewExecutionEvent.execution_id == execution.id,
            PreviewExecutionEvent.kind == "truncated",
        )
    ).all():
        session.delete(previous)
    _add_event(
        session,
        execution,
        kind="truncated",
        payload={
            "dropped_bytes": dropped_bytes,
            "total_dropped_bytes": execution.truncated_bytes,
            "dropped_events": dropped_events,
            "reason": "Stored stdout/stderr retention limit",
        },
    )


def append_events(
    session: Session,
    execution_id: uuid.UUID,
    events: Sequence[PreviewEventInput],
    *,
    redactor: SecretRedactor | None = None,
    retention_bytes: int = DEFAULT_OUTPUT_RETENTION_BYTES,
    output_event_limit: int = DEFAULT_OUTPUT_EVENT_LIMIT,
) -> list[PreviewExecutionEvent]:
    """Persist a bounded batch of already chunk-redacted controller events.

    Cursors start at 1. Retries at/below the committed controller high-water mark
    are ignored, including evicted events. New cursors must be contiguous. A
    controller journal gap is explicit: an event at the next expected cursor,
    kind='gap', payload={'through_cursor': N} consumes the omitted range through
    N. Browser sequence is independent and includes backend-generated markers.
    Return only newly retained events, ordered by sequence; commit before emit.
    Any exception requires the caller to roll back the transaction.
    """
    if retention_bytes < 0 or output_event_limit < 1:
        raise ValueError("Invalid preview output retention bounds")
    if len(events) > MAX_BATCH_EVENTS:
        raise ValueError("Preview event batch exceeds limit")
    execution = _lock_execution(session, execution_id)
    before_sequence = execution.last_sequence
    dropped_bytes = 0
    for incoming in events:
        if (
            not isinstance(incoming.cursor, int)
            or isinstance(incoming.cursor, bool)
            or incoming.cursor < 1
        ):
            raise ValueError("Controller event cursor must be positive")
        if incoming.cursor <= execution.controller_cursor:
            continue
        if incoming.cursor != execution.controller_cursor + 1:
            raise ValueError("Controller event cursor has an unmarked gap")
        if incoming.kind not in EVENT_KINDS:
            raise ValueError("Invalid preview event kind")
        payload = _safe_json(incoming.payload, redactor)
        cursor = incoming.cursor
        if incoming.kind == "gap":
            through = payload.get("through_cursor")
            if (
                not isinstance(through, int)
                or isinstance(through, bool)
                or through < cursor
            ):
                raise ValueError("Invalid controller gap cursor")
            cursor = through
        output_bytes = 0
        if incoming.kind in ("stdout", "stderr"):
            text = payload.get("text", "")
            if not isinstance(text, str):
                raise ValueError("Preview output text must be a string")
            metadata = {key: value for key, value in payload.items() if key != "text"}
            if _metadata_size(metadata) > MAX_METADATA_BYTES:
                raise ValueError("Preview output metadata exceeds limit")
            encoded = text.encode("utf-8")
            allowance = min(retention_bytes, MAX_OUTPUT_CHUNK_BYTES)
            retained = (
                encoded[-allowance:].decode("utf-8", errors="ignore")
                if allowance
                else ""
            )
            output_bytes = len(retained.encode("utf-8"))
            dropped_bytes += len(encoded) - output_bytes
            payload["text"] = retained
        elif _metadata_size(payload) > MAX_METADATA_BYTES:
            raise ValueError("Preview event metadata exceeds limit")
        if incoming.kind == "status":
            _apply_status(execution, payload)
        _add_event(
            session,
            execution,
            kind=incoming.kind,
            payload=payload,
            controller_cursor=incoming.cursor,
            output_bytes=output_bytes,
        )
        execution.controller_cursor = cursor
    _retain_output(
        session,
        execution,
        retention_bytes=retention_bytes,
        output_event_limit=output_event_limit,
        dropped_bytes=dropped_bytes,
    )
    session.add(execution)
    session.flush()
    return read_events(
        session,
        execution_id,
        after_sequence=before_sequence,
        limit=MAX_BATCH_EVENTS + 1,
    )


def set_terminal_status(
    session: Session,
    execution_id: uuid.UUID,
    status: PreviewExecutionStatus | str,
    *,
    reason: str | None = None,
    redactor: SecretRedactor | None = None,
) -> PreviewExecution:
    """Record terminal status atomically; the first terminal outcome wins."""
    status = PreviewExecutionStatus(status)
    if status not in TERMINAL_STATUSES:
        raise ValueError("Expected a terminal preview execution status")
    execution = _lock_execution(session, execution_id)
    if execution.status in TERMINAL_STATUSES:
        return execution
    payload: dict[str, Any] = {"status": status.value, "ready": False}
    if reason is not None:
        payload["reason"] = reason
    payload = _safe_json(payload, redactor)
    if _metadata_size(payload) > MAX_METADATA_BYTES:
        raise ValueError("Preview terminal diagnostic exceeds metadata limit")
    _apply_status(execution, payload)
    _add_event(session, execution, kind="status", payload=payload)
    session.flush()
    return execution


def read_events(
    session: Session,
    execution_id: uuid.UUID,
    *,
    after_sequence: int = 0,
    limit: int = 100,
) -> list[PreviewExecutionEvent]:
    """Read-only stable ascending replay. The next cursor is the final sequence."""
    if after_sequence < 0 or not 1 <= limit <= 1000:
        raise ValueError("Invalid preview event page")
    return list(
        session.exec(
            select(PreviewExecutionEvent)
            .where(
                PreviewExecutionEvent.execution_id == execution_id,
                PreviewExecutionEvent.sequence > after_sequence,
            )
            .order_by(col(PreviewExecutionEvent.sequence))
            .limit(limit)
        ).all()
    )


def list_executions(
    session: Session,
    chat_id: uuid.UUID,
    *,
    limit: int = 50,
    before: tuple[datetime, uuid.UUID] | None = None,
) -> list[PreviewExecution]:
    """Read-only newest-first history; page using the last (created_at, id)."""
    if not 1 <= limit <= 200:
        raise ValueError("Invalid preview history page")
    statement = select(PreviewExecution).where(PreviewExecution.chat_id == chat_id)
    if before is not None:
        created_at, execution_id = before
        statement = statement.where(
            (PreviewExecution.created_at < created_at)
            | (
                (PreviewExecution.created_at == created_at)
                & (PreviewExecution.id < execution_id)
            )
        )
    return list(
        session.exec(
            statement.order_by(
                col(PreviewExecution.created_at).desc(), col(PreviewExecution.id).desc()
            ).limit(limit)
        ).all()
    )

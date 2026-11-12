"""Bounded polling/reconciliation for durable preview operations.

The scanner has no runtime-provisioning path. It discovers persisted active rows
on every scan, including after process restart. Acceptance work is admitted per
scan, so reset cancels/drains in-flight I/O without an immortal registered worker.
No controller exception/output is logged or exposed verbatim.
"""

import json
import logging
import os
import re
import stat
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values
from sqlalchemy import Engine
from sqlmodel import Session, col, select

from app.models import DevelopmentChat, PreviewExecution, PreviewExecutionEvent
from app.services.acceptance_work import AdmissionClosed, WorkBarrier, current_work
from app.services.preview_executions import (
    ACTIVE_STATUSES,
    MAX_BATCH_EVENTS,
    PreviewEventInput,
    _lock_execution,
    append_events,
    read_events,
    set_terminal_status,
)
from app.services.preview_redaction import SecretRedactor, command_secrets

logger = logging.getLogger(__name__)
SECRET_KEY = re.compile(
    r"password|passwd|secret|token|api[_-]?key|private[_-]?key|credential", re.I
)


def known_secret_redactor(
    checkout: Path, payload: dict[str, Any] | None = None
) -> SecretRedactor:
    """Mask only bounded literal project configuration, never platform env.

    This is not Compose resolution/preflight: literal environment/env_file
    fields are inspected only to discover values to mask, not to choose services,
    interpolate deployment settings or decide whether a project may execute.
    Missing environment files may be created by documented setup; native Compose
    validates their presence and masks resolved values before its first command.
    """
    import yaml  # type: ignore[import-untyped]

    root = checkout.resolve(strict=True)
    secrets: list[str] = []
    seen: set[Path] = set()
    total = 0

    def read_local(path: Path, *, required: bool = False) -> str | None:
        nonlocal total
        if path in seen:
            return None
        if len(seen) >= 64:
            raise ValueError("Project secret discovery file limit exceeded")
        if not path.is_absolute():
            path = root / path
        lexical = Path(os.path.abspath(path))
        if not lexical.is_relative_to(root):
            raise ValueError("Project secret configuration escapes checkout")
        for component in (lexical, *lexical.parents):
            if component == root:
                break
            if component.is_symlink():
                raise ValueError("Project secret configuration must not use symlinks")
        try:
            descriptor = os.open(lexical, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            if required:
                raise ValueError(
                    "Referenced project configuration is missing"
                ) from None
            return None
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError("Project configuration must be a regular file")
            data = handle.read(262145)
        total += len(data)
        if len(data) > 262144 or total > 1048576:
            raise ValueError("Project secret discovery text limit exceeded")
        seen.add(lexical)
        return data.decode("utf-8")

    def environment(path: Path) -> None:
        text = read_local(path)
        if text is not None:
            # interpolate=False never consults os.environ/platform credentials.
            secrets.extend(
                value
                for key, value in dotenv_values(
                    stream=StringIO(text), interpolate=False
                ).items()
                if value and SECRET_KEY.search(key)
            )

    workflow = payload or {}
    commands = workflow.get("commands", []) or [
        *workflow.get("setup", []),
        *(workflow[key] for key in ("website", "api") if workflow.get(key)),
    ]
    bases = {root}
    manifests: set[Path] = set()
    for command in commands:
        base = root / command.get("cwd", ".")
        bases.add(base)
        secrets.extend(command_secrets(command))
        argv = command.get("argv", [])
        for index, argument in enumerate(argv):
            if argument in ("--env-file", "-f", "--file") and index + 1 < len(argv):
                target = base / argv[index + 1]
                if argument == "--env-file":
                    environment(target)
                else:
                    manifests.add(target)
            elif argument.startswith("--env-file="):
                environment(base / argument.split("=", 1)[1])
            elif argument.startswith("--file="):
                manifests.add(base / argument.split("=", 1)[1])
    for base in bases:
        for filename in (".env", ".env.local"):
            environment(base / filename)
        for filename in (
            "compose.yml",
            "compose.yaml",
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.override.yml",
            "compose.override.yaml",
            "docker-compose.override.yml",
            "docker-compose.override.yaml",
        ):
            path = base / filename
            if path.exists() or path.is_symlink():
                manifests.add(path)
    for path in sorted(manifests):
        content = read_local(path, required=True)
        if content is None:
            continue
        try:
            model = yaml.safe_load(content)
        except yaml.YAMLError:
            raise ValueError(
                "Project secret configuration could not be inspected safely"
            ) from None
        services = model.get("services", {}) if isinstance(model, dict) else {}
        if not isinstance(services, dict):
            continue
        for service in services.values():
            if not isinstance(service, dict):
                continue
            configured = service.get("environment", {})
            if isinstance(configured, dict):
                secrets.extend(
                    str(value)
                    for key, value in configured.items()
                    if isinstance(key, str)
                    and SECRET_KEY.search(key)
                    and value is not None
                    and not isinstance(value, (dict, list))
                )
            elif isinstance(configured, list):
                secrets.extend(
                    value.partition("=")[2]
                    for value in configured
                    if isinstance(value, str)
                    and "=" in value
                    and SECRET_KEY.search(value.partition("=")[0])
                )
            files = service.get("env_file", [])
            if isinstance(files, (str, dict)):
                files = [files]
            if isinstance(files, list):
                for configured_file in files:
                    value = (
                        configured_file.get("path")
                        if isinstance(configured_file, dict)
                        else configured_file
                    )
                    if isinstance(value, str) and "${" not in value:
                        environment(path.parent / value)
    return SecretRedactor(secrets)


def _timestamp(value: datetime) -> str:
    return (
        value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    ).isoformat()


def execution_public(execution: PreviewExecution) -> dict[str, Any]:
    return {
        "id": str(execution.id),
        "chat_id": str(execution.chat_id),
        "created_at": _timestamp(execution.created_at),
        "updated_at": _timestamp(execution.updated_at),
        "status": str(execution.status),
        "ready": execution.ready,
        "workflow": execution.workflow_snapshot,
        "last_sequence": execution.last_sequence,
        "truncated_bytes": execution.truncated_bytes,
    }


def event_public(event: PreviewExecutionEvent) -> dict[str, Any]:
    return {
        "execution_id": str(event.execution_id),
        "sequence": event.sequence,
        "kind": event.kind,
        "payload": event.payload,
        "created_at": _timestamp(event.created_at),
    }


def serialize_event(event: dict[str, Any]) -> str:
    return (
        f"id: {event['sequence']}\nevent: preview-event\n"
        f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
    )


class PreviewExecutionLifecycle:
    def __init__(
        self,
        database: Engine,
        controller: Any,
        *,
        barrier: WorkBarrier | None = None,
        poll_interval: float = 0.25,
        launch_grace_seconds: float = 60,
    ) -> None:
        self.database = database
        self.controller = controller
        self.barrier = barrier
        self.poll_interval = poll_interval
        self.launch_grace_seconds = launch_grace_seconds
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._scan_after: uuid.UUID | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=15)
            if thread.is_alive():
                raise RuntimeError("Preview reconciliation did not stop")

    def _run(self) -> None:
        while not self._stop.is_set():
            work = None
            token = None
            try:
                if self.barrier is not None:
                    work = self.barrier.admit("preview-reconciliation")
                    token = current_work.set(work)
                cancelled = work.cancelled if work else self._stop
                self.scan_once(cancelled=cancelled)
            except AdmissionClosed:
                pass
            except Exception:
                # Identifiers/project output/provider exception text are omitted.
                logger.warning("Preview reconciliation temporarily unavailable")
            finally:
                if token is not None:
                    current_work.reset(token)
                if work is not None and self.barrier is not None:
                    self.barrier.finish(work)
            self._stop.wait(self.poll_interval)

    def scan_once(self, *, cancelled: threading.Event | None = None) -> None:
        with Session(self.database) as session:
            statement = select(PreviewExecution.id).where(
                col(PreviewExecution.status).in_(ACTIVE_STATUSES)
            )
            if self._scan_after is not None:
                statement = statement.where(col(PreviewExecution.id) > self._scan_after)
            ids = session.exec(
                statement.order_by(col(PreviewExecution.id)).limit(64)
            ).all()
            self._scan_after = ids[-1] if len(ids) == 64 else None
        for execution_id in ids:
            if self._stop.is_set() or (cancelled is not None and cancelled.is_set()):
                return
            self.collect(execution_id, cancelled=cancelled)

    def collect(
        self, execution_id: uuid.UUID, *, cancelled: threading.Event | None = None
    ) -> None:
        with Session(self.database) as session:
            execution = session.get(PreviewExecution, execution_id)
            if execution is None or execution.status not in ACTIVE_STATUSES:
                return
            chat_id, after = execution.chat_id, execution.controller_cursor
            observed_updated_at = execution.updated_at
            created = execution.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            pending_launch = (
                execution.status == "starting"
                and after == 0
                and (datetime.now(UTC) - created).total_seconds()
                < self.launch_grace_seconds
            )
        missing = False
        try:
            result = self.controller.events(chat_id, after)
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                return
            missing = True
            result = {}
        except httpx.HTTPError, OSError, RuntimeError:
            return
        if self._stop.is_set() or (cancelled is not None and cancelled.is_set()):
            return
        reported_execution = result.get("execution_id")
        mismatch = reported_execution is not None and str(reported_execution) != str(
            execution_id
        )
        if (missing or mismatch) and pending_launch:
            return
        with Session(self.database) as session, session.begin():
            try:
                execution = _lock_execution(session, execution_id)
            except LookupError:
                return
            if execution.status not in ACTIVE_STATUSES:
                return
            if (missing or mismatch) and execution.updated_at != observed_updated_at:
                return  # A concurrent dispatch changed ownership after the HTTP read.
            if missing or mismatch:
                set_terminal_status(
                    session,
                    execution_id,
                    "interrupted",
                    reason="The owned preview sandbox is missing after reconciliation. Launch explicitly to start another attempt.",
                )
                return
            incoming = result.get("events", [])
            if not isinstance(incoming, list) or len(incoming) > 1000:
                raise ValueError("Invalid controller event batch")
            # Bound write batches even if a controller response contains a full
            # replay window. A transaction commits before any stream reads it.
            for offset in range(0, len(incoming), MAX_BATCH_EVENTS):
                batch = [
                    PreviewEventInput(
                        item["cursor"], item["kind"], item.get("payload", {})
                    )
                    for item in incoming[offset : offset + MAX_BATCH_EVENTS]
                ]
                append_events(session, execution_id, batch)
            state = result.get("state")
            if execution.status in ACTIVE_STATUSES and state in {
                "failed",
                "stopped",
                "interrupted",
            }:
                set_terminal_status(
                    session,
                    execution_id,
                    state,
                    reason="Preview runtime stopped."
                    if state == "stopped"
                    else "Preview runtime is no longer active.",
                )

    def stream(
        self,
        chat_id: uuid.UUID,
        execution_id: uuid.UUID,
        owner_id: uuid.UUID,
        *,
        after: int,
    ) -> Iterator[str]:
        """Independent safe-text SSE; all emitted rows were already committed."""
        cursor = after
        work = current_work.get()
        while not self._stop.is_set():
            if work is not None and work.cancelled.is_set():
                return
            with Session(self.database) as session:
                owner = session.exec(
                    select(DevelopmentChat.id).where(
                        DevelopmentChat.id == chat_id,
                        DevelopmentChat.owner_id == owner_id,
                    )
                ).first()
                execution = session.exec(
                    select(PreviewExecution).where(
                        PreviewExecution.id == execution_id,
                        PreviewExecution.chat_id == chat_id,
                    )
                ).first()
                if owner is None or execution is None:
                    return
                events = [
                    event_public(event)
                    for event in read_events(
                        session, execution_id, after_sequence=cursor, limit=256
                    )
                ]
                terminal = execution.status not in ACTIVE_STATUSES
            for event in events:
                cursor = event["sequence"]
                yield serialize_event(event)
            if terminal and len(events) < 256:
                return
            if events:
                continue
            yield ": heartbeat\n\n"
            if work is not None:
                work.cancelled.wait(self.poll_interval)
            else:
                self._stop.wait(self.poll_interval)

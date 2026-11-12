import asyncio
import base64
import hashlib
import json
import logging
import re
import threading
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from functools import partial
from http.cookies import CookieError, SimpleCookie
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlsplit

import httpx
import jwt
import websockets
from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, update
from sqlmodel import Session, col, func, select
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.db import engine
from app.core.security import ALGORITHM
from app.models import (
    DevelopmentChat,
    DevelopmentChatCreate,
    DevelopmentChatPublic,
    DevelopmentChatsPublic,
    DevelopmentChatUpdate,
    DevelopmentMessage,
    DevelopmentMessageCreate,
    DevelopmentMessageKind,
    DevelopmentMessagePublic,
    DevelopmentMessagesPublic,
    DevelopmentPresenceUpdate,
    DevelopmentProposalState,
    DevelopmentWorkspacePublic,
    Message,
    PreviewExecution,
    get_datetime_utc,
)
from app.services.acceptance_reset import (
    acceptance_reset,
    effective_repository,
    reset_enabled,
)
from app.services.acceptance_work import CompletionStreamingResponse, current_work
from app.services.develop_agent import (
    AgentCommandCancelled,
    AgentCommandError,
    AgentCommandTimeout,
    AgentEvent,
    AgentEventKind,
    execute_apply,
    execute_exploration,
    execute_proposal,
)
from app.services.develop_preview_classification import classify_workspace
from app.services.develop_preview_detection import (
    relevant_turn_change,
    snapshot_workspace,
)
from app.services.develop_preview_instructions import resolve_preview_plan
from app.services.develop_preview_runtime import PreviewController
from app.services.develop_turns import (
    ChatTurnActiveError,
    TurnEvent,
    TurnSession,
    TurnTerminalState,
    UserTurnLimitError,
    develop_turn_manager,
)
from app.services.develop_workspace import (
    FakeCommandRunner,
    SubprocessCommandRunner,
    WorkspacePathError,
    WorkspaceSetupError,
    cleanup_workspace,
    setup_workspace,
    workspace_path,
)
from app.services.preview_execution_lifecycle import (
    SECRET_KEY,
    PreviewExecutionLifecycle,
    event_public,
    execution_public,
    known_secret_redactor,
)
from app.services.preview_executions import (
    ACTIVE_STATUSES,
    MAX_BATCH_EVENTS,
    PreviewEventInput,
    _add_event,
    _lock_chat,
    append_events,
    get_active_execution,
    get_execution_for_chat,
    get_or_create_active_execution,
    list_executions,
    read_events,
    set_terminal_status,
    set_workflow_snapshot,
)
from app.services.preview_native_plan import (
    PreviewInstructionsError,
    resolve_native_plan,
)
from app.services.preview_redaction import SecretRedactor

logger = logging.getLogger(__name__)
preview_controller = PreviewController(
    root=settings.DEVELOP_WORKSPACE_ROOT, url="http://preview-controller:8090"
)
preview_lifecycle = PreviewExecutionLifecycle(
    engine, preview_controller,
    barrier=acceptance_reset.barrier if reset_enabled() else None,
)


@asynccontextmanager
async def _preview_lifespan(_app: Any) -> AsyncIterator[None]:
    preview_lifecycle.start()
    try:
        yield
    finally:
        await run_in_threadpool(preview_lifecycle.stop)


router = APIRouter(prefix="/develop/chats", tags=["develop"], lifespan=_preview_lifespan)


class PreviewLaunchRequest(BaseModel):
    answer: str | None = Field(default=None, max_length=16384)
    pointer: str = Field(default="README.md", max_length=240)


class BrowserSessionRequest(BaseModel):
    credential: str


def _browser_origin() -> str:
    if settings.PREVIEW_ORIGIN is None or settings.PREVIEW_ORIGIN.host == urlsplit(settings.FRONTEND_HOST).hostname:
        raise HTTPException(status_code=503, detail="Preview origin is not configured")
    return str(settings.PREVIEW_ORIGIN).rstrip("/")


def _browser_key() -> bytes:
    return hashlib.sha256((settings.SECRET_KEY + ":preview-browser").encode()).digest()


def _require_browser_host(request: Request) -> str:
    origin = _browser_origin()
    if request.headers.get("host") != origin.split("://", 1)[1] and _service_host(request) is None:
        raise HTTPException(status_code=404, detail="Not found")
    return origin


def _service_origin(chat_id: uuid.UUID, port: str) -> str:
    origin = urlsplit(_browser_origin())
    return f"{origin.scheme}://{chat_id}-{port}.{origin.netloc}"


def _service_host(request: Request) -> tuple[uuid.UUID, str] | None:
    origin = urlsplit(_browser_origin())
    match = re.fullmatch(r"([0-9a-f-]{36})-([0-9]{1,5})\." + re.escape(origin.netloc), request.headers.get("host", ""))
    if match is None:
        return None
    try:
        chat_id = uuid.UUID(match[1])
    except ValueError:
        return None
    if match[1] != str(chat_id) or not 1 <= int(match[2]) <= 65535:
        return None
    return chat_id, match[2]


def _service_cookie(chat_id: uuid.UUID) -> str:
    return f"preview_session_{chat_id.hex}"


def _browser_cookie(request: Request, chat_id: uuid.UUID) -> str:
    name = _service_cookie(chat_id) if _service_host(request) is not None else "preview_session"
    return request.cookies.get(name, "")


def _browser_claims(credential: str, *, session: Session) -> uuid.UUID:
    try:
        claims = jwt.decode(credential, _browser_key(), algorithms=[ALGORITHM], options={"require": ["exp", "chat", "owner"]})
        chat_id = uuid.UUID(claims["chat"])
        owner_id = uuid.UUID(claims["owner"])
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=404, detail="Not found") from None
    chat = session.exec(select(DevelopmentChat).where(
        DevelopmentChat.id == chat_id, DevelopmentChat.owner_id == owner_id,
    )).first()
    if chat is None or not chat.workspace_ready:
        raise HTTPException(status_code=404, detail="Not found")
    return chat_id


SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
SSE_KIND_ALIASES = {
    "activity": "status",
    "response": "text",
    "started": "status",
    "terminal": "done",
}


def _preview_status(chat_id: uuid.UUID) -> dict[str, Any]:
    """Read-only runtime status; never resolves instructions or starts resources."""
    try:
        workload = preview_controller.status(chat_id)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            return {"state": "stopped"}
        raise
    state = workload.get("state", "stopped")
    if state in ("starting", "failed", "stopped", "interrupted"):
        return {**workload, "state": state}
    if state == "ready" or (state == "running" and workload.get("ready", "initial_port" in workload)):
        return {**workload, "state": "ready"}
    return {**workload, "state": "starting"}


def _saved_preview_instructions(session: Session, chat_id: uuid.UUID) -> dict[str, Any]:
    for execution in list_executions(session, chat_id, limit=200):
        saved = execution.workflow_snapshot.get("preview_instructions")
        if isinstance(saved, dict):
            return saved
    return {}


def _operation_response(execution: PreviewExecution, **extra: Any) -> dict[str, Any]:
    state = "ready" if execution.ready else str(execution.status)
    return {"state": state, "ready": execution.ready, "execution": execution_public(execution), **extra}


def _save_preview_instructions(
    session: Session, chat: DevelopmentChat, request: PreviewLaunchRequest, redactor: SecretRedactor
) -> dict[str, Any]:
    _lock_chat(session, chat.id)
    latest = list_executions(session, chat.id, limit=1)
    execution = latest[0] if latest and latest[0].status not in ACTIVE_STATUSES else None
    if execution is None:
        execution = PreviewExecution(chat_id=chat.id, status="failed", finished_at=get_datetime_utc())
        session.add(execution)
        session.flush()
    snapshot = dict(execution.workflow_snapshot)
    for match in re.finditer(r"\b([\w-]+)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s]+)", request.answer or ""):
        if SECRET_KEY.search(match[1]):
            redactor.update_secrets([match[2].strip("\"'")])
    safe_answer = redactor.redact(request.answer or "")
    snapshot["preview_instructions"] = {
        "answer": safe_answer, "pointer": redactor.redact(request.pointer),
        "requires_secret_reference": safe_answer != request.answer,
    }
    execution.workflow_snapshot = snapshot
    _add_event(session, execution, kind="status", payload={
        "status": str(execution.status), "ready": False,
        "reason": "Preview instructions saved for this chat. Click Launch to run them.",
    })
    session.commit()
    return _operation_response(execution, state="stopped", message="Preview instructions saved. Click Launch to run them.")


def _drain_preview_events(session: Session, execution: PreviewExecution) -> None:
    # The stopped journal is immutable, but can span multiple bounded pages.
    # Finish before terminalizing/replacing its owner and clearing runtime caches.
    for _ in range(128):
        after = execution.controller_cursor
        try:
            result = preview_controller.events(execution.chat_id, after)
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                return
            raise
        reported = result.get("execution_id")
        if reported is not None and str(reported) != str(execution.id):
            return
        incoming = result.get("events", [])
        if not isinstance(incoming, list) or len(incoming) > 1000:
            raise ValueError("Invalid controller event batch")
        for offset in range(0, len(incoming), MAX_BATCH_EVENTS):
            append_events(session, execution.id, [
                PreviewEventInput(event["cursor"], event["kind"], event.get("payload", {}))
                for event in incoming[offset:offset + MAX_BATCH_EVENTS]
            ])
        target = result.get("cursor", execution.controller_cursor)
        if not isinstance(target, int) or isinstance(target, bool) or target < 0:
            raise ValueError("Invalid controller journal cursor")
        if execution.controller_cursor >= target:
            return
        if execution.controller_cursor <= after:
            raise RuntimeError("Stopped preview journal did not advance")
    raise RuntimeError("Stopped preview journal exceeded its drain bound")


def _start_preview(
    session: Session, chat: DevelopmentChat,
    request: PreviewLaunchRequest | None = None, *, restart: bool = False,
) -> dict[str, Any]:
    if not chat.workspace_ready:
        raise HTTPException(status_code=409, detail="Development Workspace is not ready")
    request = request or PreviewLaunchRequest()
    checkout = workspace_path(root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=chat.id)
    try:
        redactor = known_secret_redactor(checkout)
    except (OSError, UnicodeError, ValueError):
        redactor = SecretRedactor()
        execution, created = get_or_create_active_execution(session, chat.id)
        if created:
            set_terminal_status(session, execution.id, "failed", reason="Project secret configuration could not be loaded safely.")
        session.commit()
        return _operation_response(execution, message="Project secret configuration could not be loaded safely.")
    if request.answer is not None:
        return _save_preview_instructions(session, chat, request, redactor)
    saved = _saved_preview_instructions(session, chat.id)
    if restart:
        _lock_chat(session, chat.id)
        previous = get_active_execution(session, chat.id)
        try:
            preview_controller.stop(chat.id)
            if previous is not None:
                _drain_preview_events(session, previous)
                if previous.status in ACTIVE_STATUSES:
                    set_terminal_status(session, previous.id, "stopped", reason="Explicit Restart requested by the chat owner.")
                else:
                    _add_event(session, previous, kind="status", payload={"status": str(previous.status), "ready": False, "reason": "Explicit Restart requested by the chat owner."})
        except (httpx.HTTPError, RuntimeError, ValueError):
            session.rollback()
            raise HTTPException(status_code=502, detail="Preview workload could not be stopped for Restart") from None
    execution, created = get_or_create_active_execution(session, chat.id)
    execution_id = execution.id
    session.commit()  # Durable single ownership precedes discovery or provisioning.
    if not created:
        return _operation_response(execution)
    pointer = request.pointer if request.pointer != "README.md" else saved.get("pointer", "README.md")
    answer = saved.get("answer")
    native_runtime = False
    try:
        if saved.get("requires_secret_reference"):
            raise PreviewInstructionsError("Saved instructions contained credential values. Move those values into a checkout-local environment file and save a command or pointer without embedded credentials.")
        native = resolve_native_plan(checkout, pointer=pointer, answer=answer)
        if native is not None:
            payload = native.as_dict()
            native_runtime = True
        else:
            provider_key = settings.OPENAI_API_KEY
            if provider_key is None:
                raise PreviewInstructionsError("Please provide a complete startup command or checkout-local instruction pointer. Launch again after saving instructions.")
            plan = resolve_preview_plan(
                root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=chat.id,
                provider_key=provider_key.get_secret_value(),
                provider_base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
                model=settings.DEVELOP_AGENT_MODEL, answer=answer, pointer=pointer,
            )
            if plan is None:
                raise PreviewInstructionsError("Please provide a complete startup command or checkout-local instruction pointer. Launch again after saving instructions.")
            payload = plan.model_dump()
            classification = classify_workspace(root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=chat.id)
            if plan.website is None and classification.kind == "api_documentation":
                payload["initial_path"] = classification.entry_point
            native_runtime = False
        redactor = known_secret_redactor(checkout, payload)
        snapshot = {**payload, "preview_instructions": saved}
        set_workflow_snapshot(session, execution_id, snapshot, redactor=redactor)
        session.commit()  # Workflow/source/argv are safe and durable before execution.
        _lock_chat(session, chat.id)
        active = get_active_execution(session, chat.id)
        if active is None or active.id != execution_id:
            session.rollback()
            session.refresh(execution)
            return _operation_response(execution)
        # Prevent Restart from stopping a not-yet-dispatched attempt and then
        # allowing its stale creator to provision a runtime after the stop.
        if native_runtime:
            preview_controller.native_launch(chat.id, payload, str(execution_id))
        else:
            preview_controller.start(chat.id)
            preview_controller.launch(chat.id, {**payload, "execution_id": str(execution_id)})
        active.updated_at = get_datetime_utc()
        session.add(active)
        session.commit()
    except PreviewInstructionsError as error:
        session.rollback()
        execution = set_terminal_status(session, execution_id, "failed", reason=str(error), redactor=redactor)
        session.commit()
        return _operation_response(execution, state="needs_instructions", message=redactor.redact(str(error)))
    except (ValueError, OSError, RuntimeError, httpx.HTTPError, KeyError, StopIteration, TypeError) as error:
        session.rollback()
        reason = (
            redactor.redact(str(error))[:8192]
            if native_runtime and isinstance(error, RuntimeError)
            else "Preview startup failed. Check the persisted command diagnostics and deployment configuration."
        )
        execution = set_terminal_status(session, execution_id, "failed", reason=reason, redactor=redactor)
        session.commit()
        return _operation_response(execution, message=reason)
    session.refresh(execution)
    return _operation_response(execution)


def _get_chat(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> DevelopmentChat:
    chat = session.exec(
        select(DevelopmentChat).where(
            DevelopmentChat.id == chat_id,
            DevelopmentChat.owner_id == current_user.id,
        )
    ).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Development Chat not found")
    return chat


def _get_proposal(
    *, session: SessionDep, chat_id: uuid.UUID, message_id: uuid.UUID
) -> DevelopmentMessage:
    proposal = session.exec(
        select(DevelopmentMessage).where(
            DevelopmentMessage.id == message_id,
            DevelopmentMessage.chat_id == chat_id,
            DevelopmentMessage.kind == DevelopmentMessageKind.proposal,
        )
    ).first()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


def _repository_setup_available() -> bool:
    repository, token = effective_repository()
    return bool(repository and token)


def _workspace_status(chat: DevelopmentChat) -> DevelopmentWorkspacePublic:
    return DevelopmentWorkspacePublic(
        ready=chat.workspace_ready,
        setup_available=_repository_setup_available(),
    )


def _serialize_sse_event(event: TurnEvent) -> str:
    kind = SSE_KIND_ALIASES.get(event.kind, event.kind)
    payload = json.dumps(
        {"sequence": event.sequence, "kind": kind, "data": event.data},
        separators=(",", ":"),
    )
    return f"id: {event.sequence}\nevent: {kind}\ndata: {payload}\n\n"


def _stream_turn(
    turn: TurnSession,
    subscriber_id: str,
    buffered_events: tuple[TurnEvent, ...],
) -> Iterator[str]:
    last_sequence = 0
    try:
        for event in buffered_events:
            last_sequence = event.sequence
            yield _serialize_sse_event(event)
        while turn.terminal_state is None:
            work = current_work.get()
            if work is not None and work.cancelled.is_set():
                break
            events = turn.wait_for_events(
                after_sequence=last_sequence,
                timeout=min(settings.DEVELOP_SSE_HEARTBEAT_SECONDS, 0.1) if reset_enabled() else settings.DEVELOP_SSE_HEARTBEAT_SECONDS,
            )
            if not events:
                yield ": heartbeat\n\n"
                continue
            for event in events:
                last_sequence = event.sequence
                yield _serialize_sse_event(event)
        for event in turn.replay(after_sequence=last_sequence):
            yield _serialize_sse_event(event)
    finally:
        turn.detach(
            subscriber_id,
            grace_seconds=settings.DEVELOP_TURN_PRESENCE_GRACE_SECONDS,
        )


def _stream_response(
    turn: TurnSession,
    subscriber_id: str,
    buffered_events: tuple[TurnEvent, ...],
) -> StreamingResponse:
    response_class = CompletionStreamingResponse if reset_enabled() else StreamingResponse
    return response_class(
        _stream_turn(turn, subscriber_id, buffered_events),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


def _start_turn_worker(target: Any, **kwargs: Any) -> None:
    def complete(**values: Any) -> None:
        turn = values["turn"]
        work = current_work.get()
        if work is not None and work.cancelled.is_set():
            turn.request_stop(reason=TurnTerminalState.stopped)
        try:
            target(**values)
        finally:
            # A failure before the agent's own handler must not strand capacity/streams.
            if turn.terminal_state is None:
                develop_turn_manager.finish_turn(turn, TurnTerminalState.failed, "Agent Turn failed")

    if reset_enabled():
        acceptance_reset.barrier.start_thread(complete, kwargs)
    else:
        threading.Thread(target=complete, kwargs=kwargs, daemon=True).start()


def _emit_agent_event(turn: TurnSession, event: AgentEvent) -> None:
    if event.kind == AgentEventKind.session:
        turn.emit("session", event.session_id or "")
    elif event.kind == AgentEventKind.activity:
        turn.emit("status", event.text or "")
    elif event.kind == AgentEventKind.text:
        turn.emit("text", event.text or "")
    elif event.kind == AgentEventKind.error:
        turn.emit("error", event.text or "")


def _publish_turn_message(turn: TurnSession, message: DevelopmentMessage) -> None:
    turn.emit("result", DevelopmentMessagePublic.model_validate(message).model_dump_json())


def _run_streamed_proposal(*, chat_id: uuid.UUID, turn: TurnSession) -> None:
    with Session(engine) as session:
        chat = session.get(DevelopmentChat, chat_id)
        if chat is None:
            develop_turn_manager.finish_turn(turn, TurnTerminalState.failed, "Development Chat not found")
            return
        provider_key = settings.OPENAI_API_KEY
        if provider_key is None:
            turn.emit("error", "Agent provider is not configured")
            develop_turn_manager.finish_turn(turn, TurnTerminalState.failed)
            return
        messages = list(session.exec(
            select(DevelopmentMessage).where(
                DevelopmentMessage.chat_id == chat.id,
                DevelopmentMessage.kind == DevelopmentMessageKind.message,
            ).order_by(col(DevelopmentMessage.created_at), col(DevelopmentMessage.id))
        ).all())
        try:
            completion = execute_proposal(
                root=settings.DEVELOP_WORKSPACE_ROOT,
                chat_id=chat.id,
                messages=messages,
                max_conversation_characters=settings.DEVELOP_AGENT_MAX_CONVERSATION_CHARACTERS,
                session_id=chat.agent_session_id,
                provider_key=provider_key.get_secret_value(),
                provider_base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
                repository_secret=settings.DEMO_GITHUB_TOKEN.get_secret_value() if settings.DEMO_GITHUB_TOKEN else None,
                model=settings.DEVELOP_AGENT_MODEL,
                timeout_seconds=settings.DEVELOP_TURN_TIMEOUT_SECONDS,
                max_activity_parts=settings.DEVELOP_AGENT_MAX_ACTIVITY_PARTS,
                max_part_characters=settings.DEVELOP_AGENT_MAX_PART_CHARACTERS,
                max_response_characters=settings.DEVELOP_AGENT_MAX_RESPONSE_CHARACTERS,
                cancel_event=turn.cancel_event,
                on_event=lambda event: _emit_agent_event(turn, event),
            )
        except (AgentCommandCancelled, AgentCommandTimeout):
            state = turn.stop_reason or TurnTerminalState.timed_out
            content = "Proposal Agent Turn timed out." if state == TurnTerminalState.timed_out else "Proposal Agent Turn was interrupted."
            completion = None
        except AgentCommandError as error:
            logger.error("Agent proposal failed for chat %s: %s", chat.id, error)
            turn.emit("error", "Agent proposal failed")
            develop_turn_manager.finish_turn(turn, TurnTerminalState.failed, "Agent proposal failed")
            return
        completed_at = get_datetime_utc()
        if completion is not None:
            state = TurnTerminalState.completed
            content = completion.response_text
            activity = [part.model_dump() for part in completion.activity]
            chat.agent_session_id = completion.session_id
        else:
            activity = [{"text": content}]
        proposal = DevelopmentMessage(
            role="assistant", content=content, activity=activity,
            duration_seconds=turn.elapsed_seconds(), chat_id=chat.id,
            created_at=completed_at,
            kind=DevelopmentMessageKind.proposal if completion is not None else DevelopmentMessageKind.message,
            proposal_state=DevelopmentProposalState.undecided if completion is not None else None,
        )
        chat.updated_at = completed_at
        session.add(proposal)
        session.add(chat)
        session.commit()
        _publish_turn_message(turn, proposal)
        develop_turn_manager.finish_turn(turn, state, content)


def _run_streamed_exploration(
    *, chat_id: uuid.UUID, message: str, turn: TurnSession
) -> None:
    with Session(engine) as session:
        chat = session.get(DevelopmentChat, chat_id)
        if chat is None:
            develop_turn_manager.finish_turn(
                turn, TurnTerminalState.failed, "Development Chat not found"
            )
            return
        provider_key = settings.OPENAI_API_KEY
        if provider_key is None:
            turn.emit("error", "Agent provider is not configured")
            develop_turn_manager.finish_turn(turn, TurnTerminalState.failed)
            return
        before = snapshot_workspace(
            root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=chat.id
        )
        try:
            completion = execute_exploration(
                root=settings.DEVELOP_WORKSPACE_ROOT,
                chat_id=chat.id,
                message=message,
                session_id=chat.agent_session_id,
                provider_key=provider_key.get_secret_value(),
                provider_base_url=(
                    str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None
                ),
                repository_secret=(
                    settings.DEMO_GITHUB_TOKEN.get_secret_value()
                    if settings.DEMO_GITHUB_TOKEN
                    else None
                ),
                model=settings.DEVELOP_AGENT_MODEL,
                timeout_seconds=settings.DEVELOP_TURN_TIMEOUT_SECONDS,
                max_activity_parts=settings.DEVELOP_AGENT_MAX_ACTIVITY_PARTS,
                max_part_characters=settings.DEVELOP_AGENT_MAX_PART_CHARACTERS,
                max_response_characters=settings.DEVELOP_AGENT_MAX_RESPONSE_CHARACTERS,
                cancel_event=turn.cancel_event,
                on_event=lambda event: _emit_agent_event(turn, event),
            )
        except (AgentCommandCancelled, AgentCommandTimeout) as error:
            state = turn.stop_reason or TurnTerminalState.timed_out
            safe_message = (
                "Agent Turn timed out."
                if state == TurnTerminalState.timed_out
                else "Agent Turn was interrupted."
            )
            logger.info("Agent exploration ended for chat %s: %s", chat.id, error)
            turn.emit("idle", safe_message)
            completion = None
        except AgentCommandError as error:
            logger.error("Agent exploration failed for chat %s: %s", chat.id, error)
            turn.emit("error", "Agent exploration failed")
            develop_turn_manager.finish_turn(
                turn, TurnTerminalState.failed, "Agent exploration failed"
            )
            return

        completed_at = get_datetime_utc()
        if completion is None:
            state = turn.stop_reason or TurnTerminalState.timed_out
            content = (
                "Agent Turn timed out."
                if state == TurnTerminalState.timed_out
                else "Agent Turn was interrupted."
            )
            activity = [{"text": content}]
            session_id = chat.agent_session_id
        else:
            state = TurnTerminalState.completed
            content = completion.response_text
            activity = [part.model_dump() for part in completion.activity]
            session_id = completion.session_id
        assistant_message = DevelopmentMessage(
            role="assistant",
            content=content,
            activity=activity,
            duration_seconds=turn.elapsed_seconds(),
            chat_id=chat.id,
            created_at=completed_at,
        )
        chat.agent_session_id = session_id
        chat.updated_at = completed_at
        session.add(assistant_message)
        session.add(chat)
        session.commit()
        _publish_turn_message(turn, assistant_message)
        if completion is not None:
            after = snapshot_workspace(
                root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=chat.id
            )
            if relevant_turn_change(before, after):
                turn.emit("preview-change", "changed")
        develop_turn_manager.finish_turn(turn, state, content)


def _run_streamed_apply(*, chat_id: uuid.UUID, turn: TurnSession) -> None:
    with Session(engine) as session:
        chat = session.get(DevelopmentChat, chat_id)
        if chat is None:
            develop_turn_manager.finish_turn(
                turn, TurnTerminalState.failed, "Development Chat not found"
            )
            return
        before = snapshot_workspace(root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=chat.id)
        provider_key = settings.OPENAI_API_KEY
        if provider_key is None:
            turn.emit("error", "Agent provider is not configured")
            develop_turn_manager.finish_turn(turn, TurnTerminalState.failed)
            return
        try:
            completion = execute_apply(
                root=settings.DEVELOP_WORKSPACE_ROOT,
                chat_id=chat.id,
                session_id=chat.agent_session_id,
                provider_key=provider_key.get_secret_value(),
                provider_base_url=(
                    str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None
                ),
                repository_secret=(
                    settings.DEMO_GITHUB_TOKEN.get_secret_value()
                    if settings.DEMO_GITHUB_TOKEN
                    else None
                ),
                model=settings.DEVELOP_AGENT_MODEL,
                timeout_seconds=settings.DEVELOP_TURN_TIMEOUT_SECONDS,
                max_activity_parts=settings.DEVELOP_AGENT_MAX_ACTIVITY_PARTS,
                max_part_characters=settings.DEVELOP_AGENT_MAX_PART_CHARACTERS,
                max_response_characters=settings.DEVELOP_AGENT_MAX_RESPONSE_CHARACTERS,
                cancel_event=turn.cancel_event,
                on_event=lambda event: _emit_agent_event(turn, event),
            )
        except (AgentCommandCancelled, AgentCommandTimeout) as error:
            state = turn.stop_reason or TurnTerminalState.timed_out
            content = (
                "Apply Agent Turn timed out."
                if state == TurnTerminalState.timed_out
                else "Apply Agent Turn was interrupted."
            )
            logger.info("Agent apply ended for chat %s: %s", chat.id, error)
            completion = None
        except AgentCommandError as error:
            logger.error("Agent apply failed for chat %s: %s", chat.id, error)
            turn.emit("error", "Agent apply failed")
            develop_turn_manager.finish_turn(
                turn, TurnTerminalState.failed, "Agent apply failed"
            )
            return

        completed_at = get_datetime_utc()
        if completion is None:
            activity = [{"text": content}]
            session_id = chat.agent_session_id
        else:
            state = TurnTerminalState.completed
            content = completion.response_text
            activity = [part.model_dump() for part in completion.activity]
            session_id = completion.session_id
        assistant_message = DevelopmentMessage(
            role="assistant",
            content=content,
            activity=activity,
            duration_seconds=turn.elapsed_seconds(),
            chat_id=chat.id,
            created_at=completed_at,
        )
        chat.agent_session_id = session_id
        chat.updated_at = completed_at
        session.add(assistant_message)
        session.add(chat)
        session.commit()
        _publish_turn_message(turn, assistant_message)
        if completion is not None:
            after = snapshot_workspace(root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=chat.id)
            if relevant_turn_change(before, after):
                turn.emit("preview-change", "changed")
        develop_turn_manager.finish_turn(turn, state, content)


def _encode_cursor(message: DevelopmentMessage) -> str:
    payload = json.dumps([message.created_at.isoformat(), str(message.id)]).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        created_at_value, message_id_value = json.loads(
            base64.urlsafe_b64decode(cursor + padding)
        )
        created_at = datetime.fromisoformat(created_at_value)
        message_id = uuid.UUID(message_id_value)
        if created_at.tzinfo is None:
            raise ValueError
    except ValueError, TypeError, json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Invalid message cursor")
    return created_at, message_id


@router.post("", response_model=DevelopmentChatPublic)
def create_development_chat(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    chat_in: DevelopmentChatCreate,
) -> Any:
    now = get_datetime_utc()
    title = chat_in.content.splitlines()[0][:255]
    chat = DevelopmentChat(
        title=title,
        owner_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    message = DevelopmentMessage(
        role="user",
        content=chat_in.content,
        chat_id=chat.id,
        created_at=now,
    )
    session.add(chat)
    session.add(message)
    session.commit()
    session.refresh(chat)
    return chat


@router.get("", response_model=DevelopmentChatsPublic)
def read_development_chats(*, session: SessionDep, current_user: CurrentUser) -> Any:
    count = session.exec(
        select(func.count())
        .select_from(DevelopmentChat)
        .where(DevelopmentChat.owner_id == current_user.id)
    ).one()
    chats = session.exec(
        select(DevelopmentChat)
        .where(DevelopmentChat.owner_id == current_user.id)
        .order_by(
            col(DevelopmentChat.updated_at).desc(), col(DevelopmentChat.id).desc()
        )
        .limit(settings.DEVELOP_HISTORY_LIMIT)
    ).all()
    return DevelopmentChatsPublic(data=list(chats), count=count)


@router.get("/{chat_id}", response_model=DevelopmentChatPublic)
def read_development_chat(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> Any:
    return _get_chat(session=session, current_user=current_user, chat_id=chat_id)


@router.get("/{chat_id}/workspace", response_model=DevelopmentWorkspacePublic)
def read_development_workspace(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> Any:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    return _workspace_status(chat)


@router.post("/{chat_id}/workspace/setup", response_model=DevelopmentWorkspacePublic)
def setup_development_workspace(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> Any:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    repository_url, repository_token = effective_repository()
    if not repository_url or not repository_token:
        raise HTTPException(
            status_code=503,
            detail="Demo repository setup is not configured",
        )

    chat.workspace_ready = False
    session.add(chat)
    session.commit()
    runner = (
        FakeCommandRunner()
        if settings.DEVELOP_FAKE_SETUP_RUNNER
        else SubprocessCommandRunner()
    )
    try:
        setup_workspace(
            root=settings.DEVELOP_WORKSPACE_ROOT,
            chat_id=chat.id,
            repository_url=str(repository_url),
            repository_token=repository_token.get_secret_value(),
            timeout=settings.DEVELOP_SETUP_TIMEOUT_SECONDS,
            runner=runner,
        )
    except WorkspaceSetupError:
        raise HTTPException(
            status_code=502,
            detail="Demo repository setup failed",
        )

    chat.workspace_ready = True
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return _workspace_status(chat)


@router.patch("/{chat_id}", response_model=DevelopmentChatPublic)
def rename_development_chat(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    chat_id: uuid.UUID,
    chat_in: DevelopmentChatUpdate,
) -> Any:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    if chat_in.title is not None:
        chat.title = chat_in.title
    if chat_in.presence_mode is not None:
        chat.presence_mode = chat_in.presence_mode
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return chat


@router.put("/{chat_id}/presence", response_model=DevelopmentChatPublic)
def update_development_presence(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    chat_id: uuid.UUID,
    presence_in: DevelopmentPresenceUpdate,
) -> Any:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    chat.presence_mode = presence_in.presence_mode
    active_turn = develop_turn_manager.active_turn(chat.id)
    if active_turn is not None:
        active_turn.presence_mode = presence_in.presence_mode
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return chat


@router.delete("/{chat_id}", response_model=Message)
def delete_development_chat(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    chat_id: uuid.UUID,
    confirm: bool = False,
) -> Any:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Development Chat deletion requires confirmation",
        )
    if not develop_turn_manager.stop_and_wait(
        chat.id,
        timeout=settings.DEVELOP_AGENT_TERMINATION_GRACE_SECONDS + 1,
    ):
        raise HTTPException(
            status_code=409,
            detail="Active Agent Turn did not stop before deletion",
        )
    try:
        preview_controller.stop(chat.id)
    except httpx.HTTPError, RuntimeError:
        raise HTTPException(status_code=502, detail="Preview workload cleanup failed")
    try:
        cleanup_workspace(root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=chat.id)
    except OSError, WorkspacePathError:
        raise HTTPException(
            status_code=500,
            detail="Development Workspace cleanup failed",
        )
    session.delete(chat)
    session.commit()
    return Message(message="Development Chat deleted")


@router.post("/{chat_id}/preview/start")
def start_development_preview(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> Any:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    return _start_preview(session, chat)


@router.post("/{chat_id}/preview/browser-session")
def issue_browser_session(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID,
) -> dict[str, Any]:
    origin = _browser_origin()
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    ready = _preview_status(chat.id) if chat.workspace_ready else {}
    if ready.get("state") != "ready":
        raise HTTPException(status_code=409, detail="Preview is not ready")
    credential = jwt.encode({
        "chat": str(chat.id), "owner": str(current_user.id),
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }, _browser_key(), algorithm=ALGORITHM)
    ports = {key: _service_origin(chat.id, ready[key]) for key in ("initial_port", "website_port", "api_port") if key in ready}
    return {"chat_id": str(chat.id), "origin": origin, "services": ports,
            "initial_url": ports["initial_port"] + ready.get("initial_path", "/"),
            "credential": credential, "expires_in": 300}


@router.post("/preview-browser/session")
async def exchange_browser_session(
    *, request: Request, session: SessionDep,
) -> Response:
    origin = _require_browser_host(request)
    body = await request.body()
    if len(body) > 8192:
        raise HTTPException(status_code=413, detail="Browser session request is too large")
    form = request.headers.get("content-type", "").split(";", 1)[0] == "application/x-www-form-urlencoded"
    try:
        if form:
            values = parse_qs(body.decode("utf-8"), strict_parsing=True)
            if set(values) != {"credential"} or len(values["credential"]) != 1:
                raise ValueError
            credential = values["credential"][0]
        else:
            credential = BrowserSessionRequest.model_validate_json(body).credential
    except (UnicodeError, ValueError):
        raise HTTPException(status_code=422, detail="Invalid browser session request") from None
    chat_id = _browser_claims(credential, session=session)
    service = _service_host(request)
    if service is not None:
        if service[0] != chat_id:
            raise HTTPException(status_code=404, detail="Not found")
        ready = await run_in_threadpool(_preview_status, chat_id) if reset_enabled() else _preview_status(chat_id)
        if service[1] not in (ready.get("initial_port"), ready.get("website_port"), ready.get("api_port")):
            raise HTTPException(status_code=404, detail="Not found")
    path = "/" if service is not None else f"{settings.API_V1_STR}/develop/chats/preview-browser/{chat_id}/"
    redirect_path = path
    if service is not None and service[1] == ready["initial_port"]:
        redirect_path = ready.get("initial_path", "/")
    response = Response(status_code=303 if form else 200, headers={
        "Cache-Control": "no-store", "Content-Security-Policy": f"frame-ancestors {settings.FRONTEND_HOST}",
        **({"Location": redirect_path} if form else {}),
    })
    response.set_cookie(_service_cookie(chat_id) if service is not None else "preview_session",
                        credential, max_age=300, httponly=True,
                        secure=origin.startswith("https://"), samesite="none" if origin.startswith("https://") else "lax",
                        path=path, domain=settings.PREVIEW_ORIGIN.host if service is not None else None)
    return response


async def browser_service_resource(request: Request, session: SessionDep, asset_path: str) -> Response:
    service = _service_host(request)
    if service is None:
        raise HTTPException(status_code=404, detail="Not found")
    chat_id, port = service
    return await browser_preview_resource(request=request, session=session, chat_id=chat_id,
                                          asset_path=f"localhost/{port}/{asset_path}")


async def browser_service_socket(websocket: WebSocket, session: SessionDep, asset_path: str) -> None:
    service = _service_host(websocket)
    if service is None:
        await websocket.close(code=1008)
        return
    chat_id, port = service
    await browser_preview_socket(websocket, session, chat_id, f"localhost/{port}/{asset_path}")


@router.api_route("/preview-browser/{chat_id}/{asset_path:path}", methods=["GET", "POST"])
async def browser_preview_resource(
    *, request: Request, session: SessionDep, chat_id: uuid.UUID, asset_path: str,
) -> Response:
    origin = _require_browser_host(request)
    service = _service_host(request)
    if request.method == "POST" and request.headers.get("origin") != (
        _service_origin(*service) if service is not None else origin
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    if _browser_claims(_browser_cookie(request, chat_id), session=session) != chat_id:
        raise HTTPException(status_code=404, detail="Not found")
    port = None
    if asset_path.startswith("localhost/"):
        parts = asset_path.split("/", 2)
        if len(parts) < 2 or not parts[1].isdigit():
            raise HTTPException(status_code=404, detail="Not found")
        port = parts[1]
        asset_path = parts[2] if len(parts) == 3 else ""
    if urlsplit(asset_path).scheme:
        raise HTTPException(status_code=404, detail="Not found")
    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    body = None
    if request.method == "POST":
        if content_type not in ("application/x-www-form-urlencoded", "multipart/form-data", "text/plain", "application/json"):
            raise HTTPException(status_code=415, detail="Unsupported preview form")
        body = await request.body()
        if len(body) > 32768:
            raise HTTPException(status_code=413, detail="Preview form is too large")
    forwarded_cookies = []
    if service is not None:
        raw_cookie = request.headers.get("cookie", "")
        if len(raw_cookie) > 8192:
            raise HTTPException(status_code=400, detail="Preview cookie is too large")
        for raw_pair in raw_cookie.split(";") if raw_cookie else []:
            name, separator, value = raw_pair.strip().partition("=")
            if not separator or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
                raise HTTPException(status_code=400, detail="Invalid preview cookie")
            cookie_value = value[1:-1] if value.startswith('"') and value.endswith('"') else value
            if not re.fullmatch(r"[\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]*", cookie_value):
                raise HTTPException(status_code=400, detail="Invalid preview cookie")
            if name != "preview_session" and not name.startswith("preview_session_"):
                forwarded_cookies.append(f"{name}={value}")
    forwarded_cookie = "; ".join(forwarded_cookies)
    if len(forwarded_cookie) > 8192:
        raise HTTPException(status_code=400, detail="Preview cookie is too large")
    try:
        project_authorization = request.headers.get("authorization", "")
        fetch_preview = partial(preview_controller.fetch, chat_id, "/" + asset_path, request.url.query, port, body,
                                request.headers.get("content-type", "") if body is not None else "", forwarded_cookie,
                                **({"authorization": project_authorization} if project_authorization else {}))
        result = await run_in_threadpool(fetch_preview) if reset_enabled() else fetch_preview()
    except (httpx.HTTPError, FileNotFoundError, RuntimeError, ValueError):
        raise HTTPException(status_code=404, detail="Not found") from None
    headers = {
        "Content-Type": result["content_type"], "Cache-Control": "no-store",
        "Content-Security-Policy": f"frame-ancestors {settings.FRONTEND_HOST}",
        "X-Content-Type-Options": "nosniff",
    }
    if 300 <= result["status"] < 400:
        location = urlsplit(result["location"])
        redirect_port = port
        if location.scheme or location.netloc:
            if location.scheme != "http" or location.hostname not in ("localhost", "127.0.0.1"):
                raise HTTPException(status_code=404, detail="Not found")
            try:
                redirect_port = str(location.port or 80)
            except ValueError:
                raise HTTPException(status_code=404, detail="Not found") from None
            ready = await run_in_threadpool(_preview_status, chat_id) if reset_enabled() else _preview_status(chat_id)
            if redirect_port not in (ready.get("initial_port"), ready.get("website_port"), ready.get("api_port")):
                raise HTTPException(status_code=404, detail="Not found")
            redirect_path = location.path
        else:
            if result["location"].startswith("//"):
                raise HTTPException(status_code=404, detail="Not found")
            redirect_path = urlsplit(urljoin("http://localhost/" + asset_path, result["location"])).path
        service = _service_host(request)
        if service is not None:
            base = _service_origin(chat_id, redirect_port or service[1])
        else:
            base = f"{settings.API_V1_STR}/develop/chats/preview-browser/{chat_id}/"
            if redirect_port is not None:
                base += f"localhost/{redirect_port}/"
        headers["Location"] = base.rstrip("/") + redirect_path
        if location.query:
            headers["Location"] += "?" + location.query
    response = Response(content=result["body"], status_code=result["status"], headers=headers)
    cookies = result.get("cookies", [])
    if service is not None and isinstance(cookies, list) and len(cookies) <= 8:
        for raw_cookie in cookies:
            if not isinstance(raw_cookie, str) or len(raw_cookie) > 4096 or any(ord(char) < 32 or ord(char) == 127 for char in raw_cookie):
                continue
            parsed_cookie = SimpleCookie()
            try:
                parsed_cookie.load(raw_cookie)
            except CookieError:
                continue
            if len(parsed_cookie) != 1:
                continue
            name, morsel = next(iter(parsed_cookie.items()))
            if name == "preview_session" or name.startswith("preview_session_"):
                continue
            same_site = morsel["samesite"].capitalize() if morsel["samesite"].lower() in ("lax", "strict", "none") else "lax"
            path = morsel["path"] if morsel["path"].startswith("/") and not morsel["path"].startswith("//") else "/"
            response.set_cookie(name, morsel.value, path=path, secure=origin.startswith("https://") or bool(morsel["secure"]),
                                httponly=bool(morsel["httponly"]), samesite=same_site,
                                max_age=int(morsel["max-age"]) if re.fullmatch(r"-?[0-9]{1,10}", morsel["max-age"]) else None,
                                expires=morsel["expires"] or None)
    return response


@router.websocket("/preview-browser/{chat_id}/{asset_path:path}")
async def browser_preview_socket(
    websocket: WebSocket, session: SessionDep, chat_id: uuid.UUID, asset_path: str,
) -> None:
    try:
        origin = _require_browser_host(websocket)
        service = _service_host(websocket)
        expected_origin = _service_origin(*service) if service is not None else origin
        if websocket.headers.get("origin") != expected_origin:
            raise ValueError("Invalid preview origin")
        if _browser_claims(_browser_cookie(websocket, chat_id), session=session) != chat_id:
            raise ValueError("Not found")
        parts = asset_path.split("/", 2)
        if len(parts) != 3 or parts[0] != "localhost" or not parts[1].isdigit():
            raise ValueError("Invalid preview port")
        port = parts[1]
        path = "/" + parts[2]
        if path.startswith("//") or len(path) + len(websocket.url.query) > 2000:
            raise ValueError("Invalid preview path")
        offered = websocket.headers.get("sec-websocket-protocol", "")
        protocols = [value.strip() for value in offered.split(",")] if offered else []
        if len(offered) > 256 or len(protocols) > 8 or any(
            not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", value) for value in protocols
        ):
            raise ValueError("Invalid preview protocols")
        target = f"ws://preview-controller:8090/workloads/{chat_id}/browser?path="
        target += quote(path + ("?" + websocket.url.query if websocket.url.query else ""), safe="")
        target += f"&port={port}"
        async with websockets.connect(target, subprotocols=protocols or None, max_size=2 * 1024 * 1024) as upstream:
            await websocket.accept(subprotocol=upstream.subprotocol)

            async def to_upstream() -> None:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        break
                    data = message.get("bytes") if message.get("bytes") is not None else message.get("text")
                    if data is not None:
                        await upstream.send(data)

            async def to_browser() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            tasks = [asyncio.create_task(to_upstream()), asyncio.create_task(to_browser())]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                import anyio

                for task in tasks:
                    if not task.done():
                        task.cancel()
                with anyio.CancelScope(shield=True):
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await upstream.close()
    except (HTTPException, ValueError, OSError, websockets.WebSocketException) as error:
        logger.warning("Preview WebSocket rejected: %s", error)
        await websocket.close(code=1008)


@router.get("/{chat_id}/preview/context")
def development_preview_context(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> Any:
    """Checkout-local discovery and status only: no model, preflight or launch."""
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    if not chat.workspace_ready:
        return {"state": "unavailable", "message": "Set up the repository to preview this chat."}
    try:
        checkout = workspace_path(root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=chat.id)
        saved = _saved_preview_instructions(session, chat.id)
        native = resolve_native_plan(checkout, pointer=saved.get("pointer"), answer=saved.get("answer"))
        if native is None:
            return {
                "state": "needs_instructions", "runtime": "unsupported",
                "message": "Context requires checkout-local Docker Compose startup instructions. Non-Compose preview APIs remain available separately.",
            }
    except (ValueError, OSError, RuntimeError):
        return {"state": "needs_instructions", "runtime": "compose", "message": "The checkout-local startup instructions are missing, conflicting or unsafe. Provide an unambiguous local command or documentation pointer."}
    try:
        current = _preview_status(chat.id)
    except httpx.HTTPError:
        return {"state": "failed", "runtime": "compose", "message": "Preview controller unavailable."}
    if current.get("state") == "ready" and current.get("runtime") not in ("compose", "native-compose"):
        return {"state": "unsupported", "runtime": "unsupported", "message": "An existing non-Compose runtime is not embedded in Context. It has not been restarted."}
    return {**current, "runtime": "compose"}


@router.get("/{chat_id}/preview/status")
def development_preview_status(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> Any:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    if not chat.workspace_ready:
        return {"state": "unavailable"}
    try:
        return _preview_status(chat.id)
    except httpx.HTTPError:
        return {"state": "failed"}


@router.post("/{chat_id}/preview/restart")
def restart_development_preview(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> Any:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    return _start_preview(session, chat, restart=True)


@router.post("/{chat_id}/preview/launch")
def launch_development_preview(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID,
    request: PreviewLaunchRequest,
) -> Any:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    return _start_preview(session, chat, request)


@router.get("/{chat_id}/preview/executions")
def read_preview_executions(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID,
    before: str | None = None,
) -> dict[str, Any]:
    _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    executions = list_executions(session, chat_id, limit=200, before=_decode_cursor(before) if before else None)
    data = [execution_public(execution) for execution in executions]
    cursor = None
    if len(executions) == 200:
        cursor = base64.urlsafe_b64encode(json.dumps([data[-1]["created_at"], data[-1]["id"]]).encode()).decode().rstrip("=")
    return {"data": data, "has_more": len(executions) == 200, "next_cursor": cursor}


def _get_preview_execution(session: Session, chat_id: uuid.UUID, execution_id: uuid.UUID) -> PreviewExecution:
    execution = get_execution_for_chat(session, chat_id, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Preview execution not found")
    return execution


@router.get("/{chat_id}/preview/executions/{execution_id}/events")
def read_preview_execution_events(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID,
    execution_id: uuid.UUID, after: int = 0,
) -> dict[str, Any]:
    _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    _get_preview_execution(session, chat_id, execution_id)
    if after < 0:
        raise HTTPException(status_code=422, detail="Invalid preview event cursor")
    events = read_events(session, execution_id, after_sequence=after, limit=257)
    page = events[:256]
    return {"data": [event_public(event) for event in page], "has_more": len(events) > 256,
            "next_sequence": page[-1].sequence if page else after}


@router.get("/{chat_id}/preview/executions/{execution_id}/stream", response_model=None)
def stream_preview_execution(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID,
    execution_id: uuid.UUID, after: int = 0,
) -> StreamingResponse:
    _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    _get_preview_execution(session, chat_id, execution_id)
    if after < 0:
        raise HTTPException(status_code=422, detail="Invalid preview event cursor")
    # Do not keep a request transaction open while polling independent committed rows.
    owner_id = current_user.id
    session.commit()
    response_class = CompletionStreamingResponse if reset_enabled() else StreamingResponse
    return response_class(
        preview_lifecycle.stream(chat_id, execution_id, owner_id, after=after),
        media_type="text/event-stream", headers=SSE_HEADERS,
    )


@router.post("/{chat_id}/preview/activity", response_model=dict[str, Any])
def record_development_preview_activity(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> Any:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    try:
        return preview_controller.activity(chat.id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Preview workload not found")
        raise HTTPException(status_code=502, detail="Preview controller unavailable")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Preview controller unavailable")


@router.get("/{chat_id}/messages", response_model=DevelopmentMessagesPublic)
def read_development_messages(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    chat_id: uuid.UUID,
    before: str | None = None,
    after: str | None = None,
) -> Any:
    _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    if before and after:
        raise HTTPException(
            status_code=422, detail="Use either before or after, not both"
        )

    statement = select(DevelopmentMessage).where(DevelopmentMessage.chat_id == chat_id)
    ascending = after is not None
    cursor = after or before
    if cursor:
        created_at, message_id = _decode_cursor(cursor)
        if ascending:
            statement = statement.where(
                or_(
                    col(DevelopmentMessage.created_at) > created_at,
                    and_(
                        col(DevelopmentMessage.created_at) == created_at,
                        col(DevelopmentMessage.id) > message_id,
                    ),
                )
            )
        else:
            statement = statement.where(
                or_(
                    col(DevelopmentMessage.created_at) < created_at,
                    and_(
                        col(DevelopmentMessage.created_at) == created_at,
                        col(DevelopmentMessage.id) < message_id,
                    ),
                )
            )

    if ascending:
        statement = statement.order_by(
            col(DevelopmentMessage.created_at), col(DevelopmentMessage.id)
        )
    else:
        statement = statement.order_by(
            col(DevelopmentMessage.created_at).desc(),
            col(DevelopmentMessage.id).desc(),
        )

    messages = list(
        session.exec(statement.limit(settings.DEVELOP_MESSAGE_PAGE_SIZE + 1)).all()
    )
    has_more = len(messages) > settings.DEVELOP_MESSAGE_PAGE_SIZE
    messages = messages[: settings.DEVELOP_MESSAGE_PAGE_SIZE]
    if not ascending:
        messages.reverse()
    next_cursor = None
    if has_more and messages:
        next_cursor = _encode_cursor(messages[-1] if ascending else messages[0])
    return DevelopmentMessagesPublic(
        data=[DevelopmentMessagePublic.model_validate(message) for message in messages],
        has_more=has_more,
        next_cursor=next_cursor,
    )


@router.post("/{chat_id}/messages/propose/stream", response_model=None)
def stream_development_chat_proposal(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID,
) -> StreamingResponse:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    if not chat.workspace_ready:
        raise HTTPException(status_code=409, detail="Development Workspace is not ready")
    if settings.OPENAI_API_KEY is None:
        raise HTTPException(status_code=503, detail="Agent provider is not configured")
    try:
        turn = develop_turn_manager.start_turn(
            chat_id=chat.id, user_id=current_user.id,
            user_limit=current_user.concurrent_agent_turn_limit,
            presence_mode=chat.presence_mode,
            replay_limit=settings.DEVELOP_TURN_REPLAY_LIMIT,
            timeout_seconds=settings.DEVELOP_TURN_TIMEOUT_SECONDS,
        )
    except ChatTurnActiveError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except UserTurnLimitError as error:
        raise HTTPException(status_code=429, detail=str(error))
    turn.emit("session", chat.agent_session_id or "")
    turn.emit("status", "Agent Turn started")
    subscriber_id = uuid.uuid4().hex
    buffered_events = turn.attach(subscriber_id)
    _start_turn_worker(_run_streamed_proposal, chat_id=chat.id, turn=turn)
    return _stream_response(turn, subscriber_id, buffered_events)


@router.post(
    "/{chat_id}/messages/propose",
    response_model=DevelopmentMessagePublic,
)
def propose_development_chat(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> Any:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    if not chat.workspace_ready:
        raise HTTPException(
            status_code=409, detail="Development Workspace is not ready"
        )
    provider_key = settings.OPENAI_API_KEY
    if provider_key is None:
        raise HTTPException(status_code=503, detail="Agent provider is not configured")
    try:
        turn = develop_turn_manager.start_turn(
            chat_id=chat.id,
            user_id=current_user.id,
            user_limit=current_user.concurrent_agent_turn_limit,
            presence_mode=chat.presence_mode,
            replay_limit=settings.DEVELOP_TURN_REPLAY_LIMIT,
            timeout_seconds=settings.DEVELOP_TURN_TIMEOUT_SECONDS,
        )
    except ChatTurnActiveError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except UserTurnLimitError as error:
        raise HTTPException(status_code=429, detail=str(error))

    messages = list(
        session.exec(
            select(DevelopmentMessage)
            .where(
                DevelopmentMessage.chat_id == chat.id,
                DevelopmentMessage.kind == DevelopmentMessageKind.message,
            )
            .order_by(col(DevelopmentMessage.created_at), col(DevelopmentMessage.id))
        ).all()
    )
    try:
        completion = execute_proposal(
            root=settings.DEVELOP_WORKSPACE_ROOT,
            chat_id=chat.id,
            messages=messages,
            max_conversation_characters=settings.DEVELOP_AGENT_MAX_CONVERSATION_CHARACTERS,
            session_id=chat.agent_session_id,
            provider_key=provider_key.get_secret_value(),
            provider_base_url=(
                str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None
            ),
            repository_secret=(
                settings.DEMO_GITHUB_TOKEN.get_secret_value()
                if settings.DEMO_GITHUB_TOKEN
                else None
            ),
            model=settings.DEVELOP_AGENT_MODEL,
            timeout_seconds=settings.DEVELOP_TURN_TIMEOUT_SECONDS,
            max_activity_parts=settings.DEVELOP_AGENT_MAX_ACTIVITY_PARTS,
            max_part_characters=settings.DEVELOP_AGENT_MAX_PART_CHARACTERS,
            max_response_characters=settings.DEVELOP_AGENT_MAX_RESPONSE_CHARACTERS,
            cancel_event=turn.cancel_event,
            on_event=lambda event: _emit_agent_event(turn, event),
        )
    except AgentCommandError as error:
        develop_turn_manager.finish_turn(
            turn, TurnTerminalState.failed, "Agent proposal failed"
        )
        detail = (
            f"Agent proposal failed: {error}"
            if settings.DEVELOP_ACCEPTANCE_MODE
            else "Agent proposal failed"
        )
        raise HTTPException(status_code=502, detail=detail)

    completed_at = get_datetime_utc()
    proposal = DevelopmentMessage(
        role="assistant",
        content=completion.response_text,
        activity=[part.model_dump() for part in completion.activity],
        duration_seconds=turn.elapsed_seconds(),
        kind=DevelopmentMessageKind.proposal,
        proposal_state=DevelopmentProposalState.undecided,
        chat_id=chat.id,
        created_at=completed_at,
    )
    chat.agent_session_id = completion.session_id
    chat.updated_at = completed_at
    session.add(proposal)
    session.add(chat)
    session.commit()
    session.refresh(proposal)
    develop_turn_manager.finish_turn(
        turn, TurnTerminalState.completed, "Proposal created"
    )
    return proposal


@router.post(
    "/{chat_id}/messages/{message_id}/reject",
    response_model=DevelopmentMessagePublic,
)
def reject_development_proposal(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
) -> Any:
    _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    proposal = _get_proposal(session=session, chat_id=chat_id, message_id=message_id)
    result = session.exec(
        update(DevelopmentMessage)
        .where(
            col(DevelopmentMessage.id) == proposal.id,
            col(DevelopmentMessage.proposal_state)
            == DevelopmentProposalState.undecided,
        )
        .values(proposal_state=DevelopmentProposalState.rejected)
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(status_code=409, detail="Proposal is already decided")
    session.commit()
    session.refresh(proposal)
    return proposal


@router.post(
    "/{chat_id}/messages/{message_id}/approve/stream",
    response_model=None,
)
def approve_development_proposal(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
) -> StreamingResponse:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    proposal = _get_proposal(session=session, chat_id=chat_id, message_id=message_id)
    if proposal.proposal_state != DevelopmentProposalState.undecided:
        raise HTTPException(status_code=409, detail="Proposal is already decided")
    if not chat.workspace_ready:
        raise HTTPException(
            status_code=409, detail="Development Workspace is not ready"
        )
    if settings.OPENAI_API_KEY is None:
        raise HTTPException(status_code=503, detail="Agent provider is not configured")
    try:
        turn = develop_turn_manager.start_turn(
            chat_id=chat.id,
            user_id=current_user.id,
            user_limit=current_user.concurrent_agent_turn_limit,
            weight=settings.DEVELOP_APPLY_TURN_WEIGHT,
            presence_mode=chat.presence_mode,
            replay_limit=settings.DEVELOP_TURN_REPLAY_LIMIT,
            timeout_seconds=settings.DEVELOP_TURN_TIMEOUT_SECONDS,
        )
    except ChatTurnActiveError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except UserTurnLimitError as error:
        raise HTTPException(status_code=429, detail=str(error))

    result = session.exec(
        update(DevelopmentMessage)
        .where(
            col(DevelopmentMessage.id) == proposal.id,
            col(DevelopmentMessage.proposal_state)
            == DevelopmentProposalState.undecided,
        )
        .values(proposal_state=DevelopmentProposalState.approved)
    )
    if result.rowcount != 1:
        session.rollback()
        develop_turn_manager.finish_turn(
            turn, TurnTerminalState.failed, "Proposal is already decided"
        )
        raise HTTPException(status_code=409, detail="Proposal is already decided")
    session.commit()
    turn.emit("session", chat.agent_session_id or "")
    turn.emit("status", "Agent Turn started")
    subscriber_id = uuid.uuid4().hex
    buffered_events = turn.attach(subscriber_id)
    _start_turn_worker(_run_streamed_apply, chat_id=chat.id, turn=turn)
    return _stream_response(turn, subscriber_id, buffered_events)


@router.get("/{chat_id}/turns/current")
def read_current_turn(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> dict[str, Any]:
    _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    turn = develop_turn_manager.active_turn(chat_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="No active Agent Turn")
    return {
        "running": turn.terminal_state is None,
        "subscriber_count": turn.subscriber_count,
        "cancel_requested": turn.cancel_event.is_set(),
        "stop_reason": turn.stop_reason,
        "events": [event.__dict__ for event in turn.replay()],
    }


@router.get("/{chat_id}/turns/current/stream", response_model=None)
def stream_current_turn(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> StreamingResponse:
    _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    turn = develop_turn_manager.active_turn(chat_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="No active Agent Turn")
    subscriber_id = uuid.uuid4().hex
    buffered_events = turn.attach(subscriber_id)
    return _stream_response(turn, subscriber_id, buffered_events)


@router.post("/{chat_id}/turns/current/attach")
def attach_current_turn(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> dict[str, Any]:
    _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    events = develop_turn_manager.attach(chat_id, str(current_user.id))
    if events is None:
        raise HTTPException(status_code=404, detail="No active Agent Turn")
    return {"events": [event.__dict__ for event in events]}


@router.delete("/{chat_id}/turns/current/attach", response_model=Message)
def detach_current_turn(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> Message:
    _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    if not develop_turn_manager.detach(
        chat_id,
        str(current_user.id),
        grace_seconds=settings.DEVELOP_TURN_PRESENCE_GRACE_SECONDS,
    ):
        raise HTTPException(status_code=404, detail="No active Agent Turn")
    return Message(message="Detached from Agent Turn")


@router.delete("/{chat_id}/turns/current", response_model=Message)
def stop_current_turn(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> Message:
    _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    turn = develop_turn_manager.request_stop(chat_id)
    if turn is None:
        return Message(message="Agent Turn is not running")
    if not turn.wait_terminal(settings.DEVELOP_AGENT_TERMINATION_GRACE_SECONDS + 1):
        raise HTTPException(status_code=409, detail="Agent Turn did not stop")
    return Message(message="Agent Turn stopped")


@router.post("/{chat_id}/messages/explore/stream", response_model=None)
def stream_development_chat_exploration(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    chat_id: uuid.UUID,
    message_in: DevelopmentMessageCreate,
) -> StreamingResponse:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    if not chat.workspace_ready:
        raise HTTPException(
            status_code=409, detail="Development Workspace is not ready"
        )
    if settings.OPENAI_API_KEY is None:
        raise HTTPException(status_code=503, detail="Agent provider is not configured")
    try:
        turn = develop_turn_manager.start_turn(
            chat_id=chat.id,
            user_id=current_user.id,
            user_limit=current_user.concurrent_agent_turn_limit,
            presence_mode=chat.presence_mode,
            replay_limit=settings.DEVELOP_TURN_REPLAY_LIMIT,
            timeout_seconds=settings.DEVELOP_TURN_TIMEOUT_SECONDS,
        )
    except ChatTurnActiveError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except UserTurnLimitError as error:
        raise HTTPException(status_code=429, detail=str(error))

    now = get_datetime_utc()
    session.add(
        DevelopmentMessage(
            role="user", content=message_in.content, chat_id=chat.id, created_at=now
        )
    )
    chat.updated_at = now
    session.add(chat)
    session.commit()
    turn.emit("session", chat.agent_session_id or "")
    turn.emit("status", "Agent Turn started")
    subscriber_id = uuid.uuid4().hex
    buffered_events = turn.attach(subscriber_id)
    _start_turn_worker(_run_streamed_exploration, chat_id=chat.id, message=message_in.content, turn=turn)
    return _stream_response(turn, subscriber_id, buffered_events)


@router.post(
    "/{chat_id}/messages/explore",
    response_model=DevelopmentMessagePublic,
)
def explore_development_chat(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    chat_id: uuid.UUID,
    message_in: DevelopmentMessageCreate,
) -> Any:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    if not chat.workspace_ready:
        raise HTTPException(
            status_code=409, detail="Development Workspace is not ready"
        )
    provider_key = settings.OPENAI_API_KEY
    if provider_key is None:
        raise HTTPException(status_code=503, detail="Agent provider is not configured")

    try:
        turn = develop_turn_manager.start_turn(
            chat_id=chat.id,
            user_id=current_user.id,
            user_limit=current_user.concurrent_agent_turn_limit,
            presence_mode=chat.presence_mode,
            replay_limit=settings.DEVELOP_TURN_REPLAY_LIMIT,
            timeout_seconds=settings.DEVELOP_TURN_TIMEOUT_SECONDS,
        )
    except ChatTurnActiveError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except UserTurnLimitError as error:
        raise HTTPException(status_code=429, detail=str(error))
    turn.attach(str(current_user.id))
    turn.emit("session", chat.agent_session_id or "")
    turn.emit("status", "Agent Turn started")

    now = get_datetime_utc()
    user_message = DevelopmentMessage(
        role="user",
        content=message_in.content,
        chat_id=chat.id,
        created_at=now,
    )
    chat.updated_at = now
    session.add(user_message)
    session.add(chat)
    session.commit()

    before = snapshot_workspace(root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=chat.id)
    try:
        completion = execute_exploration(
            root=settings.DEVELOP_WORKSPACE_ROOT,
            chat_id=chat.id,
            message=message_in.content,
            session_id=chat.agent_session_id,
            provider_key=provider_key.get_secret_value(),
            provider_base_url=(
                str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None
            ),
            repository_secret=(
                settings.DEMO_GITHUB_TOKEN.get_secret_value()
                if settings.DEMO_GITHUB_TOKEN
                else None
            ),
            model=settings.DEVELOP_AGENT_MODEL,
            timeout_seconds=settings.DEVELOP_TURN_TIMEOUT_SECONDS,
            max_activity_parts=settings.DEVELOP_AGENT_MAX_ACTIVITY_PARTS,
            max_part_characters=settings.DEVELOP_AGENT_MAX_PART_CHARACTERS,
            max_response_characters=settings.DEVELOP_AGENT_MAX_RESPONSE_CHARACTERS,
            cancel_event=turn.cancel_event,
            on_event=lambda event: _emit_agent_event(turn, event),
        )
    except (AgentCommandCancelled, AgentCommandTimeout) as error:
        state = turn.stop_reason or TurnTerminalState.timed_out
        safe_message = (
            "Agent Turn timed out."
            if state == TurnTerminalState.timed_out
            else "Agent Turn was interrupted."
        )
        logger.info("Agent exploration ended for chat %s: %s", chat.id, error)
        completed_at = get_datetime_utc()
        assistant_message = DevelopmentMessage(
            role="assistant",
            content=safe_message,
            activity=[{"text": safe_message}],
            duration_seconds=turn.elapsed_seconds(),
            chat_id=chat.id,
            created_at=completed_at,
        )
        chat.updated_at = completed_at
        session.add(assistant_message)
        session.add(chat)
        session.commit()
        session.refresh(assistant_message)
        develop_turn_manager.finish_turn(turn, state, safe_message)
        return assistant_message
    except AgentCommandError as error:
        logger.error("Agent exploration failed for chat %s: %s", chat.id, error)
        develop_turn_manager.finish_turn(
            turn, TurnTerminalState.failed, "Agent exploration failed"
        )
        detail = (
            f"Agent exploration failed: {error}"
            if settings.DEVELOP_ACCEPTANCE_MODE
            else "Agent exploration failed"
        )
        raise HTTPException(status_code=502, detail=detail)

    completed_at = get_datetime_utc()
    assistant_message = DevelopmentMessage(
        role="assistant",
        content=completion.response_text,
        activity=[part.model_dump() for part in completion.activity],
        duration_seconds=turn.elapsed_seconds(),
        chat_id=chat.id,
        created_at=completed_at,
    )
    chat.agent_session_id = completion.session_id
    chat.updated_at = completed_at
    session.add(assistant_message)
    session.add(chat)
    session.commit()
    session.refresh(assistant_message)
    after = snapshot_workspace(root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=chat.id)
    if relevant_turn_change(before, after):
        turn.emit("preview-change", "changed")
    develop_turn_manager.finish_turn(
        turn, TurnTerminalState.completed, "Agent Turn completed"
    )
    return assistant_message

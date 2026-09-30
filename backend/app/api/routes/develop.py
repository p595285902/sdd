import base64
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import and_, or_
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import (
    DevelopmentChat,
    DevelopmentChatCreate,
    DevelopmentChatPublic,
    DevelopmentChatsPublic,
    DevelopmentChatUpdate,
    DevelopmentMessage,
    DevelopmentMessageCreate,
    DevelopmentMessagePublic,
    DevelopmentMessagesPublic,
    DevelopmentWorkspacePublic,
    Message,
    get_datetime_utc,
)
from app.services.develop_agent import (
    AgentCommandCancelled,
    AgentCommandError,
    AgentCommandTimeout,
    execute_exploration,
)
from app.services.develop_turns import (
    ChatTurnActiveError,
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
)

router = APIRouter(prefix="/develop/chats", tags=["develop"])
logger = logging.getLogger(__name__)


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


def _repository_setup_available() -> bool:
    return bool(settings.DEMO_GITHUB_REPO and settings.DEMO_GITHUB_TOKEN)


def _workspace_status(chat: DevelopmentChat) -> DevelopmentWorkspacePublic:
    return DevelopmentWorkspacePublic(
        ready=chat.workspace_ready,
        setup_available=_repository_setup_available(),
    )


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


@router.post(
    "/{chat_id}/workspace/setup", response_model=DevelopmentWorkspacePublic
)
def setup_development_workspace(
    *, session: SessionDep, current_user: CurrentUser, chat_id: uuid.UUID
) -> Any:
    chat = _get_chat(session=session, current_user=current_user, chat_id=chat_id)
    repository_url = settings.DEMO_GITHUB_REPO
    repository_token = settings.DEMO_GITHUB_TOKEN
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
        cleanup_workspace(root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=chat.id)
    except (OSError, WorkspacePathError):
        raise HTTPException(
            status_code=500,
            detail="Development Workspace cleanup failed",
        )
    session.delete(chat)
    session.commit()
    return Message(message="Development Chat deleted")


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
        raise HTTPException(status_code=409, detail="Development Workspace is not ready")
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
    turn.emit("started")

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
        chat_id=chat.id,
        created_at=completed_at,
    )
    chat.agent_session_id = completion.session_id
    chat.updated_at = completed_at
    session.add(assistant_message)
    session.add(chat)
    session.commit()
    session.refresh(assistant_message)
    turn.emit("response", completion.response_text)
    develop_turn_manager.finish_turn(
        turn, TurnTerminalState.completed, "Agent Turn completed"
    )
    return assistant_message

import base64
import json
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
    DevelopmentMessagePublic,
    DevelopmentMessagesPublic,
    DevelopmentWorkspacePublic,
    Message,
    get_datetime_utc,
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
    chat.title = chat_in.title
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

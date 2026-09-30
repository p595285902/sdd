from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlmodel import Session, col, delete

from app.models import (
    DevelopmentChat,
    DevelopmentChatBase,
    DevelopmentChatPublic,
    DevelopmentMessage,
    DevelopmentMessageBase,
    DevelopmentMessageKind,
    DevelopmentProposalState,
    User,
)
from tests.utils.user import create_random_user


@pytest.mark.parametrize("title", ["", "x" * 256])
def test_development_chat_title_validation(title: str) -> None:
    with pytest.raises(ValidationError):
        DevelopmentChatBase.model_validate({"title": title})


@pytest.mark.parametrize(
    ("role", "content"),
    [
        ("system", "Valid content"),
        ("user", ""),
        ("assistant", "x" * 100_001),
    ],
)
def test_development_message_validation(role: str, content: str) -> None:
    with pytest.raises(ValidationError):
        DevelopmentMessageBase.model_validate({"role": role, "content": content})


@pytest.mark.parametrize(
    "proposal_state",
    [
        DevelopmentProposalState.undecided,
        DevelopmentProposalState.approved,
        DevelopmentProposalState.rejected,
    ],
)
def test_development_message_kind_and_proposal_state(
    proposal_state: DevelopmentProposalState,
) -> None:
    message = DevelopmentMessageBase(role="assistant", content="A proposal")
    proposal = DevelopmentMessageBase(
        role="assistant",
        content="A proposal",
        kind=DevelopmentMessageKind.proposal,
        proposal_state=proposal_state,
    )

    assert message.kind == DevelopmentMessageKind.message
    assert message.proposal_state is None
    assert proposal.kind == DevelopmentMessageKind.proposal
    assert proposal.proposal_state == proposal_state


def test_development_chat_relationships_and_timestamp_defaults(db: Session) -> None:
    user = create_random_user(db)
    chat = DevelopmentChat(title="New chat", owner_id=user.id, owner=user)
    db.add(chat)
    db.commit()
    db.refresh(chat)

    message = DevelopmentMessage(
        role="user", content="First message", chat_id=chat.id, chat=chat
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    assert chat.owner == user
    assert message.chat == chat
    assert message in chat.messages
    assert chat.created_at.utcoffset() == timedelta(0)
    assert chat.updated_at.utcoffset() == timedelta(0)
    assert message.created_at.utcoffset() == timedelta(0)
    assert chat.updated_at >= chat.created_at


def test_development_chat_workspace_is_not_ready_by_default() -> None:
    chat = DevelopmentChat(title="New chat", owner_id=User().id)

    assert chat.workspace_ready is False
    public_chat = DevelopmentChatPublic.model_validate(chat)
    assert public_chat.workspace_ready is False


def test_deleting_user_cascades_to_development_data(db: Session) -> None:
    user = create_random_user(db)
    chat = DevelopmentChat(title="Owned chat", owner_id=user.id)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    message = DevelopmentMessage(
        role="assistant", content="Owned message", chat_id=chat.id
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    chat_id = chat.id
    message_id = message.id

    db.exec(delete(User).where(col(User.id) == user.id))
    db.commit()
    db.expire_all()

    assert db.get(DevelopmentChat, chat_id) is None
    assert db.get(DevelopmentMessage, message_id) is None

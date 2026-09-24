import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import DevelopmentChat, DevelopmentMessage, User
from tests.utils.user import create_random_user, user_authentication_headers
from tests.utils.utils import random_lower_string

DEVELOP_CHATS_URL = f"{settings.API_V1_STR}/develop/chats"


def _superuser(db: Session) -> User:
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user
    return user


def test_unauthenticated_client_cannot_access_development_chats(
    client: TestClient,
) -> None:
    response = client.get(DEVELOP_CHATS_URL)

    assert response.status_code == 401


def test_first_message_creates_chat_and_message(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    response = client.post(
        DEVELOP_CHATS_URL,
        headers=superuser_token_headers,
        json={"content": "  Build the import flow  "},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Build the import flow"
    chat = db.get(DevelopmentChat, uuid.UUID(body["id"]))
    assert chat
    message = db.exec(
        select(DevelopmentMessage).where(DevelopmentMessage.chat_id == chat.id)
    ).one()
    assert message.content == "Build the import flow"
    assert message.role == "user"
    assert chat.owner_id == _superuser(db).id


@pytest.mark.parametrize("content", ["", "   ", "x" * 100_001])
def test_first_message_validates_content(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    content: str,
) -> None:
    response = client.post(
        DEVELOP_CHATS_URL,
        headers=superuser_token_headers,
        json={"content": content},
    )

    assert response.status_code == 422


def test_missing_and_foreign_chats_have_same_response(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    other_user = create_random_user(db)
    foreign_chat = DevelopmentChat(title="Private", owner_id=other_user.id)
    db.add(foreign_chat)
    db.commit()
    db.refresh(foreign_chat)

    missing_response = client.get(
        f"{DEVELOP_CHATS_URL}/{uuid.uuid4()}", headers=superuser_token_headers
    )
    foreign_response = client.get(
        f"{DEVELOP_CHATS_URL}/{foreign_chat.id}", headers=superuser_token_headers
    )

    assert missing_response.status_code == 404
    assert foreign_response.status_code == 404
    assert foreign_response.json() == missing_response.json()


def test_rename_does_not_change_activity_order(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    create_response = client.post(
        DEVELOP_CHATS_URL,
        headers=superuser_token_headers,
        json={"content": "Original title"},
    )
    original = create_response.json()

    rename_response = client.patch(
        f"{DEVELOP_CHATS_URL}/{original['id']}",
        headers=superuser_token_headers,
        json={"title": "  Renamed chat  "},
    )

    assert rename_response.status_code == 200
    renamed = rename_response.json()
    assert renamed["title"] == "Renamed chat"
    assert renamed["updated_at"] == original["updated_at"]


def test_recent_chats_use_stable_bounded_activity_order(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DEVELOP_HISTORY_LIMIT", 2)
    owner = _superuser(db)
    activity_time = datetime(2100, 1, 1, tzinfo=UTC)
    chats = [
        DevelopmentChat(
            id=uuid.UUID(int=value),
            title=f"Chat {value}",
            owner_id=owner.id,
            created_at=activity_time,
            updated_at=activity_time,
        )
        for value in (101, 102, 103)
    ]
    db.add_all(chats)
    db.commit()

    response = client.get(DEVELOP_CHATS_URL, headers=superuser_token_headers)

    assert response.status_code == 200
    assert [entry["id"] for entry in response.json()["data"]] == [
        str(chats[2].id),
        str(chats[1].id),
    ]


def test_messages_are_cursor_paginated_in_conversation_order(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DEVELOP_MESSAGE_PAGE_SIZE", 2)
    owner = _superuser(db)
    chat = DevelopmentChat(title="Paged chat", owner_id=owner.id)
    db.add(chat)
    db.commit()
    messages = [
        DevelopmentMessage(
            id=uuid.UUID(int=value),
            role="user",
            content=f"Message {value}",
            chat_id=chat.id,
            created_at=datetime(2099, 1, 1, tzinfo=UTC) + timedelta(seconds=value),
        )
        for value in range(1, 5)
    ]
    db.add_all(messages)
    db.commit()

    latest_response = client.get(
        f"{DEVELOP_CHATS_URL}/{chat.id}/messages",
        headers=superuser_token_headers,
    )
    latest = latest_response.json()
    older_response = client.get(
        f"{DEVELOP_CHATS_URL}/{chat.id}/messages",
        headers=superuser_token_headers,
        params={"before": latest["next_cursor"]},
    )

    assert latest_response.status_code == 200
    assert [entry["content"] for entry in latest["data"]] == [
        "Message 3",
        "Message 4",
    ]
    assert latest["has_more"] is True
    assert [entry["content"] for entry in older_response.json()["data"]] == [
        "Message 1",
        "Message 2",
    ]
    assert older_response.json()["has_more"] is False


@pytest.mark.parametrize(
    "params",
    [
        {"before": "not-a-cursor"},
        {"before": "not-a-cursor", "after": "not-a-cursor"},
    ],
)
def test_message_cursor_validation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    params: dict[str, str],
) -> None:
    owner = _superuser(db)
    chat = DevelopmentChat(
        title=f"Cursor test {random_lower_string()}", owner_id=owner.id
    )
    db.add(chat)
    db.commit()

    response = client.get(
        f"{DEVELOP_CHATS_URL}/{chat.id}/messages",
        headers=superuser_token_headers,
        params=params,
    )

    assert response.status_code == 422
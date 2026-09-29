import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import HttpUrl, SecretStr
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import DevelopmentChat, DevelopmentMessage, User
from app.services.develop_agent import (
    AgentActivityPart,
    AgentCommandError,
    AgentCompletion,
)
from tests.utils.user import create_random_user
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


def test_setup_demo_repository_marks_owned_chat_workspace_ready(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _superuser(db)
    chat = DevelopmentChat(title="Workspace setup", owner_id=owner.id)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    monkeypatch.setattr(
        settings,
        "DEMO_GITHUB_REPO",
        HttpUrl("https://example.com/demo/repository.git"),
    )
    monkeypatch.setattr(
        settings, "DEMO_GITHUB_TOKEN", SecretStr("top-secret-token")
    )
    monkeypatch.setattr(settings, "DEVELOP_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(settings, "DEVELOP_FAKE_SETUP_RUNNER", True)

    response = client.post(
        f"{DEVELOP_CHATS_URL}/{chat.id}/workspace/setup",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"ready": True, "setup_available": True}
    db.refresh(chat)
    assert chat.workspace_ready is True
    assert (tmp_path / str(chat.id) / ".opencode-initialized").exists()
    assert (tmp_path / str(chat.id) / ".openspec-initialized").exists()

    readiness_response = client.get(
        f"{DEVELOP_CHATS_URL}/{chat.id}/workspace",
        headers=superuser_token_headers,
    )
    assert readiness_response.status_code == 200
    assert readiness_response.json() == {"ready": True, "setup_available": True}


def test_setup_demo_repository_returns_safe_error_when_configuration_is_incomplete(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _superuser(db)
    chat = DevelopmentChat(title="Missing setup configuration", owner_id=owner.id)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    token = "top-secret-token"
    monkeypatch.setattr(settings, "DEMO_GITHUB_REPO", None)
    monkeypatch.setattr(settings, "DEMO_GITHUB_TOKEN", SecretStr(token))

    response = client.post(
        f"{DEVELOP_CHATS_URL}/{chat.id}/workspace/setup",
        headers=superuser_token_headers,
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Demo repository setup is not configured"}
    assert token not in response.text


def test_foreign_chat_workspace_status_is_not_disclosed(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    other_user = create_random_user(db)
    foreign_chat = DevelopmentChat(title="Private workspace", owner_id=other_user.id)
    db.add(foreign_chat)
    db.commit()
    db.refresh(foreign_chat)

    response = client.get(
        f"{DEVELOP_CHATS_URL}/{foreign_chat.id}/workspace",
        headers=superuser_token_headers,
    )

    assert response.status_code == 404


def test_development_chat_deletion_requires_confirmation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    owner = _superuser(db)
    chat = DevelopmentChat(title="Keep this chat", owner_id=owner.id)
    db.add(chat)
    db.commit()
    db.refresh(chat)

    response = client.delete(
        f"{DEVELOP_CHATS_URL}/{chat.id}", headers=superuser_token_headers
    )

    assert response.status_code == 400
    assert db.get(DevelopmentChat, chat.id) is not None


def test_confirmed_deletion_removes_workspace_chat_and_messages(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _superuser(db)
    chat = DevelopmentChat(
        title="Delete this chat", owner_id=owner.id, workspace_ready=True
    )
    message = DevelopmentMessage(role="user", content="Delete me", chat_id=chat.id)
    db.add(chat)
    db.add(message)
    db.commit()
    db.refresh(chat)
    db.refresh(message)
    chat_id = chat.id
    message_id = message.id
    workspace = tmp_path / str(chat.id)
    workspace.mkdir()
    monkeypatch.setattr(settings, "DEVELOP_WORKSPACE_ROOT", tmp_path)

    response = client.delete(
        f"{DEVELOP_CHATS_URL}/{chat.id}",
        headers=superuser_token_headers,
        params={"confirm": True},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Development Chat deleted"}
    assert not workspace.exists()
    db.expunge_all()
    assert db.get(DevelopmentChat, chat_id) is None
    assert db.get(DevelopmentMessage, message_id) is None


def test_cleanup_failure_keeps_development_chat_and_messages(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _superuser(db)
    chat = DevelopmentChat(
        title="Retry deletion", owner_id=owner.id, workspace_ready=True
    )
    message = DevelopmentMessage(role="user", content="Keep me", chat_id=chat.id)
    db.add(chat)
    db.add(message)
    db.commit()
    db.refresh(chat)
    db.refresh(message)

    def fail_cleanup(**_kwargs: object) -> None:
        raise OSError("secret filesystem detail")

    monkeypatch.setattr(
        "app.api.routes.develop.cleanup_workspace", fail_cleanup, raising=False
    )

    response = client.delete(
        f"{DEVELOP_CHATS_URL}/{chat.id}",
        headers=superuser_token_headers,
        params={"confirm": True},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Development Workspace cleanup failed"}
    assert "secret filesystem detail" not in response.text
    assert db.get(DevelopmentChat, chat.id) is not None
    assert db.get(DevelopmentMessage, message.id) is not None


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


def test_explore_persists_user_before_agent_and_completion_atomically(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _superuser(db)
    chat = DevelopmentChat(
        title="Explore",
        owner_id=owner.id,
        workspace_ready=True,
        agent_session_id="ses_previous",
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)
    (tmp_path / str(chat.id)).mkdir()
    monkeypatch.setattr(settings, "DEVELOP_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("provider-secret"))

    def fake_execute_exploration(**kwargs: object) -> AgentCompletion:
        db.expire_all()
        messages = list(
            db.exec(
                select(DevelopmentMessage).where(
                    DevelopmentMessage.chat_id == chat.id
                )
            ).all()
        )
        assert [(message.role, message.content) for message in messages] == [
            ("user", "Inspect the repository")
        ]
        assert kwargs["session_id"] == "ses_previous"
        return AgentCompletion(
            response_text="Repository explored",
            activity=(AgentActivityPart(text="Reading README.md"),),
            session_id="ses_next",
        )

    monkeypatch.setattr(
        "app.api.routes.develop.execute_exploration", fake_execute_exploration
    )

    response = client.post(
        f"{DEVELOP_CHATS_URL}/{chat.id}/messages/explore",
        headers=superuser_token_headers,
        json={"content": "Inspect the repository"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "Repository explored"
    assert response.json()["activity"] == [{"text": "Reading README.md"}]
    db.expire_all()
    persisted_chat = db.get(DevelopmentChat, chat.id)
    assert persisted_chat
    assert persisted_chat.agent_session_id == "ses_next"


def test_explore_failure_keeps_user_message_without_completion(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _superuser(db)
    chat = DevelopmentChat(title="Failure", owner_id=owner.id, workspace_ready=True)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    (tmp_path / str(chat.id)).mkdir()
    monkeypatch.setattr(settings, "DEVELOP_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("provider-secret"))

    def fail_exploration(**_kwargs: object) -> AgentCompletion:
        raise AgentCommandError("[REDACTED] provider failure")

    monkeypatch.setattr(
        "app.api.routes.develop.execute_exploration", fail_exploration
    )

    response = client.post(
        f"{DEVELOP_CHATS_URL}/{chat.id}/messages/explore",
        headers=superuser_token_headers,
        json={"content": "Try this"},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Agent exploration failed"}
    db.expire_all()
    messages = list(
        db.exec(
            select(DevelopmentMessage).where(DevelopmentMessage.chat_id == chat.id)
        ).all()
    )
    assert [(message.role, message.content) for message in messages] == [
        ("user", "Try this")
    ]
    persisted_chat = db.get(DevelopmentChat, chat.id)
    assert persisted_chat
    assert persisted_chat.agent_session_id is None

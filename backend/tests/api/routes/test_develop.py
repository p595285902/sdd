import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import HttpUrl, SecretStr
from sqlmodel import Session, select

from app import crud
from app.api.routes.develop import _serialize_sse_event
from app.core.config import settings
from app.models import DevelopmentChat, DevelopmentMessage, PresenceMode, User
from app.services.develop_agent import (
    AgentActivityPart,
    AgentCommandCancelled,
    AgentCommandError,
    AgentCompletion,
)
from app.services.develop_turns import (
    TurnEvent,
    TurnTerminalState,
    develop_turn_manager,
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


def test_presence_mode_defaults_and_persists_for_later_turns(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    create_response = client.post(
        DEVELOP_CHATS_URL,
        headers=superuser_token_headers,
        json={"content": "Presence mode"},
    )
    chat_id = uuid.UUID(create_response.json()["id"])

    assert create_response.json()["presence_mode"] == "stop_when_i_leave"

    update_response = client.patch(
        f"{DEVELOP_CHATS_URL}/{chat_id}",
        headers=superuser_token_headers,
        json={"presence_mode": "continue_in_background"},
    )

    assert update_response.status_code == 200
    assert update_response.json()["presence_mode"] == "continue_in_background"
    db.expire_all()
    chat = db.get(DevelopmentChat, chat_id)
    assert chat
    assert chat.presence_mode == PresenceMode.continue_in_background


def test_user_concurrent_agent_turn_limit_defaults_to_two(db: Session) -> None:
    user = create_random_user(db)

    assert user.concurrent_agent_turn_limit == 2


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
    assert develop_turn_manager.active_turn(chat.id) is None
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


def test_concurrent_turn_for_one_chat_is_rejected_and_explicit_stop_completes(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _superuser(db)
    chat = DevelopmentChat(title="Concurrent", owner_id=owner.id, workspace_ready=True)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("provider-secret"))
    started = threading.Event()

    def block_until_cancelled(**kwargs: object) -> AgentCompletion:
        cancel_event = kwargs["cancel_event"]
        assert isinstance(cancel_event, threading.Event)
        started.set()
        assert cancel_event.wait(2)
        raise AgentCommandCancelled("cancelled")

    monkeypatch.setattr(
        "app.api.routes.develop.execute_exploration", block_until_cancelled
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            client.post,
            f"{DEVELOP_CHATS_URL}/{chat.id}/messages/explore",
            headers=superuser_token_headers,
            json={"content": "First"},
        )
        assert started.wait(1)
        second = client.post(
            f"{DEVELOP_CHATS_URL}/{chat.id}/messages/explore",
            headers=superuser_token_headers,
            json={"content": "Second"},
        )
        stop = client.delete(
            f"{DEVELOP_CHATS_URL}/{chat.id}/turns/current",
            headers=superuser_token_headers,
        )
        first_response = first.result(timeout=2)

    assert second.status_code == 409
    assert "already has an active" in second.json()["detail"]
    assert stop.status_code == 200
    assert first_response.status_code == 200
    assert first_response.json()["content"] == "Agent Turn was interrupted."
    assert develop_turn_manager.active_turn(chat.id) is None


def test_agent_turn_timeout_records_safe_error(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _superuser(db)
    chat = DevelopmentChat(title="Timeout", owner_id=owner.id, workspace_ready=True)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("provider-secret"))
    monkeypatch.setattr(settings, "DEVELOP_TURN_TIMEOUT_SECONDS", 0.01)

    def wait_for_timeout(**kwargs: object) -> AgentCompletion:
        cancel_event = kwargs["cancel_event"]
        assert isinstance(cancel_event, threading.Event)
        assert cancel_event.wait(1)
        raise AgentCommandCancelled("cancelled")

    monkeypatch.setattr(
        "app.api.routes.develop.execute_exploration", wait_for_timeout
    )

    response = client.post(
        f"{DEVELOP_CHATS_URL}/{chat.id}/messages/explore",
        headers=superuser_token_headers,
        json={"content": "Wait forever"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "Agent Turn timed out."
    assert develop_turn_manager.active_turn(chat.id) is None


def test_user_turn_capacity_is_enforced_across_chats(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _superuser(db)
    chats = [
        DevelopmentChat(
            title=f"Capacity {index}", owner_id=owner.id, workspace_ready=True
        )
        for index in range(3)
    ]
    db.add_all(chats)
    db.commit()
    for chat in chats:
        db.refresh(chat)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("provider-secret"))
    started = threading.Barrier(3)

    def block_until_cancelled(**kwargs: object) -> AgentCompletion:
        cancel_event = kwargs["cancel_event"]
        assert isinstance(cancel_event, threading.Event)
        started.wait()
        assert cancel_event.wait(2)
        raise AgentCommandCancelled("cancelled")

    monkeypatch.setattr(
        "app.api.routes.develop.execute_exploration", block_until_cancelled
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        active = [
            executor.submit(
                client.post,
                f"{DEVELOP_CHATS_URL}/{chat.id}/messages/explore",
                headers=superuser_token_headers,
                json={"content": f"Active {index}"},
            )
            for index, chat in enumerate(chats[:2])
        ]
        started.wait()
        rejected = client.post(
            f"{DEVELOP_CHATS_URL}/{chats[2].id}/messages/explore",
            headers=superuser_token_headers,
            json={"content": "Excess"},
        )
        for chat in chats[:2]:
            response = client.delete(
                f"{DEVELOP_CHATS_URL}/{chat.id}/turns/current",
                headers=superuser_token_headers,
            )
            assert response.status_code == 200
        for future in active:
            assert future.result(timeout=2).status_code == 200

    assert rejected.status_code == 429
    assert "limit has been reached" in rejected.json()["detail"]


def test_confirmed_deletion_waits_for_active_turn_before_workspace_cleanup(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _superuser(db)
    chat = DevelopmentChat(title="Delete active", owner_id=owner.id)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    turn = develop_turn_manager.start_turn(
        chat_id=chat.id,
        user_id=owner.id,
        user_limit=owner.concurrent_agent_turn_limit,
        presence_mode=chat.presence_mode,
        replay_limit=2,
        timeout_seconds=10,
    )

    def finish_after_stop() -> None:
        assert turn.cancel_event.wait(1)
        develop_turn_manager.finish_turn(turn, TurnTerminalState.stopped)

    worker = threading.Thread(target=finish_after_stop)
    worker.start()

    def assert_turn_stopped_before_cleanup(**_kwargs: object) -> None:
        assert develop_turn_manager.active_turn(chat.id) is None

    monkeypatch.setattr(
        "app.api.routes.develop.cleanup_workspace",
        assert_turn_stopped_before_cleanup,
    )

    response = client.delete(
        f"{DEVELOP_CHATS_URL}/{chat.id}",
        headers=superuser_token_headers,
        params={"confirm": True},
    )
    worker.join(timeout=1)

    assert response.status_code == 200
    assert not worker.is_alive()


@pytest.mark.parametrize(
    ("source_kind", "wire_kind"),
    [
        ("session", "session"),
        ("status", "status"),
        ("text", "text"),
        ("error", "error"),
        ("idle", "idle"),
        ("terminal", "done"),
    ],
)
def test_turn_events_have_normalized_sse_serialization(
    source_kind: str, wire_kind: str
) -> None:
    serialized = _serialize_sse_event(TurnEvent(7, source_kind, "value"))

    assert serialized == (
        f'id: 7\nevent: {wire_kind}\n'
        f'data: {{"sequence":7,"kind":"{wire_kind}","data":"value"}}\n\n'
    )


def test_reattachment_stream_requires_bearer_authentication(
    client: TestClient,
) -> None:
    response = client.get(f"{DEVELOP_CHATS_URL}/{uuid.uuid4()}/turns/current/stream")

    assert response.status_code == 401


def test_reattachment_stream_hides_missing_and_foreign_chats(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    other_user = create_random_user(db)
    foreign_chat = DevelopmentChat(title="Private stream", owner_id=other_user.id)
    db.add(foreign_chat)
    db.commit()

    missing = client.get(
        f"{DEVELOP_CHATS_URL}/{uuid.uuid4()}/turns/current/stream",
        headers=superuser_token_headers,
    )
    foreign = client.get(
        f"{DEVELOP_CHATS_URL}/{foreign_chat.id}/turns/current/stream",
        headers=superuser_token_headers,
    )

    assert missing.status_code == 404
    assert foreign.status_code == 404
    assert foreign.json() == missing.json()


def test_reattachment_stream_replays_then_sends_live_events_and_cleans_up(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _superuser(db)
    chat = DevelopmentChat(title="Streaming", owner_id=owner.id)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    turn = develop_turn_manager.start_turn(
        chat_id=chat.id,
        user_id=owner.id,
        user_limit=owner.concurrent_agent_turn_limit,
        presence_mode=PresenceMode.continue_in_background,
        replay_limit=10,
        timeout_seconds=10,
    )
    turn.emit("status", "buffered")
    monkeypatch.setattr(settings, "DEVELOP_SSE_HEARTBEAT_SECONDS", 0.01)

    def finish_turn() -> None:
        time.sleep(0.03)
        turn.emit("text", "live")
        develop_turn_manager.finish_turn(turn, TurnTerminalState.completed, "complete")

    worker = threading.Thread(target=finish_turn)
    worker.start()
    response = client.get(
        f"{DEVELOP_CHATS_URL}/{chat.id}/turns/current/stream",
        headers=superuser_token_headers,
    )
    worker.join(timeout=1)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.text.index('"data":"buffered"') < response.text.index(
        '"data":"live"'
    )
    assert ": heartbeat\n\n" in response.text
    assert "event: done" in response.text
    assert turn.subscriber_count == 0


def test_start_stream_creates_and_completes_managed_turn(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _superuser(db)
    chat = DevelopmentChat(title="Start stream", owner_id=owner.id, workspace_ready=True)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("provider-secret"))

    def fake_streamed_exploration(**kwargs: object) -> None:
        turn = kwargs["turn"]
        assert hasattr(turn, "emit")
        turn.emit("text", "streamed")
        develop_turn_manager.finish_turn(
            turn, TurnTerminalState.completed, "complete"
        )

    monkeypatch.setattr(
        "app.api.routes.develop._run_streamed_exploration",
        fake_streamed_exploration,
    )

    response = client.post(
        f"{DEVELOP_CHATS_URL}/{chat.id}/messages/explore/stream",
        headers=superuser_token_headers,
        json={"content": "Inspect live"},
    )

    assert response.status_code == 200
    assert [
        event
        for event in ("event: session", "event: status", "event: text", "event: done")
        if event in response.text
    ] == ["event: session", "event: status", "event: text", "event: done"]
    assert develop_turn_manager.active_turn(chat.id) is None

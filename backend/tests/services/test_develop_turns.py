import threading
import time
import uuid

import pytest

from app.models import PresenceMode
from app.services.develop_turns import (
    ChatTurnActiveError,
    DevelopTurnManager,
    TurnSession,
    TurnTerminalState,
    UserTurnLimitError,
)


def _start(
    manager: DevelopTurnManager,
    *,
    chat_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    user_limit: int = 2,
    presence_mode: PresenceMode = PresenceMode.stop_when_i_leave,
    timeout_seconds: float = 10,
) -> TurnSession:
    return manager.start_turn(
        chat_id=chat_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        user_limit=user_limit,
        presence_mode=presence_mode,
        replay_limit=3,
        timeout_seconds=timeout_seconds,
    )


def test_turn_session_bounds_replay_and_tracks_terminal_state() -> None:
    session = TurnSession(
        chat_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        presence_mode=PresenceMode.stop_when_i_leave,
        replay_limit=2,
    )

    session.emit("activity", "one")
    session.emit("activity", "two")
    session.emit("activity", "three")

    assert [event.data for event in session.replay()] == ["two", "three"]
    assert session.complete(TurnTerminalState.completed)
    assert not session.complete(TurnTerminalState.failed)
    assert session.wait_terminal(0)


def test_turn_session_tracks_subscribers_and_withdraws_grace_stop() -> None:
    session = TurnSession(
        chat_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        presence_mode=PresenceMode.stop_when_i_leave,
        replay_limit=2,
    )
    session.attach("owner")
    session.detach("owner", grace_seconds=0.05)
    session.attach("owner")

    time.sleep(0.1)

    assert not session.cancel_event.is_set()
    assert session.subscriber_count == 1


def test_background_session_ignores_subscriber_loss_but_times_out() -> None:
    session = TurnSession(
        chat_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        presence_mode=PresenceMode.continue_in_background,
        replay_limit=2,
    )
    session.attach("owner")
    session.detach("owner", grace_seconds=0)
    session.start_timeout(0.01)

    assert session.cancel_event.wait(0.5)
    assert session.stop_reason == TurnTerminalState.timed_out


def test_manager_rejects_concurrent_turn_for_same_chat() -> None:
    manager = DevelopTurnManager()
    chat_id = uuid.uuid4()
    _start(manager, chat_id=chat_id)

    with pytest.raises(ChatTurnActiveError, match="already has an active"):
        _start(manager, chat_id=chat_id)


def test_manager_reserves_user_slots_atomically_and_releases_once() -> None:
    manager = DevelopTurnManager()
    user_id = uuid.uuid4()
    barrier = threading.Barrier(3)
    sessions: list[TurnSession] = []
    errors: list[Exception] = []

    def start() -> None:
        barrier.wait()
        try:
            sessions.append(_start(manager, user_id=user_id, user_limit=1))
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=start) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert len(sessions) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], UserTurnLimitError)
    assert "limit has been reached" in str(errors[0])
    assert manager.finish_turn(sessions[0], TurnTerminalState.completed)
    assert not manager.finish_turn(sessions[0], TurnTerminalState.completed)
    replacement = _start(manager, user_id=user_id, user_limit=1)
    assert replacement is manager.active_turn(replacement.chat_id)

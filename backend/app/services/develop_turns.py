import threading
import uuid
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic

from app.models import PresenceMode


class TurnAdmissionError(RuntimeError):
    pass


class ChatTurnActiveError(TurnAdmissionError):
    pass


class UserTurnLimitError(TurnAdmissionError):
    pass


class TurnTerminalState(StrEnum):
    completed = "completed"
    stopped = "stopped"
    timed_out = "timed_out"
    failed = "failed"


@dataclass(frozen=True)
class TurnEvent:
    sequence: int
    kind: str
    data: str


class TurnSession:
    def __init__(
        self,
        *,
        chat_id: uuid.UUID,
        user_id: uuid.UUID,
        presence_mode: PresenceMode,
        replay_limit: int,
    ) -> None:
        if replay_limit < 1:
            raise ValueError("Turn replay limit must be positive")
        self.chat_id = chat_id
        self.user_id = user_id
        self.presence_mode = presence_mode
        self.cancel_event = threading.Event()
        self._condition = threading.Condition(threading.RLock())
        self._events: deque[TurnEvent] = deque(maxlen=replay_limit)
        self._subscribers: set[str] = set()
        self._next_sequence = 1
        self._terminal_state: TurnTerminalState | None = None
        self._stop_reason: TurnTerminalState | None = None
        self._grace_timer: threading.Timer | None = None
        self._timeout_timer: threading.Timer | None = None

    @property
    def terminal_state(self) -> TurnTerminalState | None:
        with self._condition:
            return self._terminal_state

    @property
    def stop_reason(self) -> TurnTerminalState | None:
        with self._condition:
            return self._stop_reason

    @property
    def subscriber_count(self) -> int:
        with self._condition:
            return len(self._subscribers)

    def emit(self, kind: str, data: str = "") -> TurnEvent:
        with self._condition:
            event = TurnEvent(self._next_sequence, kind, data)
            self._next_sequence += 1
            self._events.append(event)
            self._condition.notify_all()
            return event

    def replay(self, *, after_sequence: int = 0) -> tuple[TurnEvent, ...]:
        with self._condition:
            return tuple(
                event for event in self._events if event.sequence > after_sequence
            )

    def attach(self, subscriber_id: str) -> tuple[TurnEvent, ...]:
        with self._condition:
            self._subscribers.add(subscriber_id)
            self._cancel_grace_timer_locked()
            return tuple(self._events)

    def detach(self, subscriber_id: str, *, grace_seconds: float) -> None:
        with self._condition:
            self._subscribers.discard(subscriber_id)
            if (
                self._subscribers
                or self._terminal_state is not None
                or self.presence_mode == PresenceMode.continue_in_background
            ):
                return
            self._cancel_grace_timer_locked()
            self._grace_timer = threading.Timer(
                grace_seconds,
                self.request_stop,
                kwargs={"reason": TurnTerminalState.stopped},
            )
            self._grace_timer.daemon = True
            self._grace_timer.start()

    def start_timeout(self, timeout_seconds: float) -> None:
        with self._condition:
            if self._terminal_state is not None:
                return
            self._timeout_timer = threading.Timer(
                timeout_seconds,
                self.request_stop,
                kwargs={"reason": TurnTerminalState.timed_out},
            )
            self._timeout_timer.daemon = True
            self._timeout_timer.start()

    def request_stop(self, *, reason: TurnTerminalState) -> bool:
        with self._condition:
            if self._terminal_state is not None or self._stop_reason is not None:
                return False
            self._stop_reason = reason
            self.cancel_event.set()
            self._condition.notify_all()
            return True

    def complete(self, state: TurnTerminalState, data: str = "") -> bool:
        with self._condition:
            if self._terminal_state is not None:
                return False
            self._terminal_state = state
            self._cancel_grace_timer_locked()
            if self._timeout_timer is not None:
                self._timeout_timer.cancel()
                self._timeout_timer = None
            self.emit("terminal", data or state.value)
            self._condition.notify_all()
            return True

    def wait_terminal(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else monotonic() + timeout
        with self._condition:
            while self._terminal_state is None:
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def _cancel_grace_timer_locked(self) -> None:
        if self._grace_timer is not None:
            self._grace_timer.cancel()
            self._grace_timer = None


class DevelopTurnManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active_by_chat: dict[uuid.UUID, TurnSession] = {}
        self._active_by_user: dict[uuid.UUID, int] = {}

    def start_turn(
        self,
        *,
        chat_id: uuid.UUID,
        user_id: uuid.UUID,
        user_limit: int,
        presence_mode: PresenceMode,
        replay_limit: int,
        timeout_seconds: float,
    ) -> TurnSession:
        if user_limit < 1:
            raise ValueError("User turn limit must be positive")
        with self._lock:
            if chat_id in self._active_by_chat:
                raise ChatTurnActiveError(
                    "This Development Chat already has an active Agent Turn"
                )
            if self._active_by_user.get(user_id, 0) >= user_limit:
                raise UserTurnLimitError(
                    "The user's concurrent Agent Turn limit has been reached"
                )
            session = TurnSession(
                chat_id=chat_id,
                user_id=user_id,
                presence_mode=presence_mode,
                replay_limit=replay_limit,
            )
            self._active_by_chat[chat_id] = session
            self._active_by_user[user_id] = self._active_by_user.get(user_id, 0) + 1
            session.start_timeout(timeout_seconds)
            return session

    def active_turn(self, chat_id: uuid.UUID) -> TurnSession | None:
        with self._lock:
            return self._active_by_chat.get(chat_id)

    def finish_turn(
        self,
        session: TurnSession,
        state: TurnTerminalState,
        data: str = "",
    ) -> bool:
        with self._lock:
            if self._active_by_chat.get(session.chat_id) is not session:
                return False
            session.complete(state, data)
            del self._active_by_chat[session.chat_id]
            active_count = self._active_by_user.get(session.user_id, 0)
            if active_count <= 1:
                self._active_by_user.pop(session.user_id, None)
            else:
                self._active_by_user[session.user_id] = active_count - 1
            return True

    def request_stop(
        self,
        chat_id: uuid.UUID,
        *,
        reason: TurnTerminalState = TurnTerminalState.stopped,
    ) -> TurnSession | None:
        session = self.active_turn(chat_id)
        if session is not None:
            session.request_stop(reason=reason)
        return session

    def stop_and_wait(self, chat_id: uuid.UUID, *, timeout: float) -> bool:
        session = self.request_stop(chat_id)
        return session is None or session.wait_terminal(timeout)

    def attach(
        self, chat_id: uuid.UUID, subscriber_id: str
    ) -> tuple[TurnEvent, ...] | None:
        session = self.active_turn(chat_id)
        return None if session is None else session.attach(subscriber_id)

    def detach(
        self, chat_id: uuid.UUID, subscriber_id: str, *, grace_seconds: float
    ) -> bool:
        session = self.active_turn(chat_id)
        if session is None:
            return False
        session.detach(subscriber_id, grace_seconds=grace_seconds)
        return True


develop_turn_manager = DevelopTurnManager()

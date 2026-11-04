"""Run-local admission and completion barrier; never enabled in production."""
import asyncio
import contextvars
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

import anyio
from anyio.to_thread import run_sync
from starlette.responses import JSONResponse, StreamingResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class AdmissionClosed(RuntimeError):
    pass


@dataclass(eq=False)
class Work:
    generation: int
    kind: str
    cancelled: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    done: bool = False
    cancel_callback: Callable[[], None] | None = None


current_work: contextvars.ContextVar[Work | None] = contextvars.ContextVar("acceptance_work", default=None)


class WorkBarrier:
    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self.generation = 0
        self.open = True
        self.activity = 0
        self._work: set[Work] = set()

    def admit(self, kind: str, *, parent: Work | None = None) -> Work:
        with self._condition:
            # Already admitted requests may hand ownership to a child while closing.
            if not self.open and (parent is None or parent not in self._work):
                raise AdmissionClosed("Acceptance boundary is closed")
            generation = parent.generation if parent else self.generation
            if generation != self.generation:
                raise AdmissionClosed("Stale acceptance generation")
            work = Work(generation, kind)
            if not self.open:
                work.cancelled.set()
            self._work.add(work)
            self.activity += 1
            self._reap_locked()
            return work

    def finish(self, work: Work) -> None:
        with self._condition:
            work.done = True
            if work.thread is None:
                self._work.discard(work)
            self._condition.notify_all()

    def _reap_locked(self) -> None:
        self._work = {work for work in self._work if not (
            work.done and (work.thread is None or not work.thread.is_alive())
        )}

    def counts(self) -> dict[str, int]:
        with self._condition:
            self._reap_locked()
            return dict(Counter(work.kind for work in self._work))

    def close(self) -> None:
        with self._condition:
            self.open = False
            for work in self._work:
                work.cancelled.set()
                if work.cancel_callback:
                    work.cancel_callback()
            self._condition.notify_all()

    def drain(self, deadline: float) -> None:
        while True:
            with self._condition:
                self._reap_locked()
                if not self._work:
                    return
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("Generation work did not complete")
                threads = [work.thread for work in self._work if work.thread is not None and work.thread.ident is not None]
                if not threads:
                    self._condition.wait(min(remaining, 0.05))
                    continue
            for thread in threads:
                thread.join(timeout=min(max(0, deadline - monotonic()), 0.05))

    def reopen(self, generation: int) -> None:
        with self._condition:
            self._reap_locked()
            if self._work:
                raise RuntimeError("Cannot reopen before actual completion")
            self.generation = generation
            self.open = True

    def start_thread(self, target: Callable[..., Any], kwargs: dict[str, Any]) -> threading.Thread:
        parent = current_work.get()
        work = self.admit("turn-completion", parent=parent)
        context = contextvars.copy_context()

        def execute() -> None:
            token = current_work.set(work)
            try:
                target(**kwargs)
            finally:
                current_work.reset(token)
                self.finish(work)

        thread = threading.Thread(target=lambda: context.run(execute), daemon=True)
        work.thread = thread
        try:
            thread.start()
        except BaseException:
            work.thread = None
            self.finish(work)
            raise
        return thread


class AcceptanceAdmissionMiddleware:
    """Pure ASGI: response streams, background tasks and dependency finally blocks finish first."""
    def __init__(self, app: ASGIApp, *, barrier: WorkBarrier, prefix: str) -> None:
        self.app, self.barrier, self.prefix = app, barrier, prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] not in ("http", "websocket") or path.startswith(self.prefix + "/testing/acceptance/") or path == self.prefix + "/utils/health-check/":
            await self.app(scope, receive, send)
            return
        try:
            work = self.barrier.admit("provider" if "/testing/llm/v1/" in path else scope["type"])
        except AdmissionClosed:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1013})
            else:
                await JSONResponse({"detail": "Acceptance boundary is closed"}, status_code=503)(scope, receive, send)
            return
        token = current_work.set(work)
        try:
            # WebSockets must close their child forwarding tasks and session before drain.
            with anyio.CancelScope() as cancel_scope:
                if scope["type"] == "websocket":
                    loop = asyncio.get_running_loop()
                    def cancel_socket() -> None:
                        loop.call_soon_threadsafe(cancel_scope.cancel)

                    work.cancel_callback = cancel_socket
                    if work.cancelled.is_set():
                        cancel_scope.cancel()
                await self.app(scope, receive, send)
        finally:
            current_work.reset(token)
            self.barrier.finish(work)


class CompletionStreamingResponse(StreamingResponse):
    """Starlette's thread iterator does not close its underlying generator on disconnect."""
    def __init__(self, content: Any, **kwargs: Any) -> None:
        self._source = content
        super().__init__(content, **kwargs)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            close = getattr(self._source, "close", None)
            aclose = getattr(self._source, "aclose", None)
            with anyio.CancelScope(shield=True):
                if close:
                    await run_sync(close, abandon_on_cancel=False)
                elif aclose:
                    await aclose()

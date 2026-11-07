import asyncio
import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.services.develop_workspace import workspace_path

SESSION_ID_PATTERN = re.compile(r"^ses_[A-Za-z0-9_-]+$")
REDACTED = "[REDACTED]"
URL_CREDENTIAL_PATTERN = re.compile(r"(https?://)([^/@\s]+)@")
REASONING_EVENT_TYPES = frozenset({"reasoning", "thinking"})


def validate_session_id(value: str | None) -> str | None:
    if value is None or SESSION_ID_PATTERN.fullmatch(value) is None:
        return None
    return value


def scrub_secrets(text: str | None, secrets: Iterable[str | None]) -> str:
    if not text:
        return ""
    scrubbed = text
    values = sorted({secret for secret in secrets if secret}, key=len, reverse=True)
    for secret in values:
        scrubbed = scrubbed.replace(secret, REDACTED)
    return URL_CREDENTIAL_PATTERN.sub(rf"\1{REDACTED}@", scrubbed)


@dataclass(frozen=True)
class AgentCommandResult:
    stdout_lines: tuple[str, ...]
    stderr: str


class AgentCommandError(RuntimeError):
    pass


class AgentCommandCancelled(AgentCommandError):
    pass


class AgentCommandTimeout(AgentCommandError):
    pass


class AgentCommandRunner:
    def __init__(self, *, termination_grace_seconds: float = 1.0) -> None:
        if termination_grace_seconds <= 0:
            raise ValueError("Termination grace period must be positive")
        self._termination_grace_seconds = termination_grace_seconds

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_seconds: float,
        secrets: Iterable[str | None] = (),
        cancel_event: threading.Event | None = None,
        on_stdout_line: Callable[[str], None] | None = None,
    ) -> AgentCommandResult:
        if timeout_seconds <= 0:
            raise ValueError("Agent command timeout must be positive")
        if command[0] == "opencode" and on_stdout_line is not None:
            return self._run_opencode(
                command, cwd=cwd, env=env, timeout_seconds=timeout_seconds,
                secrets=secrets, cancel_event=cancel_event,
                on_stdout_line=on_stdout_line,
            )
        from app.services.acceptance_reset import acceptance_reset, reset_enabled
        from app.services.acceptance_work import current_work

        owned = acceptance_reset.barrier.admit("agent-process", parent=current_work.get()) if reset_enabled() else None
        process: subprocess.Popen[str] | None = None
        drainers: list[threading.Thread] = []
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        failure: type[AgentCommandError] | None = None
        try:
            process = subprocess.Popen(
                list(command), cwd=cwd, env=dict(env), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, start_new_session=True,
            )
            drainers.append(self._start_drainer(
                process.stdout, stdout_lines,
                on_line=None if on_stdout_line is None else lambda line: on_stdout_line(scrub_secrets(line, secrets)),
            ))
            drainers.append(self._start_drainer(process.stderr, stderr_lines))
            deadline = time.monotonic() + timeout_seconds
            while process.poll() is None:
                if (cancel_event is not None and cancel_event.is_set()) or (owned is not None and owned.cancelled.is_set()):
                    failure = AgentCommandCancelled
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    failure = AgentCommandTimeout
                    break
                try:
                    process.wait(timeout=min(0.05, remaining))
                except subprocess.TimeoutExpired:
                    pass
            if failure is None and ((cancel_event is not None and cancel_event.is_set()) or (owned is not None and owned.cancelled.is_set())):
                failure = AgentCommandCancelled
            if failure is not None:
                self._terminate_process_group(process)
            elif process.returncode != 0:
                failure = AgentCommandError
                self._terminate_process_group(process)
            if owned is None:
                for drainer in drainers:
                    drainer.join(timeout=self._termination_grace_seconds)
        finally:
            if owned is not None:
                # The process lease is retained if termination cannot be proven.
                # EOF consumers include live callbacks and their finally blocks.
                termination_proven = process is None
                try:
                    if process is not None:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait(timeout=self._termination_grace_seconds)
                        termination_proven = True
                    for drainer in drainers:
                        drainer.join()
                finally:
                    if termination_proven and all(not drainer.is_alive() for drainer in drainers):
                        acceptance_reset.barrier.finish(owned)
        scrubbed_stdout = tuple(
            scrub_secrets(line.rstrip("\n"), secrets) for line in stdout_lines
        )
        scrubbed_stderr = scrub_secrets("".join(stderr_lines).strip(), secrets)
        if failure is not None:
            fallback = {
                AgentCommandCancelled: "Agent command was cancelled",
                AgentCommandTimeout: "Agent command timed out",
                AgentCommandError: "Agent command failed",
            }[failure]
            raise failure(scrubbed_stderr or "\n".join(scrubbed_stdout) or fallback)
        return AgentCommandResult(
            stdout_lines=scrubbed_stdout,
            stderr=scrubbed_stderr,
        )

    @staticmethod
    def _server_command(port: int) -> tuple[str, ...]:
        return (
            "opencode", "--print-logs", "--log-level", "ERROR", "serve",
            "--hostname", "127.0.0.1", "--port", str(port),
        )

    def _run_opencode(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_seconds: float,
        secrets: Iterable[str | None],
        cancel_event: threading.Event | None,
        on_stdout_line: Callable[[str], None],
    ) -> AgentCommandResult:
        # `run --format json` publishes only completed text parts. The headless
        # event API exposes the actual provider deltas before a part completes.
        from app.services.acceptance_reset import acceptance_reset, reset_enabled
        from app.services.acceptance_work import current_work

        owned = acceptance_reset.barrier.admit("agent-process", parent=current_work.get()) if reset_enabled() else None
        process: subprocess.Popen[str] | None = None
        drainers: list[threading.Thread] = []
        stdout: list[str] = []
        stderr: list[str] = []
        server_ready = threading.Event()
        password = uuid.uuid4().hex
        protected = (*secrets, password)
        deadline = time.monotonic() + timeout_seconds
        stage = "server startup"
        try:
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            environment = dict(env)
            environment["OPENCODE_SERVER_PASSWORD"] = password
            environment["OPENCODE_SERVER_USERNAME"] = "opencode"
            process = subprocess.Popen(
                self._server_command(port), cwd=cwd, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                start_new_session=True,
            )
            def observe_startup(line: str) -> None:
                if line.startswith(f"opencode server listening on http://127.0.0.1:{port}"):
                    server_ready.set()

            drainers = [
                self._start_drainer(process.stdout, stdout, observe_startup),
                self._start_drainer(process.stderr, stderr),
            ]

            async def consume() -> None:
                nonlocal stage
                while not server_ready.is_set():
                    await asyncio.sleep(0.025)
                async with httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{port}",
                    auth=("opencode", password), params={"directory": str(cwd)},
                    timeout=httpx.Timeout(5, read=None), trust_env=False,
                ) as client:
                    while True:
                        try:
                            health = await client.get("/global/health", timeout=1)
                            health.raise_for_status()
                            break
                        except (httpx.ConnectError, httpx.ReadTimeout):
                            await asyncio.sleep(0.025)
                    stage = "session setup"
                    session_id = (
                        command[command.index("--session") + 1]
                        if "--session" in command else None
                    )
                    if session_id is None:
                        response = await client.post("/session", json={"permission": [
                            {"permission": name, "action": "deny", "pattern": "*"}
                            for name in ("question", "plan_enter", "plan_exit")
                        ]})
                    else:
                        response = await client.get(f"/session/{session_id}")
                    response.raise_for_status()
                    session = response.json()
                    session_id = validate_session_id(session.get("id"))
                    if session_id is None or session.get("directory") != str(cwd):
                        raise AgentCommandError("Agent session does not belong to this workspace")
                    on_stdout_line(json.dumps({"sessionID": session_id}))
                    sessions = {session_id}
                    model = command[command.index("--model") + 1]
                    provider, _, model_id = model.partition("/")
                    prompt = command[-1]
                    # Preserve the pinned CLI's wire prompt quoting, including
                    # literal newlines and escaped internal quotation marks.
                    if " " in prompt:
                        prompt = '"' + prompt.replace(chr(34), chr(92) + chr(34)) + '"'
                    stage = "event subscription"
                    async with client.stream("GET", "/event") as events:
                        events.raise_for_status()
                        stage = "prompt submission"
                        # Subscribe before admitting the prompt: no early deltas
                        # or permission requests can be missed.
                        response = await client.post(f"/session/{session_id}/prompt_async", json={
                            "model": {"providerID": provider, "modelID": model_id},
                            "parts": [{"type": "text", "text": prompt}],
                        })
                        response.raise_for_status()
                        stage = "provider events"
                        async for line in events.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            raw = line[5:].lstrip()
                            event = json.loads(raw)
                            properties = event.get("properties", {})
                            info = properties.get("info", {})
                            if event.get("type") == "session.created" and info.get("parentID") in sessions:
                                child = validate_session_id(info.get("id"))
                                if child:
                                    sessions.add(child)
                            if event.get("type") == "permission.asked" and properties.get("sessionID") in sessions:
                                request_id = properties["id"]
                                reply = await client.post(f"/permission/{request_id}/reply", json={"reply": "once"})
                                reply.raise_for_status()
                            on_stdout_line(raw)
                            if properties.get("sessionID") != session_id:
                                continue
                            if event.get("type") == "session.error":
                                raise AgentCommandError("Agent provider failed")
                            if event.get("type") == "session.status" and properties.get("status", {}).get("type") == "idle":
                                return
                        raise AgentCommandError("Agent event stream ended before completion")

            async def supervise() -> None:
                consumer = asyncio.create_task(consume())
                try:
                    while not consumer.done():
                        if (cancel_event is not None and cancel_event.is_set()) or (owned is not None and owned.cancelled.is_set()):
                            raise AgentCommandCancelled(f"Agent command was cancelled during {stage}")
                        if time.monotonic() >= deadline:
                            raise AgentCommandTimeout(f"Agent command timed out during {stage}")
                        if process is not None and process.poll() is not None:
                            raise AgentCommandError("Agent event server exited")
                        await asyncio.wait({consumer}, timeout=0.025)
                    await consumer
                    if cancel_event is not None and cancel_event.is_set():
                        raise AgentCommandCancelled("Agent command was cancelled")
                finally:
                    consumer.cancel()
                    await asyncio.gather(consumer, return_exceptions=True)

            asyncio.run(supervise())
        except (httpx.HTTPError, ValueError, OSError) as error:
            raise AgentCommandError(scrub_secrets(str(error), protected)) from error
        finally:
            termination_proven = process is None
            try:
                if process is not None:
                    self._terminate_process_group(process)
                    # The group may outlive its leader (e.g. tools or watchers).
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=self._termination_grace_seconds)
                    termination_proven = True
                for drainer in drainers:
                    drainer.join(timeout=self._termination_grace_seconds)
            finally:
                if owned is not None and termination_proven and all(not thread.is_alive() for thread in drainers):
                    acceptance_reset.barrier.finish(owned)
        return AgentCommandResult(stdout_lines=(), stderr=scrub_secrets("".join(stderr), protected))

    @staticmethod
    def _start_drainer(
        stream: Iterable[str] | None,
        destination: list[str],
        on_line: Callable[[str], None] | None = None,
    ) -> threading.Thread:
        def drain() -> None:
            if stream is not None:
                for line in stream:
                    destination.append(line)
                    if on_line is not None:
                        on_line(line.rstrip("\n"))

        thread = threading.Thread(target=drain, daemon=True)
        thread.start()
        return thread

    def _terminate_process_group(self, process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=self._termination_grace_seconds)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=self._termination_grace_seconds)


class AgentEventKind(StrEnum):
    session = "session"
    activity = "activity"
    text = "text"
    error = "error"
    done = "done"


class AgentEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: AgentEventKind
    text: str | None = None
    session_id: str | None = None


class AgentActivityPart(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1)


class BoundedAgentOutput:
    def __init__(
        self,
        *,
        max_activity_parts: int,
        max_part_characters: int,
        max_response_characters: int = 100_000,
    ) -> None:
        if min(max_activity_parts, max_part_characters, max_response_characters) < 1:
            raise ValueError("Agent output bounds must be positive")
        self._max_activity_parts = max_activity_parts
        self._max_part_characters = max_part_characters
        self._max_response_characters = max_response_characters
        self._activity: list[AgentActivityPart] = []
        self._response_parts: list[str] = []
        self._response_characters = 0
        self.session_id: str | None = None

    @property
    def activity(self) -> tuple[AgentActivityPart, ...]:
        return tuple(self._activity)

    @property
    def response_text(self) -> str:
        return "".join(self._response_parts).strip()

    def add_activity(self, text: str) -> None:
        normalized = text.strip()
        if not normalized or len(self._activity) >= self._max_activity_parts:
            return
        self._activity.append(
            AgentActivityPart(text=normalized[: self._max_part_characters])
        )

    def add_event(self, event: AgentEvent) -> AgentEvent | None:
        if event.kind == AgentEventKind.session:
            self.session_id = validate_session_id(event.session_id)
        elif event.kind == AgentEventKind.activity and event.text is not None:
            count = len(self._activity)
            self.add_activity(event.text)
            if len(self._activity) == count:
                return None
            return event.model_copy(update={"text": self._activity[-1].text})
        elif event.kind == AgentEventKind.text and event.text is not None:
            remaining = self._max_response_characters - self._response_characters
            if remaining <= 0:
                return None
            part = event.text[:remaining]
            self._response_parts.append(part)
            self._response_characters += len(part)
            return event.model_copy(update={"text": part})
        return event


def normalize_opencode_line(
    raw_line: str, *, secrets: Iterable[str | None] = ()
) -> tuple[AgentEvent, ...]:
    try:
        event = json.loads(raw_line)
    except json.JSONDecodeError, TypeError:
        return ()
    if not isinstance(event, dict):
        return ()

    normalized: list[AgentEvent] = []
    session_id = validate_session_id(event.get("sessionID"))
    if session_id is not None:
        normalized.append(
            AgentEvent(kind=AgentEventKind.session, session_id=session_id)
        )

    event_type = event.get("type")
    part = event.get("part")
    if not isinstance(part, dict):
        part = {}
    part_type = part.get("type")
    if event_type == "step_start":
        normalized.append(AgentEvent(kind=AgentEventKind.activity, text="Thinking..."))
    elif event_type in REASONING_EVENT_TYPES or part_type in REASONING_EVENT_TYPES:
        text = str(part.get("text") or "").strip()
        if text:
            normalized.append(
                AgentEvent(
                    kind=AgentEventKind.activity,
                    text=scrub_secrets(text, secrets),
                )
            )
    elif event_type == "tool_use":
        description = describe_tool_activity(part)
        if description:
            normalized.append(
                AgentEvent(
                    kind=AgentEventKind.activity,
                    text=scrub_secrets(description, secrets),
                )
            )
    elif event_type == "text":
        text = scrub_secrets(str(part.get("text") or ""), secrets)
        if text.strip():
            normalized.append(AgentEvent(kind=AgentEventKind.text, text=text))
    return tuple(normalized)


class StreamingSecretScrubber:
    def __init__(self, secrets: Iterable[str | None]) -> None:
        self.secrets = tuple(secret for secret in secrets if secret)
        self.pending = ""

    def push(self, text: str, *, final: bool = False) -> str:
        self.pending = scrub_secrets(self.pending + text, self.secrets)
        cutoff = len(self.pending)
        if not final:
            # Keep a possible secret prefix until the next provider delta.
            for secret in self.secrets:
                for length in range(1, min(len(secret), len(self.pending) + 1)):
                    if self.pending.endswith(secret[:length]):
                        cutoff = min(cutoff, len(self.pending) - length)
            # URL userinfo is not safe to publish until the URL token ends.
            url = re.search(r"https?://[^\s]*$", self.pending)
            if url is not None:
                cutoff = min(cutoff, url.start())
        ready, self.pending = self.pending[:cutoff], self.pending[cutoff:]
        return ready


class OpenCodeEventNormalizer:
    """Normalize raw provider events, without replaying completed snapshots."""

    def __init__(self, *, session_id: str | None, secrets: Iterable[str | None]) -> None:
        self.session_id = session_id
        self.secrets = tuple(secrets)
        self.assistant_messages: set[str] = set()
        self.part_types: dict[str, str] = {}
        self.text_lengths: dict[str, int] = {}
        self.scrubbers: dict[str, StreamingSecretScrubber] = {}
        self.tool_descriptions: dict[str, str] = {}

    def normalize(self, line: str) -> tuple[AgentEvent, ...]:
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            return ()
        if not isinstance(event, dict):
            return ()
        properties = event.get("properties")
        if not isinstance(properties, dict):
            session = validate_session_id(event.get("sessionID"))
            if session is not None:
                self.session_id = session
            return normalize_opencode_line(line, secrets=self.secrets)
        if properties.get("sessionID") != self.session_id:
            return ()
        event_type = event.get("type")
        if event_type == "message.updated":
            info = properties.get("info", {})
            if info.get("role") == "assistant":
                self.assistant_messages.add(info["id"])
            return ()
        if event_type == "session.status" and properties.get("status", {}).get("type") == "idle":
            return tuple(
                AgentEvent(kind=AgentEventKind.text, text=text)
                for scrubber in self.scrubbers.values()
                if (text := scrubber.push("", final=True))
            )
        if event_type == "message.part.delta":
            part_id = properties.get("partID")
            if not isinstance(part_id, str) or properties.get("messageID") not in self.assistant_messages or properties.get("field") != "text" or self.part_types.get(part_id) != "text":
                return ()
            delta = properties.get("delta")
            if not isinstance(delta, str):
                return ()
            self.text_lengths[part_id] = self.text_lengths.get(part_id, 0) + len(delta)
            text = self.scrubbers.setdefault(part_id, StreamingSecretScrubber(self.secrets)).push(delta)
            return (AgentEvent(kind=AgentEventKind.text, text=text),) if text else ()
        if event_type != "message.part.updated":
            return ()
        part = properties.get("part", {})
        if part.get("messageID") not in self.assistant_messages:
            return ()
        part_id = part.get("id")
        if not isinstance(part_id, str):
            return ()
        part_type = part.get("type")
        self.part_types[part_id] = part_type
        if part_type == "text":
            snapshot = str(part.get("text") or "")
            emitted = self.text_lengths.get(part_id, 0)
            self.text_lengths[part_id] = max(emitted, len(snapshot))
            text = self.scrubbers.setdefault(part_id, StreamingSecretScrubber(self.secrets)).push(
                snapshot[emitted:], final=bool(part.get("time", {}).get("end")),
            )
            return (AgentEvent(kind=AgentEventKind.text, text=text),) if text else ()
        if part_type == "step-start":
            if part_id in self.tool_descriptions:
                return ()
            self.tool_descriptions[part_id] = "Thinking..."
            return (AgentEvent(kind=AgentEventKind.activity, text="Thinking..."),)
        if part_type == "tool":
            description = scrub_secrets(describe_tool_activity(part), self.secrets)
            if not description or self.tool_descriptions.get(part_id) == description:
                return ()
            self.tool_descriptions[part_id] = description
            return (AgentEvent(kind=AgentEventKind.activity, text=description),)
        if part_type == "reasoning" and part.get("time", {}).get("end"):
            description = scrub_secrets(str(part.get("text") or ""), self.secrets)
            if not description.strip() or self.tool_descriptions.get(part_id) == description:
                return ()
            self.tool_descriptions[part_id] = description
            return (AgentEvent(kind=AgentEventKind.activity, text=description),)
        return ()


def describe_tool_activity(part: dict[str, object]) -> str:
    tool = str(part.get("tool") or "")
    state = part.get("state")
    if not isinstance(state, dict):
        state = {}
    tool_input = state.get("input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    file_name = Path(str(tool_input.get("filePath") or "")).name or "a file"
    pattern = str(tool_input.get("pattern") or "")
    command = str(tool_input.get("command") or "").strip()
    descriptions = {
        "read": f"Reading {file_name}",
        "edit": f"Editing {file_name}",
        "write": f"Writing {file_name}",
        "patch": f"Patching {file_name}",
        "list": f"Listing {Path(str(tool_input.get('path') or '')).name or 'files'}",
        "glob": f"Searching {pattern or 'files'}",
        "grep": f"Searching for {pattern}".strip(),
        "bash": f"Running: {command[:60]}" if command else "Running a command",
        "webfetch": f"Fetching {tool_input.get('url') or 'a web page'}",
        "task": f"Delegating: {tool_input.get('description') or 'a subtask'}",
    }
    description = descriptions.get(tool, f"{tool}..." if tool else "")
    if description and state.get("status") == "error":
        return f"{description} - failed"
    return description


@dataclass(frozen=True)
class AgentCompletion:
    response_text: str
    activity: tuple[AgentActivityPart, ...]
    session_id: str | None


def summarize_conversation(messages: Iterable[object], *, max_characters: int) -> str:
    if max_characters < 1:
        raise ValueError("Conversation summary bound must be positive")
    lines: list[str] = []
    for message in messages:
        role = str(getattr(message, "role", "user"))
        content = str(getattr(message, "content", "")).strip()
        if content:
            lines.append(f"{role}: {content}")
    summary = "\n".join(lines)
    return summary[-max_characters:]


def build_explore_prompt(message: str) -> str:
    return f"/openspec explore {message.strip()}"


def build_propose_prompt(conversation: str) -> str:
    return f"/openspec propose {conversation.strip()}"


def build_apply_prompt() -> str:
    return "/openspec apply"


def minimal_agent_environment(
    source: Mapping[str, str],
    *,
    provider_key: str,
    provider_base_url: str | None,
) -> dict[str, str]:
    allowed = {
        "HOME",
        "LANG",
        "LC_ALL",
        "NODE_EXTRA_CA_CERTS",
        "PATH",
        "TMPDIR",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
    }
    from app.services.acceptance_reset import confined_environment

    environment = confined_environment({key: value for key, value in source.items() if key in allowed})
    environment["OPENAI_API_KEY"] = provider_key
    if provider_base_url:
        environment["OPENAI_BASE_URL"] = provider_base_url
    return environment


def execute_exploration(
    *,
    root: Path,
    chat_id: object,
    message: str,
    session_id: str | None,
    provider_key: str,
    provider_base_url: str | None,
    repository_secret: str | None,
    model: str,
    timeout_seconds: float,
    max_activity_parts: int,
    max_part_characters: int,
    max_response_characters: int,
    runner: AgentCommandRunner | None = None,
    source_environment: Mapping[str, str] | None = None,
    cancel_event: threading.Event | None = None,
    on_event: Callable[[AgentEvent], None] | None = None,
) -> AgentCompletion:
    return _execute_agent_prompt(
        root=root,
        chat_id=chat_id,
        prompt=build_explore_prompt(message),
        session_id=session_id,
        provider_key=provider_key,
        provider_base_url=provider_base_url,
        repository_secret=repository_secret,
        model=model,
        timeout_seconds=timeout_seconds,
        max_activity_parts=max_activity_parts,
        max_part_characters=max_part_characters,
        max_response_characters=max_response_characters,
        runner=runner,
        source_environment=source_environment,
        cancel_event=cancel_event,
        on_event=on_event,
    )


def execute_proposal(
    *,
    root: Path,
    chat_id: object,
    messages: Iterable[object],
    max_conversation_characters: int,
    session_id: str | None,
    provider_key: str,
    provider_base_url: str | None,
    repository_secret: str | None,
    model: str,
    timeout_seconds: float,
    max_activity_parts: int,
    max_part_characters: int,
    max_response_characters: int,
    runner: AgentCommandRunner | None = None,
    source_environment: Mapping[str, str] | None = None,
    cancel_event: threading.Event | None = None,
    on_event: Callable[[AgentEvent], None] | None = None,
) -> AgentCompletion:
    conversation = summarize_conversation(
        messages, max_characters=max_conversation_characters
    )
    if not conversation.strip():
        raise AgentCommandError("Development Chat has no conversation to propose")
    return _execute_agent_prompt(
        root=root,
        chat_id=chat_id,
        prompt=build_propose_prompt(conversation),
        session_id=session_id,
        provider_key=provider_key,
        provider_base_url=provider_base_url,
        repository_secret=repository_secret,
        model=model,
        timeout_seconds=timeout_seconds,
        max_activity_parts=max_activity_parts,
        max_part_characters=max_part_characters,
        max_response_characters=max_response_characters,
        runner=runner,
        source_environment=source_environment,
        cancel_event=cancel_event,
        on_event=on_event,
    )


def execute_apply(
    *,
    root: Path,
    chat_id: object,
    session_id: str | None,
    provider_key: str,
    provider_base_url: str | None,
    repository_secret: str | None,
    model: str,
    timeout_seconds: float,
    max_activity_parts: int,
    max_part_characters: int,
    max_response_characters: int,
    runner: AgentCommandRunner | None = None,
    source_environment: Mapping[str, str] | None = None,
    cancel_event: threading.Event | None = None,
    on_event: Callable[[AgentEvent], None] | None = None,
) -> AgentCompletion:
    return _execute_agent_prompt(
        root=root,
        chat_id=chat_id,
        prompt=build_apply_prompt(),
        session_id=session_id,
        provider_key=provider_key,
        provider_base_url=provider_base_url,
        repository_secret=repository_secret,
        model=model,
        timeout_seconds=timeout_seconds,
        max_activity_parts=max_activity_parts,
        max_part_characters=max_part_characters,
        max_response_characters=max_response_characters,
        runner=runner,
        source_environment=source_environment,
        cancel_event=cancel_event,
        on_event=on_event,
    )


def _execute_agent_prompt(
    *,
    root: Path,
    chat_id: object,
    prompt: str,
    session_id: str | None,
    provider_key: str,
    provider_base_url: str | None,
    repository_secret: str | None,
    model: str,
    timeout_seconds: float,
    max_activity_parts: int,
    max_part_characters: int,
    max_response_characters: int,
    runner: AgentCommandRunner | None,
    source_environment: Mapping[str, str] | None,
    cancel_event: threading.Event | None,
    on_event: Callable[[AgentEvent], None] | None,
) -> AgentCompletion:
    if not isinstance(chat_id, uuid.UUID):
        raise TypeError("chat_id must be a UUID")
    workspace = workspace_path(root=root, chat_id=chat_id)
    if not workspace.is_dir():
        raise AgentCommandError("Development Workspace is not ready")
    environment = minimal_agent_environment(
        source_environment if source_environment is not None else os.environ,
        provider_key=provider_key,
        provider_base_url=provider_base_url,
    )
    command = [
        "opencode",
        "run",
        "--print-logs",
        "--log-level",
        "ERROR",
        "--dir",
        str(workspace),
        "--format",
        "json",
        "--thinking",
        "--auto",
    ]
    validated_session_id = validate_session_id(session_id)
    if validated_session_id is not None:
        command.extend(("--session", validated_session_id))
    command.extend(("--model", model, prompt))
    secrets = (provider_key, provider_base_url, repository_secret)
    output = BoundedAgentOutput(
        max_activity_parts=max_activity_parts,
        max_part_characters=max_part_characters,
        max_response_characters=max_response_characters,
    )
    received_live_output = False
    normalizer = OpenCodeEventNormalizer(session_id=validated_session_id, secrets=secrets)

    def handle_line(line: str) -> None:
        nonlocal received_live_output
        received_live_output = True
        for event in normalizer.normalize(line):
            accepted = output.add_event(event)
            if on_event is not None and accepted is not None:
                on_event(accepted)

    result = (runner or AgentCommandRunner()).run(
        command,
        cwd=workspace,
        env=environment,
        timeout_seconds=timeout_seconds,
        secrets=secrets,
        cancel_event=cancel_event,
        on_stdout_line=handle_line,
    )
    if not received_live_output:
        for line in result.stdout_lines:
            handle_line(line)
    if not output.response_text:
        raise AgentCommandError(result.stderr or "The agent did not return a response")
    return AgentCompletion(
        response_text=output.response_text,
        activity=output.activity,
        session_id=output.session_id or validated_session_id,
    )

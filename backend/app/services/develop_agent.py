import json
import os
import re
import signal
import subprocess
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

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
    ) -> AgentCommandResult:
        if timeout_seconds <= 0:
            raise ValueError("Agent command timeout must be positive")
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        stdout_thread = self._start_drainer(process.stdout, stdout_lines)
        stderr_thread = self._start_drainer(process.stderr, stderr_lines)
        deadline = time.monotonic() + timeout_seconds
        failure: type[AgentCommandError] | None = None

        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
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

        if failure is not None:
            self._terminate_process_group(process)
        elif process.returncode != 0:
            failure = AgentCommandError
            self._terminate_process_group(process)

        stdout_thread.join(timeout=self._termination_grace_seconds)
        stderr_thread.join(timeout=self._termination_grace_seconds)
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
    def _start_drainer(
        stream: Iterable[str] | None, destination: list[str]
    ) -> threading.Thread:
        def drain() -> None:
            if stream is not None:
                destination.extend(stream)

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

    def add_event(self, event: AgentEvent) -> None:
        if event.kind == AgentEventKind.session:
            self.session_id = validate_session_id(event.session_id)
        elif event.kind == AgentEventKind.activity and event.text is not None:
            self.add_activity(event.text)
        elif event.kind == AgentEventKind.text and event.text is not None:
            remaining = self._max_response_characters - self._response_characters
            if remaining > 0:
                part = event.text[:remaining]
                self._response_parts.append(part)
                self._response_characters += len(part)


def normalize_opencode_line(
    raw_line: str, *, secrets: Iterable[str | None] = ()
) -> tuple[AgentEvent, ...]:
    try:
        event = json.loads(raw_line)
    except (json.JSONDecodeError, TypeError):
        return ()
    if not isinstance(event, dict):
        return ()

    normalized: list[AgentEvent] = []
    session_id = validate_session_id(event.get("sessionID"))
    if session_id is not None:
        normalized.append(AgentEvent(kind=AgentEventKind.session, session_id=session_id))

    event_type = event.get("type")
    part = event.get("part")
    if not isinstance(part, dict):
        part = {}
    part_type = part.get("type")
    if event_type == "step_start":
        normalized.append(
            AgentEvent(kind=AgentEventKind.activity, text="Thinking...")
        )
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


def summarize_conversation(messages: Iterable[object]) -> str:
    lines: list[str] = []
    for message in messages:
        role = str(getattr(message, "role", "user"))
        content = str(getattr(message, "content", "")).strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def build_explore_prompt(message: str) -> str:
    return f"/openspec explore {message.strip()}"


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
    environment = {key: value for key, value in source.items() if key in allowed}
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
) -> AgentCompletion:
    import uuid

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
    command.extend(("--model", model, build_explore_prompt(message)))
    secrets = (provider_key, provider_base_url, repository_secret)
    result = (runner or AgentCommandRunner()).run(
        command,
        cwd=workspace,
        env=environment,
        timeout_seconds=timeout_seconds,
        secrets=secrets,
    )
    output = BoundedAgentOutput(
        max_activity_parts=max_activity_parts,
        max_part_characters=max_part_characters,
        max_response_characters=max_response_characters,
    )
    for line in result.stdout_lines:
        for event in normalize_opencode_line(line, secrets=secrets):
            output.add_event(event)
    if not output.response_text:
        raise AgentCommandError(result.stderr or "The agent did not return a response")
    return AgentCompletion(
        response_text=output.response_text,
        activity=output.activity,
        session_id=output.session_id or validated_session_id,
    )

import json
import sys
import threading
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.develop_agent import (
    AgentActivityPart,
    AgentCommandCancelled,
    AgentCommandError,
    AgentCommandResult,
    AgentCommandRunner,
    AgentCommandTimeout,
    AgentEvent,
    AgentEventKind,
    BoundedAgentOutput,
    build_explore_prompt,
    execute_exploration,
    minimal_agent_environment,
    normalize_opencode_line,
    scrub_secrets,
    validate_session_id,
)


def test_agent_event_is_immutable() -> None:
    event = AgentEvent(kind=AgentEventKind.text, text="Done")

    with pytest.raises(ValidationError):
        event.text = "changed"


def test_activity_part_rejects_empty_text() -> None:
    with pytest.raises(ValidationError):
        AgentActivityPart(text="")


def test_agent_output_bounds_activity_count_and_content() -> None:
    output = BoundedAgentOutput(max_activity_parts=2, max_part_characters=5)

    output.add_activity("  Reading a long filename  ")
    output.add_activity("Editing README")
    output.add_activity("Ignored")

    assert [part.text for part in output.activity] == ["Readi", "Editi"]


def test_agent_output_ignores_blank_activity() -> None:
    output = BoundedAgentOutput(max_activity_parts=2, max_part_characters=10)

    output.add_activity("  ")

    assert output.activity == ()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ses_abc-123_DEF", "ses_abc-123_DEF"),
        ("chat_123", None),
        ("ses_has spaces", None),
        (None, None),
    ],
)
def test_validate_session_id(value: str | None, expected: str | None) -> None:
    assert validate_session_id(value) == expected


def test_scrub_secrets_removes_values_and_url_credentials() -> None:
    text = (
        "token=provider-secret repo=repository-secret "
        "url=https://user:password@example.com/repository.git"
    )

    scrubbed = scrub_secrets(text, ("provider-secret", "repository-secret"))

    assert "provider-secret" not in scrubbed
    assert "repository-secret" not in scrubbed
    assert "user:password" not in scrubbed
    assert scrubbed.count("[REDACTED]") == 3


PROCESS_FIXTURE = Path(__file__).parents[1] / "fixtures" / "agent_process.py"


def test_runner_collects_stdout() -> None:
    result = AgentCommandRunner().run(
        (sys.executable, str(PROCESS_FIXTURE), "events"),
        cwd=PROCESS_FIXTURE.parent,
        env={},
        timeout_seconds=2,
    )

    assert len(result.stdout_lines) == 1
    assert '"type": "text"' in result.stdout_lines[0]


def test_runner_scrubs_failure_output() -> None:
    with pytest.raises(AgentCommandError) as error:
        AgentCommandRunner().run(
            (sys.executable, str(PROCESS_FIXTURE), "failure"),
            cwd=PROCESS_FIXTURE.parent,
            env={},
            timeout_seconds=2,
            secrets=("provider-secret",),
        )

    assert "provider-secret" not in str(error.value)
    assert "[REDACTED]" in str(error.value)


def test_runner_cancels_process_group() -> None:
    cancel_event = threading.Event()
    timer = threading.Timer(0.1, cancel_event.set)
    timer.start()
    try:
        with pytest.raises(AgentCommandCancelled):
            AgentCommandRunner(termination_grace_seconds=0.1).run(
                (sys.executable, str(PROCESS_FIXTURE), "block"),
                cwd=PROCESS_FIXTURE.parent,
                env={},
                timeout_seconds=2,
                cancel_event=cancel_event,
            )
    finally:
        timer.cancel()


def test_runner_escalates_when_process_ignores_termination() -> None:
    started_at = time.monotonic()

    with pytest.raises(AgentCommandTimeout):
        AgentCommandRunner(termination_grace_seconds=0.1).run(
            (sys.executable, str(PROCESS_FIXTURE), "ignore-term"),
            cwd=PROCESS_FIXTURE.parent,
            env={},
            timeout_seconds=0.1,
        )

    assert time.monotonic() - started_at < 1


def test_normalize_representative_opencode_events() -> None:
    fixture = PROCESS_FIXTURE.parent / "opencode" / "events.jsonl"
    events = tuple(
        event
        for line in fixture.read_text().splitlines()
        for event in normalize_opencode_line(line, secrets=("provider-secret",))
    )

    output = BoundedAgentOutput(
        max_activity_parts=2,
        max_part_characters=100,
        max_response_characters=10,
    )
    for event in events:
        output.add_event(event)

    assert output.session_id == "ses_fixture_123"
    assert [part.text for part in output.activity] == [
        "Thinking...",
        "Inspecting [REDACTED]",
    ]
    assert output.response_text == "Repository"


def test_normalize_ignores_unknown_malformed_and_invalid_session_events() -> None:
    assert normalize_opencode_line("not-json") == ()
    assert normalize_opencode_line('{"type":"future_event"}') == ()
    assert normalize_opencode_line(
        '{"type":"text","sessionID":"invalid","part":{"text":"ok"}}'
    ) == (AgentEvent(kind=AgentEventKind.text, text="ok"),)


class RecordingAgentRunner(AgentCommandRunner):
    def __init__(self, lines: tuple[str, ...]) -> None:
        self.lines = lines
        self.calls: list[tuple[tuple[str, ...], Path, dict[str, str]]] = []

    def run(self, command, *, cwd, env, **_kwargs):  # type: ignore[no-untyped-def]
        self.calls.append((tuple(command), cwd, dict(env)))
        return AgentCommandResult(stdout_lines=self.lines, stderr="")


def test_exploration_is_confined_and_uses_minimal_environment(tmp_path: Path) -> None:
    chat_id = __import__("uuid").uuid4()
    workspace = tmp_path / str(chat_id)
    workspace.mkdir()
    runner = RecordingAgentRunner(
        (
            json.dumps(
                {
                    "type": "text",
                    "sessionID": "ses_new",
                    "part": {"text": "Explored"},
                }
            ),
        )
    )

    completion = execute_exploration(
        root=tmp_path,
        chat_id=chat_id,
        message=" inspect this repository ",
        session_id="ses_previous",
        provider_key="provider-key",
        provider_base_url="http://fake-llm:9000/v1",
        repository_secret="repository-secret",
        model="openai/test-model",
        timeout_seconds=2,
        max_activity_parts=5,
        max_part_characters=100,
        max_response_characters=100,
        runner=runner,
        source_environment={"PATH": "/bin", "UNRELATED_SECRET": "nope"},
    )

    command, cwd, environment = runner.calls[0]
    assert cwd == workspace
    assert command[-1] == build_explore_prompt("inspect this repository")
    assert command[command.index("--session") + 1] == "ses_previous"
    assert environment == {
        "PATH": "/bin",
        "OPENAI_API_KEY": "provider-key",
        "OPENAI_BASE_URL": "http://fake-llm:9000/v1",
    }
    assert completion.response_text == "Explored"
    assert completion.session_id == "ses_new"


def test_exploration_rejects_missing_or_non_owning_workspace(tmp_path: Path) -> None:
    with pytest.raises(AgentCommandError, match="not ready"):
        execute_exploration(
            root=tmp_path,
            chat_id=__import__("uuid").uuid4(),
            message="inspect",
            session_id=None,
            provider_key="provider-key",
            provider_base_url=None,
            repository_secret=None,
            model="openai/test-model",
            timeout_seconds=2,
            max_activity_parts=5,
            max_part_characters=100,
            max_response_characters=100,
            runner=RecordingAgentRunner(()),
        )


def test_minimal_agent_environment_drops_unrelated_values() -> None:
    assert minimal_agent_environment(
        {"PATH": "/bin", "DATABASE_URL": "secret", "DEMO_GITHUB_TOKEN": "secret"},
        provider_key="key",
        provider_base_url=None,
    ) == {"PATH": "/bin", "OPENAI_API_KEY": "key"}

import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from app.services.develop_preview_classification import classify_workspace
from app.services.develop_preview_detection import (
    relevant_turn_change,
    snapshot_workspace,
)
from app.services.develop_workspace import (
    FakeCommandRunner,
    WorkspacePathError,
    cleanup_workspace,
    prepare_workspace,
    setup_workspace,
    validate_workspace_path,
)


class RecordingCommandRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path, dict[str, str]]] = []

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: int,
    ) -> None:
        self.calls.append((tuple(command), cwd, dict(env)))
        if command[0] == "git":
            Path(command[-1]).mkdir()


def test_preview_classification_prefers_connected_website(tmp_path: Path) -> None:
    chat_id = uuid.uuid4()
    workspace = tmp_path / str(chat_id)
    (workspace / "src").mkdir(parents=True)
    (workspace / "index.html").write_text('<script src="/src/main.ts"></script>')
    (workspace / "src/main.ts").write_text("document.body.textContent = 'ready'")
    (workspace / "README.md").write_text("Swagger UI at http://localhost:8000/docs")

    result = classify_workspace(root=tmp_path, chat_id=chat_id)

    assert result.kind == "website"
    assert result.entry_point == "index.html"


def test_preview_classification_ignores_unrelated_and_other_chat_files(
    tmp_path: Path,
) -> None:
    chat_id = uuid.uuid4()
    workspace = tmp_path / str(chat_id)
    workspace.mkdir()
    (workspace / "index.html").write_text("<h1>Notes</h1>")
    (workspace / "utility.ts").write_text("export const value = 1")
    other = tmp_path / str(uuid.uuid4())
    other.mkdir()
    (other / "README.md").write_text("Swagger UI at /docs")

    assert classify_workspace(root=tmp_path, chat_id=chat_id).kind == "unknown"


def test_preview_classification_handles_invalid_manifest(tmp_path: Path) -> None:
    chat_id = uuid.uuid4()
    workspace = tmp_path / str(chat_id)
    (workspace / "src").mkdir(parents=True)
    (workspace / "package.json").write_text(
        '{"scripts":{"dev":"vite"},"dependencies":[]}'
    )
    (workspace / "src/main.ts").write_text("document.body.textContent = 'ready'")

    assert classify_workspace(root=tmp_path, chat_id=chat_id).kind == "unknown"


def test_preview_classification_returns_documented_api_page(tmp_path: Path) -> None:
    chat_id = uuid.uuid4()
    workspace = tmp_path / str(chat_id)
    workspace.mkdir()
    (workspace / "README.md").write_text(
        "API docs at http://localhost:8000/docs (Swagger UI)"
    )

    result = classify_workspace(root=tmp_path, chat_id=chat_id)

    assert result.kind == "api_documentation"
    assert result.entry_point == "/docs"


def test_preview_snapshots_detect_new_and_repeated_dirty_edits(tmp_path: Path) -> None:
    chat_id = uuid.uuid4()
    workspace = tmp_path / str(chat_id)
    workspace.mkdir()
    source = workspace / "index.html"
    before = snapshot_workspace(root=tmp_path, chat_id=chat_id)
    source.write_text("first")
    dirty = snapshot_workspace(root=tmp_path, chat_id=chat_id)
    source.write_text("second")
    changed_again = snapshot_workspace(root=tmp_path, chat_id=chat_id)

    assert relevant_turn_change(before, dirty) is True
    assert relevant_turn_change(dirty, changed_again) is True
    assert relevant_turn_change(changed_again, changed_again) is False


def test_preview_ignore_rules_cannot_be_overridden_by_checkout(tmp_path: Path) -> None:
    chat_id = uuid.uuid4()
    workspace = tmp_path / str(chat_id)
    workspace.mkdir()
    (workspace / "preview-ignore.txt").write_text("!openspec/\n!.claude/\n")
    before = snapshot_workspace(root=tmp_path, chat_id=chat_id)
    for directory in (
        "openspec",
        ".claude",
        ".git",
        "frontend/node_modules",
        "frontend/dist",
    ):
        target = workspace / directory
        target.mkdir(parents=True)
        (target / "index.html").write_text("ignored")
    (workspace / "openspec" / "preview-ignore.txt").write_text("!openspec/\n")
    (workspace / ".claude" / "preview-ignore.txt").write_text("!openspec/\n")

    assert (
        relevant_turn_change(before, snapshot_workspace(root=tmp_path, chat_id=chat_id))
        is False
    )


def test_preview_snapshot_returns_unavailable_when_budget_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_id = uuid.uuid4()
    workspace = tmp_path / str(chat_id)
    workspace.mkdir()
    (workspace / "index.html").write_text("too large")
    monkeypatch.setattr("app.services.develop_preview_detection.MAX_BYTES", 1)

    assert snapshot_workspace(root=tmp_path, chat_id=chat_id) is None
    assert relevant_turn_change({}, None) is None


def test_validate_workspace_path_requires_expected_direct_child(
    tmp_path: Path,
) -> None:
    chat_id = uuid.uuid4()

    with pytest.raises(WorkspacePathError):
        validate_workspace_path(
            root=tmp_path,
            chat_id=chat_id,
            candidate=tmp_path / ".." / str(chat_id),
        )


def test_cleanup_workspace_is_idempotent(tmp_path: Path) -> None:
    cleanup_workspace(root=tmp_path, chat_id=uuid.uuid4())


def test_prepare_workspace_removes_partial_setup(tmp_path: Path) -> None:
    chat_id = uuid.uuid4()
    workspace = tmp_path / str(chat_id)
    workspace.mkdir()
    (workspace / "partial-clone").write_text("incomplete")

    prepared = prepare_workspace(root=tmp_path, chat_id=chat_id)

    assert prepared == workspace
    assert not workspace.exists()
    assert tmp_path.is_dir()


def test_setup_workspace_isolates_chat_directories(tmp_path: Path) -> None:
    first_chat_id = uuid.uuid4()
    second_chat_id = uuid.uuid4()
    runner = FakeCommandRunner()

    first_workspace = setup_workspace(
        root=tmp_path,
        chat_id=first_chat_id,
        repository_url="https://example.com/owner/repository.git",
        repository_token="token",
        timeout=30,
        runner=runner,
    )
    first_marker = first_workspace / "first-chat-only"
    first_marker.touch()

    second_workspace = setup_workspace(
        root=tmp_path,
        chat_id=second_chat_id,
        repository_url="https://example.com/owner/repository.git",
        repository_token="token",
        timeout=30,
        runner=runner,
    )

    assert first_workspace != second_workspace
    assert first_marker.exists()
    assert not (second_workspace / first_marker.name).exists()


def test_cleanup_workspace_propagates_removal_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_id = uuid.uuid4()
    workspace = tmp_path / str(chat_id)
    workspace.mkdir()

    def fail_removal(_path: Path) -> None:
        raise OSError("removal denied")

    monkeypatch.setattr("app.services.develop_workspace.shutil.rmtree", fail_removal)

    with pytest.raises(OSError, match="removal denied"):
        cleanup_workspace(root=tmp_path, chat_id=chat_id)

    assert workspace.exists()


def test_setup_workspace_keeps_credentials_out_of_arguments(tmp_path: Path) -> None:
    chat_id = uuid.uuid4()
    token = "top-secret-token"
    runner = RecordingCommandRunner()

    workspace = setup_workspace(
        root=tmp_path,
        chat_id=chat_id,
        repository_url="https://example.com/owner/repository.git",
        repository_token=token,
        timeout=30,
        runner=runner,
    )

    assert [call[0][0] for call in runner.calls] == ["git", "opencode", "openspec"]
    assert all(token not in argument for call in runner.calls for argument in call[0])
    assert runner.calls[0][2]["DEMO_GITHUB_TOKEN"] == token
    assert "DEMO_GITHUB_TOKEN" not in runner.calls[1][2]
    assert "DEMO_GITHUB_TOKEN" not in runner.calls[2][2]
    assert runner.calls[1][1] == workspace
    assert runner.calls[2][1] == workspace
    helper_argument = next(
        argument
        for argument in runner.calls[0][0]
        if argument.startswith("credential.helper=")
    )
    assert not Path(helper_argument.removeprefix("credential.helper=")).exists()

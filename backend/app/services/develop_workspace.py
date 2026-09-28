import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol


class WorkspacePathError(ValueError):
    pass


class WorkspaceSetupError(RuntimeError):
    pass


class CommandRunner(Protocol):
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: int,
    ) -> None: ...


class SubprocessCommandRunner:
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: int,
    ) -> None:
        subprocess.run(
            list(command),
            check=True,
            capture_output=True,
            cwd=cwd,
            env=dict(env),
            text=True,
            timeout=timeout,
        )


class FakeCommandRunner:
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: int,
    ) -> None:
        del env, timeout
        if command[0] == "git":
            target = Path(command[-1])
            target.mkdir()
            (target / ".git").mkdir()
        elif command[0] == "opencode":
            (cwd / ".opencode-initialized").touch()
        elif command[0] == "openspec":
            (cwd / ".openspec-initialized").touch()


def validate_workspace_path(
    *, root: Path, chat_id: uuid.UUID, candidate: Path
) -> Path:
    resolved_root = root.resolve()
    expected = resolved_root / str(chat_id)
    resolved_candidate = candidate.resolve()
    if resolved_candidate != expected or resolved_candidate.parent != resolved_root:
        raise WorkspacePathError("Invalid Development Workspace path")
    return resolved_candidate


def workspace_path(*, root: Path, chat_id: uuid.UUID) -> Path:
    return validate_workspace_path(
        root=root,
        chat_id=chat_id,
        candidate=root / str(chat_id),
    )


def cleanup_workspace(*, root: Path, chat_id: uuid.UUID) -> None:
    target = workspace_path(root=root, chat_id=chat_id)
    if not target.exists():
        return
    shutil.rmtree(target)


def prepare_workspace(*, root: Path, chat_id: uuid.UUID) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    cleanup_workspace(root=root, chat_id=chat_id)
    return workspace_path(root=root, chat_id=chat_id)


def setup_workspace(
    *,
    root: Path,
    chat_id: uuid.UUID,
    repository_url: str,
    repository_token: str,
    timeout: int,
    runner: CommandRunner,
) -> Path:
    target = prepare_workspace(root=root, chat_id=chat_id)
    base_env = dict(os.environ)
    base_env.pop("DEMO_GITHUB_TOKEN", None)
    try:
        with tempfile.TemporaryDirectory(prefix=".credential-", dir=root) as temp_dir:
            helper = Path(temp_dir) / "git-credential-develop"
            helper.write_text(
                "#!/bin/sh\n"
                'if [ "$1" = "get" ]; then\n'
                "  printf '%s\\n' 'username=x-access-token' "
                '"password=$DEMO_GITHUB_TOKEN"\n'
                "fi\n"
            )
            helper.chmod(0o700)
            clone_env = {**base_env, "DEMO_GITHUB_TOKEN": repository_token}
            runner.run(
                (
                    "git",
                    "-c",
                    f"credential.helper={helper}",
                    "clone",
                    repository_url,
                    str(target),
                ),
                cwd=root.resolve(),
                env=clone_env,
                timeout=timeout,
            )
        runner.run(
            ("opencode", "init"),
            cwd=target,
            env=base_env,
            timeout=timeout,
        )
        runner.run(
            ("openspec", "init", "--tools", "opencode"),
            cwd=target,
            env=base_env,
            timeout=timeout,
        )
    except Exception as error:
        cleanup_workspace(root=root, chat_id=chat_id)
        raise WorkspaceSetupError("Development Workspace setup failed") from error
    return target

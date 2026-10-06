import hashlib
import os
import stat
import tempfile
import time
from pathlib import Path

MAX_FILES = 10_000
MAX_BYTES = 64 * 1024 * 1024
MAX_SECONDS = 2.0
IGNORED = frozenset(
    {
        ".git",
        ".claude",
        "openspec",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".next",
        "dist",
        "build",
        "coverage",
        ".npmrc",
        ".pypirc",
        "id_rsa",
        "id_ed25519",
    }
)


def _private(name: str) -> bool:
    return (
        name in IGNORED
        or name == ".env"
        or name.startswith(".env.")
        or name.endswith((".pem", ".key"))
    )


def _safe_directory(root: Path, parts: tuple[str, ...]) -> Path:
    directory = root
    for part in parts:
        directory /= part
        if directory.is_symlink():
            raise RuntimeError("Preview workspace contains a redirected directory")
        directory.mkdir(exist_ok=True)
        if not directory.is_dir():
            raise RuntimeError("Preview workspace path is not a directory")
    return directory


def sync_workspace(
    checkout: Path, workspace: Path, previous: dict[str, bytes]
) -> dict[str, bytes]:
    deadline = time.monotonic() + MAX_SECONDS
    current: dict[str, bytes] = {}
    total = 0
    pending = [(checkout, ())]
    while pending:
        directory, parts = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if time.monotonic() > deadline:
                    raise RuntimeError("Preview source sync timed out")
                if _private(entry.name) or entry.is_symlink():
                    continue
                child = (*parts, entry.name)
                if entry.is_dir(follow_symlinks=False):
                    pending.append((Path(entry.path), child))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                if len(current) >= MAX_FILES:
                    raise RuntimeError("Preview source file limit exceeded")
                source = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    metadata = os.fstat(source)
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                        continue
                    total += metadata.st_size
                    if total > MAX_BYTES:
                        raise RuntimeError("Preview source size limit exceeded")
                    content = bytearray()
                    while chunk := os.read(source, 64 * 1024):
                        content.extend(chunk)
                        if (
                            len(content) > metadata.st_size
                            or time.monotonic() > deadline
                        ):
                            raise RuntimeError(
                                "Preview source changed or sync timed out"
                            )
                    if (
                        len(content) != metadata.st_size
                        or os.fstat(source).st_mtime_ns != metadata.st_mtime_ns
                    ):
                        raise RuntimeError("Preview source changed during sync")
                finally:
                    os.close(source)
                name = "/".join(child)
                digest = hashlib.sha256(content).digest()
                current[name] = digest
                if previous.get(name) == digest:
                    continue
                destination = _safe_directory(workspace, parts) / entry.name
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=destination.parent, delete=False
                    ) as target:
                        temporary = Path(target.name)
                        target.write(content)
                    temporary.chmod(metadata.st_mode & 0o755)
                    os.replace(temporary, destination)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
    for name in previous.keys() - current.keys():
        parts = tuple(name.split("/"))
        directory = workspace
        for part in parts[:-1]:
            directory /= part
            if directory.is_symlink() or not directory.is_dir():
                break
        else:
            destination = directory / parts[-1]
            if destination.is_file() or destination.is_symlink():
                destination.unlink()
    return current

import hashlib
import os
import time
from pathlib import Path

from app.services.develop_workspace import workspace_path

MAX_FILES = 10_000
MAX_BYTES = 64 * 1024 * 1024
MAX_SECONDS = 2.0
IGNORE_RULES = tuple(
    line.strip().rstrip("/")
    for line in Path(__file__).with_name("preview-ignore.txt").read_text().splitlines()
    if line.strip() and not line.startswith("#")
)


def _ignored(relative_path: str) -> bool:
    return any(part in IGNORE_RULES for part in relative_path.split("/"))


def snapshot_workspace(*, root: Path, chat_id: object) -> dict[str, bytes] | None:
    from uuid import UUID

    if not isinstance(chat_id, UUID):
        raise TypeError("chat_id must be a UUID")
    workspace = workspace_path(root=root, chat_id=chat_id)
    deadline = time.monotonic() + MAX_SECONDS
    snapshot: dict[str, bytes] = {}
    total_bytes = 0
    pending = [(workspace, "")]
    try:
        while pending:
            directory, prefix = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    if time.monotonic() > deadline:
                        return None
                    relative = f"{prefix}{entry.name}"
                    if _ignored(relative):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append((Path(entry.path), relative + "/"))
                        continue
                    if len(snapshot) >= MAX_FILES:
                        return None
                    digest = hashlib.sha256()
                    if entry.is_symlink():
                        digest.update(os.readlink(entry.path).encode())
                    elif entry.is_file(follow_symlinks=False):
                        with open(entry.path, "rb") as source:
                            while chunk := source.read(64 * 1024):
                                total_bytes += len(chunk)
                                if (
                                    total_bytes > MAX_BYTES
                                    or time.monotonic() > deadline
                                ):
                                    return None
                                digest.update(chunk)
                    else:
                        continue
                    snapshot[relative] = digest.digest()
    except OSError:
        return None
    return snapshot


def relevant_turn_change(
    before: dict[str, bytes] | None, after: dict[str, bytes] | None
) -> bool | None:
    if before is None or after is None:
        return None
    return before != after

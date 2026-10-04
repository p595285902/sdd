import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.services.develop_preview_detection import IGNORE_RULES
from app.services.develop_workspace import workspace_path

MAX_FILES = 10_000
MAX_SECONDS = 2.0
MAX_TEXT_BYTES = 256 * 1024
FRAMEWORK_COMMANDS = re.compile(
    r"^(?:vite|next\s+dev|nuxt\s+dev|astro\s+dev|react-scripts\s+start|ng\s+serve)(?:\s|$)"
)
FRAMEWORK_ENTRIES = (
    "src/main.ts",
    "src/main.tsx",
    "src/main.js",
    "src/main.jsx",
    "src/index.tsx",
    "src/index.jsx",
    "src/App.tsx",
    "app/page.tsx",
    "src/app/page.tsx",
    "pages/index.tsx",
    "src/pages/index.tsx",
)


@dataclass(frozen=True)
class PreviewClassification:
    kind: str
    entry_point: str | None = None


class ScriptReferences(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            source = dict(attrs).get("src")
            if source:
                self.sources.append(source)


def _read_text(path: Path) -> str | None:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_TEXT_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except OSError, UnicodeError:
        return None


def _files(workspace: Path) -> set[str] | None:
    deadline = time.monotonic() + MAX_SECONDS
    files: set[str] = set()
    pending = [(workspace, "")]
    try:
        while pending:
            directory, prefix = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    if time.monotonic() > deadline:
                        return None
                    relative = f"{prefix}{entry.name}"
                    if entry.name in IGNORE_RULES or entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append((Path(entry.path), relative + "/"))
                    elif entry.is_file(follow_symlinks=False):
                        files.add(relative)
                        if len(files) > MAX_FILES:
                            return None
    except OSError:
        return None
    return files


def _website_entry(workspace: Path, files: set[str]) -> str | None:
    for entry in sorted(
        name for name in files if name.endswith("/index.html") or name == "index.html"
    ):
        html = _read_text(workspace / entry)
        if html is None:
            continue
        references = ScriptReferences()
        references.feed(html)
        for source in references.sources:
            url = urlsplit(source)
            if url.scheme or url.netloc or not url.path:
                continue
            script = unquote(url.path)
            if script.startswith("/"):
                target = script.lstrip("/")
            else:
                target = os.path.normpath(str(Path(entry).parent / script))
            if target in files and target.endswith((".js", ".jsx", ".ts", ".tsx")):
                return entry

    for manifest in sorted(
        name
        for name in files
        if name == "package.json" or name.endswith("/package.json")
    ):
        content = _read_text(workspace / manifest)
        if content is None:
            continue
        try:
            package = json.loads(content)
        except ValueError, TypeError:
            continue
        if not isinstance(package, dict):
            continue
        scripts = package.get("scripts", {})
        dependencies = package.get("dependencies", {})
        dev_dependencies = package.get("devDependencies", {})
        if not all(
            isinstance(value, dict)
            for value in (scripts, dependencies, dev_dependencies)
        ):
            continue
        if not any(
            isinstance(command, str) and FRAMEWORK_COMMANDS.match(command)
            for name, command in scripts.items()
            if name in ("dev", "start")
        ):
            continue
        if not any(
            name in dependencies or name in dev_dependencies
            for name in (
                "vite",
                "next",
                "nuxt",
                "astro",
                "react-scripts",
                "@angular/cli",
            )
        ):
            continue
        directory = Path(manifest).parent
        for entry in FRAMEWORK_ENTRIES:
            candidate = (directory / entry).as_posix()
            if candidate in files:
                return candidate
    return None


def classify_workspace(*, root: Path, chat_id: uuid.UUID) -> PreviewClassification:
    if not isinstance(chat_id, uuid.UUID):
        raise TypeError("chat_id must be a UUID")
    workspace = workspace_path(root=root, chat_id=chat_id)
    files = _files(workspace)
    if files is None:
        return PreviewClassification("unknown")
    entry = _website_entry(workspace, files)
    if entry is not None:
        return PreviewClassification("website", entry)
    for readme in sorted(
        name for name in files if name.lower() in ("readme.md", "readme.rst")
    ):
        content = _read_text(workspace / readme)
        if content:
            match = re.search(
                r"(?:(?:swagger(?:\s+ui)?|openapi).{0,100}(/docs|/swagger|/openapi\.json)|(/docs|/swagger|/openapi\.json).{0,100}(?:swagger(?:\s+ui)?|openapi))",
                content,
                re.IGNORECASE,
            )
            if match:
                return PreviewClassification("api_documentation", match[1] or match[2])
    return PreviewClassification("unknown")

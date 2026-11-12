"""Read-only, source-backed discovery of checkout-local native Compose workflows.

This module never invokes a process, reads project environment values or fetches a
URL. Native Compose, in the private sandbox, resolves the actual service model.
"""
from __future__ import annotations

import hashlib
import re
import shlex
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

MAX_DOCUMENTS = 16
MAX_DEPTH = 4
MAX_TEXT = 1024 * 1024
MAX_COMMANDS = 16
LINK = re.compile(r"\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)")
URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1):(\d{1,5})(/[^\s<>`\])},;]*)?")
COMPOSE = re.compile(r"\bdocker(?:\s+compose|[-]compose)\b")
ACTIONS = {"run", "up", "watch", "build", "pull", "create", "config", "down", "stop", "logs", "exec", "restart", "ps"}
START = {"up", "watch"}
SETUP = {"run", "build", "pull"}
MAINTENANCE = re.compile(r"\b(test(?:ing|s)?|cleanup|tear.?down|stop(?:ping)?|maintenance|production|deployment|troubleshoot(?:ing)?)\b", re.I)


class PreviewInstructionsError(ValueError):
    """An actionable instruction problem, safe to retain as operation text."""


@dataclass(frozen=True)
class Document:
    path: str
    text: str
    sha256: str


@dataclass(frozen=True)
class NativeCommand:
    cwd: str
    argv: list[str]
    source: dict
    kind: str
    env: dict[str, str]


@dataclass(frozen=True)
class NativePreviewPlan:
    commands: list[NativeCommand]
    application: dict
    sources: list[dict]
    runtime: str = "native-compose"

    def as_dict(self) -> dict:
        return asdict(self)


def confined(checkout: Path, value: str, *, directory: bool = False) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise PreviewInstructionsError("Instruction paths must be relative to the selected checkout")
    try:
        target = (checkout / path).resolve(strict=True)
    except (OSError, ValueError, RuntimeError) as error:
        raise PreviewInstructionsError(f"Missing checkout-local instruction path: {value}") from error
    if not target.is_relative_to(checkout) or (directory and not target.is_dir()):
        raise PreviewInstructionsError(f"Instruction path escapes the selected checkout: {value}")
    return target


def read_startup_documents(checkout: Path, pointer: str | None = None) -> list[Document]:
    checkout = checkout.resolve(strict=True)
    roots = next(([name] for name in ("README.md", "README", "readme.md") if (checkout / name).is_file()), [])
    if pointer and pointer not in roots:
        roots.append(pointer)
    queue = deque((name, 0) for name in roots)
    seen: set[tuple[int, int]] = set()
    result: list[Document] = []
    total = 0
    while queue:
        name, depth = queue.popleft()
        try:
            path = confined(checkout, name)
        except PreviewInstructionsError:
            if name in roots:
                raise
            continue  # Escaping symlinks are never opened.
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino)
        if identity in seen:
            continue
        if len(result) >= MAX_DOCUMENTS or depth > MAX_DEPTH:
            raise PreviewInstructionsError("Linked startup documentation exceeds the checkout-local traversal budget")
        seen.add(identity)
        if not path.is_file() or path.suffix.lower() not in ("", ".md", ".rst", ".txt"):
            continue
        with path.open("rb") as stream:
            data = stream.read(MAX_TEXT - total + 1)
        total += len(data)
        if total > MAX_TEXT:
            raise PreviewInstructionsError("Startup documentation exceeds the one-MiB text budget")
        try:
            text = data.decode("utf-8")
        except UnicodeError as error:
            raise PreviewInstructionsError(f"Startup documentation is not UTF-8: {name}") from error
        relative = path.relative_to(checkout).as_posix()
        result.append(Document(relative, text, hashlib.sha256(data).hexdigest()))
        for match in LINK.finditer(text):
            value = urlsplit(unquote(match[1].strip("<>")))
            if value.scheme or value.netloc or not value.path:
                continue
            linked = path.parent / value.path
            try:
                relative_link = linked.relative_to(checkout).as_posix()
            except ValueError:
                continue
            if linked.suffix.lower() in (".md", ".rst", ".txt", ""):
                queue.append((relative_link, depth + 1))
    return result


def compose_action(argv: list[str]) -> tuple[int, str] | None:
    offset = 2 if argv[:2] == ["docker", "compose"] else 1 if argv[:1] == ["docker-compose"] else 0
    if not offset:
        return None
    valued = {"-f", "--file", "--env-file", "--profile", "--project-directory", "-p", "--project-name", "--ansi", "--progress", "--parallel"}
    i = offset
    while i < len(argv):
        token = argv[i]
        if token in valued:
            i += 2
        elif token.startswith("-"):
            i += 1
        elif token in ACTIONS:
            return i, token
        else:
            raise PreviewInstructionsError(f"Unsupported documented Compose option or command: {token}")
    raise PreviewInstructionsError("Documented Compose command has no action")


def config_command(command: dict) -> list[str]:
    action = compose_action(command["argv"])
    if action is None:
        raise PreviewInstructionsError("Native configuration requires a documented Compose command")
    return [*command["argv"][:action[0]], "config", "--format", "json"]


def _segments(text: str) -> list[list[str]]:
    lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    lexer.commenters = "#"
    words = list(lexer)
    result: list[list[str]] = [[]]
    for word in words:
        if word == "&&":
            if not result[-1]:
                raise PreviewInstructionsError("Incomplete documented command sequence")
            result.append([])
        elif word in (";", "||", "|", "&", ">", "<", ">>", "<<"):
            raise PreviewInstructionsError("Provide checkout-local startup commands without unsupported pipes, redirects or unconditional shell sequencing")
        else:
            result[-1].append(word)
    if not result[-1]:
        raise PreviewInstructionsError("Incomplete documented command sequence")
    return result


def _commands(checkout: Path, document: Document) -> list[NativeCommand]:
    result: list[NativeCommand] = []
    fenced = False
    shell_fence = False
    cwd = "."
    headings: list[tuple[int, str]] = []
    pending = ""
    pending_line = 0
    native_lines: set[int] = set()
    block_start = None
    lines = document.text.splitlines()
    for number, line in enumerate(lines, 1):
        if line.strip().startswith(("```", "~~~")):
            if block_start is None:
                block_start = number
            else:
                if COMPOSE.search("\n".join(lines[block_start:number - 1])):
                    native_lines.update(range(block_start + 1, number))
                block_start = None
    context_env: dict[str, str] = {}
    for line_number, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if fenced:
                fenced = False
            else:
                fenced = True
                language = stripped[3:].strip().lower()
                shell_fence = language in ("", "sh", "shell", "bash", "console", "shellsession")
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)", raw)
        if heading and not fenced:
            level = len(heading[1])
            headings = [item for item in headings if item[0] < level]
            headings.append((level, heading[2]))
        if MAINTENANCE.search(" ".join(text for _, text in headings)):
            continue
        if fenced:
            if not shell_fence or not stripped or stripped.startswith("#"):
                continue
            candidate = stripped.removeprefix("$ ")
        else:
            candidates = re.findall(r"`([^`]+)`", raw)
            if len(candidates) != 1 or not COMPOSE.search(candidates[0]):
                continue
            candidate = candidates[0]
        if pending:
            candidate = pending + candidate
        else:
            pending_line = line_number
        if candidate.endswith("\\"):
            pending = candidate[:-1] + " "
            continue
        pending = ""
        # Host-local alternative commands are never concatenated into Compose.
        # A standalone cd in a shell block is preserved for subsequent commands.
        in_native_context = line_number in native_lines or bool(re.search(r"\bdocker\b|\bcompose\b", " ".join(text for _, text in headings), re.I))
        if not COMPOSE.search(candidate) and not in_native_context:
            continue
        try:
            segments = _segments(candidate)
        except PreviewInstructionsError:
            raise
        except ValueError as error:
            raise PreviewInstructionsError(f"Invalid shell quoting in {document.path}:{pending_line}") from error
        for argv in segments:
            if argv[0] == "cd":
                if len(argv) != 2:
                    raise PreviewInstructionsError("Document a single checkout-local working directory")
                cwd = confined(checkout, str(Path(cwd) / argv[1]), directory=True).relative_to(checkout).as_posix() or "."
                continue
            exporting = argv[0] == "export"
            if exporting:
                argv = argv[1:]
            env = dict(context_env)
            while argv and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", argv[0]):
                key, value = argv.pop(0).split("=", 1)
                if key.startswith("DOCKER_") or key in ("HOME", "PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "COMPOSE_FILE", "COMPOSE_ENV_FILES"):
                    raise PreviewInstructionsError("Project startup must not select platform Docker settings or runtime control paths")
                env[key] = value
            if exporting and not argv:
                context_env = env
                continue
            if not argv:
                raise PreviewInstructionsError("Documented environment assignments require an explicit command")
            action = compose_action(argv)
            if action is None:
                if argv[0] not in ("cp", "mkdir", "sh", "bash", "python", "python3") and not argv[0].startswith("./"):
                    raise PreviewInstructionsError(f"Unsupported setup command in {document.path}:{pending_line}; provide an explicit checkout-local startup sequence")
                verb = "setup"
            else:
                _, verb = action
                if verb not in START | SETUP:
                    continue  # Diagnostic/maintenance examples are not startup.
            if any("\x00" in value or len(value) > 2048 for value in argv) or len(argv) > 128:
                raise PreviewInstructionsError("Documented startup command exceeds argument limits")
            if any(re.search(r"\$\(|`|\$\{?", value) for value in argv):
                raise PreviewInstructionsError("Resolve shell substitutions in the checkout-local startup instructions; project .env interpolation remains supported by Compose")
            result.append(NativeCommand(cwd, argv, {"path": document.path, "line": pending_line}, "start" if verb in START else "setup", env))
    if pending:
        raise PreviewInstructionsError(f"Unterminated startup command in {document.path}")
    return result


def resolve_native_plan(checkout: Path, *, pointer: str | None = None, answer: str | None = None) -> NativePreviewPlan | None:
    checkout = checkout.resolve(strict=True)
    documents = read_startup_documents(checkout, pointer)
    clarification = None
    if answer and COMPOSE.search(answer):
        if len(answer.encode()) > 8192:
            raise PreviewInstructionsError("Chat-local startup clarification exceeds the text limit")
        if "`" in answer or "~~~" in answer:
            text = answer
        else:
            command_text = "\n".join(line for line in answer.splitlines() if not URL.search(line))
            entry_text = "\n".join(line for line in answer.splitlines() if URL.search(line))
            text = f"# Docker development\n```sh\n{command_text}\n```\n{entry_text}\n"
        clarification = Document("<chat clarification>", text, hashlib.sha256(answer.encode()).hexdigest())
        documents.append(clarification)
    commands: list[NativeCommand] = []
    seen = set()
    entries: list[tuple[dict, str]] = []
    for document in documents:
        for command in (_commands(checkout, document) if clarification is None or document is clarification else []):
            key = (command.cwd, tuple(command.argv), tuple(command.env.items()))
            if key not in seen:
                seen.add(key)
                commands.append(command)
        for line_number, line in enumerate(document.text.splitlines(), 1):
            for match in URL.finditer(line):
                port = int(match[1])
                if not 1 <= port <= 65535:
                    raise PreviewInstructionsError("Documented application port is invalid")
                path = match[2] or "/"
                if line[match.end():match.end() + 1] not in ("`", ">", ")"):
                    # Bare prose URLs exclude sentence-ending periods. Explicit
                    # Markdown URL boundaries preserve meaningful trailing dots.
                    path = path.rstrip(".") or "/"
                entries.append(({"port": port, "path": path, "source": {"path": document.path, "line": line_number}}, line.lower()))
    if not commands:
        return None
    if len(commands) > MAX_COMMANDS:
        raise PreviewInstructionsError("Documented Compose workflow exceeds the command limit")
    startup = [command for command in commands if command.kind == "start"]
    if not startup:
        raise PreviewInstructionsError("Compose setup is documented, but no application startup command is provided")
    if len(startup) != 1:
        refs = ", ".join(f"{command.source['path']}:{command.source['line']}" for command in startup)
        raise PreviewInstructionsError(f"Conflicting full-stack Docker startup instructions ({refs}); document which workflow to use")
    if commands[-1] != startup[0]:
        raise PreviewInstructionsError("The documented workflow has setup after startup; clarify the ordered full-stack sequence")
    candidates = [entry for entry, context in entries if not re.search(r"mailpit|adminer|administration|mail tool|database|swagger.*tool", context)]
    preferred = [entry for entry, context in entries if re.search(r"application|website|frontend|web ui", context) and entry in candidates]
    candidates = preferred or candidates
    unique = {(entry["port"], entry["path"]): entry for entry in candidates}
    if len(unique) > 1:
        raise PreviewInstructionsError("Conflicting application entry points; identify the main application separately from auxiliary tools")
    if unique:
        application = next(iter(unique.values()))
    else:
        # Existing documented Compose website/API fixtures select the service by
        # name; native config supplies that service's real target port later.
        text = "\n".join(document.text for document in documents).lower()
        roles = [role for role in ("website", "frontend") if re.search(rf"\b{role}\b", text)]
        if len(roles) != 1:
            raise PreviewInstructionsError("Document the main application's localhost URL or identify its website service")
        application = {"service": roles[0], "path": "/", "source": startup[0].source}
    return NativePreviewPlan(commands, application, [{"path": document.path, "sha256": document.sha256} for document in documents])

import io
import json
import os
import re
import shlex
import stat
import tarfile
import time
from pathlib import Path

from app.services.preview_workspace_sync import _private

DEFAULT_FILES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
SERVICE_NAME = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}\Z")
IMAGE = "python:3.14-slim-bookworm@sha256:c8137f4c460908c8763f281c8f22c431eb5c538514ba9553fc3a89c06b7cfb88"
NODE_IMAGE = "node:24.15-bookworm-slim@sha256:4e6b70dd6cbfc88c8157ba19aa3d9f9cce6ba4703576d55459e45efcbc9c5f5d"
IMAGES = frozenset({IMAGE, NODE_IMAGE})
SERVICE_KEYS = frozenset({"image", "build", "depends_on", "command", "working_dir", "expose"})
DEPENDENCY_COMMANDS = {
    "pip install --no-cache-dir -r requirements.txt": ("python", "requirements.txt"),
    "npm ci --ignore-scripts": ("node", "package-lock.json"),
}


def documented_compose(checkout: Path) -> tuple[Path, tuple[str, ...]] | None:
    readme = checkout / "README.md"
    if readme.is_symlink() or not readme.is_file() or readme.stat().st_size > 256 * 1024:
        return None
    for line in readme.read_text(encoding="utf-8").splitlines():
        command = re.search(r"\bdocker(?:\s+compose|-compose)\s+", line)
        if command is None:
            continue
        prefix = line[:command.start()].lower()
        if re.search(r"\b(?:do not|don't|never|avoid)\b", prefix):
            continue
        inline = command.start() > 0 and line[command.start() - 1] == "`"
        end = line.find("`", command.start()) if inline else -1
        if inline and end < 0:
            raise ValueError("Unclosed documented Compose command")
        text = line[command.start():end] if inline else line[command.start():].strip().rstrip(".")
        try:
            words = shlex.split(text)
        except ValueError:
            raise ValueError("Invalid documented Compose command") from None
        if len(words) > 16 or any(any(char in word for char in "$`;|&<>") for word in words):
            raise ValueError("Unsupported documented Compose command")
        args = words[2:] if words[:2] == ["docker", "compose"] else words[1:]
        if args[:1] == ["-f"] and len(args) >= 3:
            filename, args = args[1], args[2:]
        else:
            filename = next((name for name in DEFAULT_FILES if (checkout / name).is_file()), None)
        if not filename or not args or args[0] != "up":
            continue
        services = tuple(arg for arg in args[1:] if arg != "-d")
        if not services or any(not SERVICE_NAME.fullmatch(name) for name in services):
            raise ValueError("Document the Compose service names explicitly")
        relative = Path(filename)
        if relative.is_absolute() or ".." in relative.parts or relative.name not in DEFAULT_FILES:
            raise ValueError("Unsupported Compose file path")
        path = checkout / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(checkout.resolve()):
            return None
        if path.stat().st_size > 128 * 1024:
            raise ValueError("Compose file is too large")
        return path, services
    return None


def _plain(value: object) -> bool:
    if isinstance(value, str):
        return "$" not in value and "\x00" not in value
    if isinstance(value, list):
        return all(_plain(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _plain(key) and _plain(item) for key, item in value.items())
    return value is None or isinstance(value, (bool, int))


def validated_graph(checkout: Path, path: Path, selected: tuple[str, ...]) -> list[tuple[str, dict]]:
    import yaml

    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader: UniqueLoader, node: yaml.MappingNode) -> dict:
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node)
            if not isinstance(key, str) or key in result:
                raise ValueError("Duplicate or invalid Compose key")
            result[key] = loader.construct_object(value_node)
        return result

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        source = path.read_text(encoding="utf-8")
        if any(isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for token in yaml.scan(source)):
            raise ValueError("Compose aliases and anchors are unsupported")
        model = yaml.load(source, Loader=UniqueLoader)
    except yaml.YAMLError:
        raise ValueError("Invalid Compose YAML") from None
    if not isinstance(model, dict) or set(model) != {"services"} or not _plain(model):
        raise ValueError("Unsupported Compose model or interpolation")
    services = model["services"]
    if not isinstance(services, dict) or not services or len(services) > 8:
        raise ValueError("Unsupported Compose services")
    if any(not isinstance(name, str) or not SERVICE_NAME.fullmatch(name) for name in services):
        raise ValueError("Invalid Compose service name")
    resolved: list[tuple[str, dict]] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ValueError("Cyclic Compose dependencies")
        if name in visited:
            return
        service = services.get(name)
        if not isinstance(service, dict) or not service or set(service) - SERVICE_KEYS:
            raise ValueError(f"Unsupported Compose service: {name}")
        if ("image" in service) == ("build" in service):
            raise ValueError("Service requires exactly one approved image or build")
        if "image" in service and service["image"] not in IMAGES:
            raise ValueError("Unapproved Compose image source")
        command = service.get("command")
        if not isinstance(command, list) or not command or len(command) > 24 or any(
            not isinstance(arg, str) or len(arg) > 240 for arg in command
        ):
            raise ValueError("Compose commands must be bounded argument lists")
        directory = service.get("working_dir", "/workspace")
        if not isinstance(directory, str) or not Path(directory).is_relative_to("/workspace") or ".." in Path(directory).parts:
            raise ValueError("Unsupported Compose working directory")
        ports = service.get("expose", [])
        if not isinstance(ports, list) or any(
            not isinstance(port, int) or not 1024 <= port <= 65535 for port in ports
        ) or len(ports) > 2:
            raise ValueError("Unsupported Compose service ports")
        dependencies = service.get("depends_on", [])
        if not isinstance(dependencies, list) or any(
            not isinstance(item, str) or not SERVICE_NAME.fullmatch(item) for item in dependencies
        ):
            raise ValueError("Unsupported Compose dependencies")
        if "build" in service:
            build = service["build"]
            if not isinstance(build, dict) or set(build) != {"context", "dockerfile"}:
                raise ValueError("Unsupported Compose build")
            context = Path(build["context"]) if isinstance(build["context"], str) else Path("/")
            dockerfile = Path(build["dockerfile"]) if isinstance(build["dockerfile"], str) else Path("/")
            if context.is_absolute() or ".." in context.parts or any(_private(part) for part in context.parts) or dockerfile.is_absolute() or ".." in dockerfile.parts:
                raise ValueError("Build input is outside the checkout")
            source = checkout / context
            definition = source / dockerfile
            if not source.is_dir() or not source.resolve().is_relative_to(checkout.resolve()) or not definition.is_file() or definition.is_symlink() or not definition.resolve().is_relative_to(source.resolve()):
                raise ValueError("Build input is outside the checkout")
        visiting.add(name)
        for dependency in dependencies:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)
        resolved.append((name, service))

    for name in selected:
        visit(name)
    return resolved


def staged_build(checkout: Path, build: dict) -> tuple[bytes, str | None, str]:
    context = checkout / build["context"]
    dockerfile = Path(build["dockerfile"])
    definition = context / dockerfile
    if definition.is_symlink() or definition.stat().st_size > 16 * 1024:
        raise ValueError("Unsupported Dockerfile")
    validated_definition = definition.read_bytes()
    instructions = validated_definition.decode("utf-8").splitlines()
    if not instructions or not instructions[0].startswith("FROM "):
        raise ValueError("Unsupported Dockerfile base image")
    base_image = instructions[0].removeprefix("FROM ")
    dependency = None
    replacement = None
    for line in instructions:
        if not line or line.startswith("#"):
            continue
        operation, _, arguments = line.partition(" ")
        if operation == "FROM":
            if arguments not in IMAGES or line != instructions[0]:
                raise ValueError("Unapproved Dockerfile image source")
        elif operation == "COPY":
            words = shlex.split(arguments)
            if len(words) != 2 or words[0].startswith("-"):
                raise ValueError("Unsupported Dockerfile COPY")
            source = Path(words[0])
            destination = Path(words[1])
            if (
                source.is_absolute() or ".." in source.parts
                or not (context / source).resolve().is_relative_to(context.resolve())
                or any(_private(part) for part in source.parts)
                or any(char in words[0] for char in "*?[]")
                or not (context / source).exists()
                or not destination.is_relative_to("/workspace")
                or ".." in destination.parts
            ):
                raise ValueError("Dockerfile COPY escapes build context")
        elif operation == "WORKDIR":
            if not arguments.startswith("/workspace") or ".." in Path(arguments).parts:
                raise ValueError("Unsupported Dockerfile working directory")
        elif operation == "USER":
            if arguments not in ("65534", "65534:65534"):
                raise ValueError("Unsupported Dockerfile user")
        elif operation == "RUN":
            if dependency is not None or arguments not in DEPENDENCY_COMMANDS or "COPY . /workspace" not in instructions[:instructions.index(line)]:
                raise ValueError("Unsupported Dockerfile instruction or build egress")
            dependency, filename = DEPENDENCY_COMMANDS[arguments]
            if (dependency == "python" and base_image != IMAGE) or (dependency == "node" and base_image != NODE_IMAGE):
                raise ValueError("Dependency manager does not match the pinned base image")
            if dependency == "python":
                requirements = context / filename
                if requirements.is_symlink() or not requirements.is_file() or requirements.stat().st_size > 4096:
                    raise ValueError("Unsupported requirements source")
                lines = requirements.read_text(encoding="utf-8").splitlines()
                if not lines or len(lines) > 20 or any(not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]*==[a-zA-Z0-9_.!+-]+", entry) for entry in lines):
                    raise ValueError("Dependencies must use pinned packages")
                replacement = "COPY .preview-deps/python /usr/local/lib/python3.14/site-packages"
            else:
                package = context / "package.json"
                lock = context / filename
                if any(path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 for path in (package, lock)):
                    raise ValueError("Unsupported npm lock source")
                try:
                    manifest = json.loads(package.read_text(encoding="utf-8"))
                    locked = json.loads(lock.read_text(encoding="utf-8"))
                except (UnicodeError, ValueError):
                    raise ValueError("Invalid npm dependency manifests") from None
                packages = locked.get("packages") if isinstance(locked, dict) else None
                if (
                    not isinstance(manifest, dict) or not isinstance(packages, dict)
                    or locked.get("lockfileVersion") != 3 or len(packages) > 150
                    or not isinstance(packages.get(""), dict)
                    or not isinstance(manifest.get("dependencies"), dict)
                    or manifest.get("dependencies", {}) != packages[""].get("dependencies", {})
                    or set(manifest) - {"name", "version", "dependencies"}
                ):
                    raise ValueError("Unsupported npm lock source")
                for entry in packages.values():
                    if not isinstance(entry, dict):
                        raise ValueError("Unsupported npm dependency declaration")
                    dependencies = entry.get("dependencies", {})
                    if not isinstance(dependencies, dict) or any(
                        not isinstance(name, str) or not isinstance(version, str)
                        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.]+)?", version)
                        for name, version in dependencies.items()
                    ):
                        raise ValueError("Unsupported npm dependency declaration")
                for path, entry in packages.items():
                    if path == "":
                        continue
                    if (
                        not isinstance(path, str) or not path.startswith("node_modules/")
                        or ".." in Path(path).parts or not isinstance(entry, dict)
                        or not isinstance(entry.get("version"), str)
                        or not isinstance(entry.get("resolved"), str)
                        or not re.fullmatch(r"https://registry\.npmjs\.org/[a-zA-Z0-9@._%/-]+", entry.get("resolved", ""))
                        or not isinstance(entry.get("integrity"), str)
                        or not re.fullmatch(r"sha512-[a-zA-Z0-9+/]+=*", entry.get("integrity", ""))
                        or any(key in entry for key in ("hasInstallScript", "bin", "link"))
                    ):
                        raise ValueError("Unsupported npm dependency source")
                replacement = "COPY .preview-deps/node_modules /workspace/node_modules"
        else:
            raise ValueError("Unsupported Dockerfile instruction or build egress")
    if (context / ".preview-deps").exists():
        raise ValueError("Reserved build dependency path")
    archive = io.BytesIO()
    total = 0
    count = 0
    deadline = time.monotonic() + 3
    with tarfile.open(fileobj=archive, mode="w") as output:
        root_fd = os.open(context, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for directory, subdirs, filenames in os.walk(context, followlinks=False):
                if time.monotonic() > deadline:
                    raise ValueError("Build staging timed out")
                relative_dir = Path(directory).relative_to(context)
                directory_fd = os.dup(root_fd)
                try:
                    for part in relative_dir.parts:
                        next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                        os.close(directory_fd)
                        directory_fd = next_fd
                    subdirs[:] = [name for name in subdirs if not _private(name)]
                    for name in (*subdirs, *filenames):
                        if stat.S_ISLNK(os.stat(name, dir_fd=directory_fd, follow_symlinks=False).st_mode):
                            raise ValueError("Build input contains a symlink")
                    for name in filenames:
                        if _private(name):
                            continue
                        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
                        try:
                            info = os.fstat(descriptor)
                            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                                raise ValueError("Unsupported build input")
                            count += 1
                            total += info.st_size
                            if count > 2000 or total > 16 * 1024 * 1024 or time.monotonic() > deadline:
                                raise ValueError("Build context exceeds preview limits")
                            entry = tarfile.TarInfo((relative_dir / name).as_posix())
                            entry.size = info.st_size
                            entry.mode = 0o644
                            entry.uid = entry.gid = 65534
                            with os.fdopen(descriptor, "rb", closefd=False) as content:
                                output.addfile(entry, content)
                            if os.fstat(descriptor).st_mtime_ns != info.st_mtime_ns:
                                raise ValueError("Build source changed during staging")
                        finally:
                            os.close(descriptor)
                finally:
                    os.close(directory_fd)
        finally:
            os.close(root_fd)
    with tarfile.open(fileobj=io.BytesIO(archive.getvalue())) as staged:
        member = staged.getmember(dockerfile.as_posix()) if dockerfile.as_posix() in staged.getnames() else None
        if member is None or staged.extractfile(member).read() != validated_definition:
            raise ValueError("Dockerfile changed during build staging")
    if dependency is not None:
        rewritten = validated_definition.decode("utf-8").replace(
            "RUN " + next(command for command, (kind, _) in DEPENDENCY_COMMANDS.items() if kind == dependency),
            replacement,
        ).encode()
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w") as target, tarfile.open(fileobj=io.BytesIO(archive.getvalue())) as original:
            for member in original:
                if member.name == dockerfile.as_posix():
                    member.size = len(rewritten)
                    target.addfile(member, io.BytesIO(rewritten))
                else:
                    target.addfile(member, original.extractfile(member))
        if output.tell() > 16 * 1024 * 1024:
            raise ValueError("Build context exceeds preview limits")
        return output.getvalue(), dependency, base_image
    if archive.tell() > 16 * 1024 * 1024:
        raise ValueError("Build context exceeds preview limits")
    return archive.getvalue(), None, base_image

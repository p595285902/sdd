"""Best-effort masking of known values, before journaling or transport.

Pending prefixes exist only in this bounded in-memory object. Persist only the
strings returned by feed/finish, never an input chunk or this object's buffers.
This does not defend against deliberate encodings or hostile secret disclosure.
"""

import re
from collections.abc import Iterable
from typing import Any

SECRET_KEY = re.compile(
    r"password|passwd|secret|token|api[_-]?key|private[_-]?key|credential", re.I
)


def command_secrets(command: dict[str, Any]) -> list[str]:
    """Find literal credentials in command env, assignments and option values."""
    values = [str(value) for key, value in command.get("env", {}).items()
              if value and SECRET_KEY.search(key)]
    argv = command.get("argv", [])
    for index, argument in enumerate(argv):
        key, equals, value = argument.partition("=")
        if equals and SECRET_KEY.search(key) and value:
            values.append(value)
        elif argument.startswith("-") and SECRET_KEY.search(argument) and index + 1 < len(argv):
            value = argv[index + 1]
            if value and not value.startswith("-"):
                values.append(value)
    return values


class SecretRedactor:
    def __init__(
        self,
        secrets: Iterable[str] = (),
        *,
        replacement: str = "[REDACTED]",
        max_secret_length: int = 16_384,
        max_secret_characters: int = 65_536,
        max_secrets: int = 512,
        max_streams: int = 16,
    ) -> None:
        if min(max_secret_length, max_secret_characters, max_secrets, max_streams) < 1:
            raise ValueError("Redaction bounds must be positive")
        if not replacement:
            raise ValueError("Redaction replacement must not be empty")
        self._replacement = replacement
        self._max_secret_length = max_secret_length
        self._max_secret_characters = max_secret_characters
        self._max_secrets = max_secrets
        self._max_streams = max_streams
        self._secrets: set[str] = set()
        self._by_first: dict[str, tuple[str, ...]] = {}
        self._pending: dict[str, str] = {}
        self.update_secrets(secrets)

    def update_secrets(self, secrets: Iterable[str]) -> None:
        """Add newly known values; keep previous values safe across file changes.

        Fail closed on excessive configuration, without including values in the
        error. Existing stream buffers remain private and use the expanded set.
        """
        values = set(self._secrets)
        total = sum(map(len, values))
        for value in secrets:
            if not isinstance(value, str):
                raise TypeError("Known secret values must be strings")
            if not value or value in values:
                continue
            total += len(value)
            if (
                len(value) > self._max_secret_length
                or total > self._max_secret_characters
                or len(values) >= self._max_secrets
            ):
                raise ValueError("Known secret values exceed redaction bounds")
            values.add(value)
        by_first: dict[str, list[str]] = {}
        for value in sorted(values, key=lambda item: (-len(item), item)):
            by_first.setdefault(value[0], []).append(value)
        self._secrets = values
        self._by_first = {key: tuple(value) for key, value in by_first.items()}

    def _scan(self, text: str, *, final: bool) -> tuple[str, str]:
        if not self._secrets:
            return text, ""
        output: list[str] = []
        position = 0
        while position < len(text):
            candidates = self._by_first.get(text[position], ())
            remaining = len(text) - position
            # A longer secret may share a prefix with an already complete short
            # one. Do not mask the short one and leak the longer one's suffix.
            incomplete = any(
                remaining < len(secret) and secret.startswith(text[position:])
                for secret in candidates
            )
            if incomplete and not final:
                return "".join(output), text[position:]
            match = next(
                (secret for secret in candidates if text.startswith(secret, position)),
                None,
            )
            if match is not None:
                output.append(self._replacement)
                position += len(match)
            else:
                output.append(text[position])
                position += 1
        return "".join(output), ""

    def feed(self, stream: str, text: str) -> str:
        """Return safe text, retaining at most max_secret_length-1 characters.

        Use distinct stable stream IDs for independent command/stdout/stderr
        streams. Finish a stream before reusing its ID for a different process.
        """
        if not stream or len(stream) > 128:
            raise ValueError("Invalid redaction stream identifier")
        if stream not in self._pending and len(self._pending) >= self._max_streams:
            raise ValueError("Too many redaction streams")
        safe, pending = self._scan(self._pending.get(stream, "") + text, final=False)
        self._pending[stream] = pending
        return safe

    def finish(self, stream: str) -> str:
        """Close a stream, masking rather than releasing an incomplete secret."""
        # Only possible secret prefixes are retained by feed. Never flush their
        # raw bytes, even though no complete value has yet been observed.
        return self._replacement if self._pending.pop(stream, "") else ""

    def redact(self, text: str) -> str:
        """Mask a complete standalone value, without affecting any streams."""
        safe, _ = self._scan(text, final=True)
        return safe

    def redact_json(self, value: Any) -> Any:
        """Copy/redact workflow, source and argv metadata, including dict keys."""
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return {
                self.redact(key) if isinstance(key, str) else key: self.redact_json(
                    item
                )
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self.redact_json(item) for item in value]
        return value

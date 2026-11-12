import itertools

import pytest

from app.services.preview_redaction import SecretRedactor, command_secrets


@pytest.mark.parametrize("argv", [
    ["docker", "compose", "run", "-e", "API_TOKEN=literal-credential", "api"],
    ["docker", "compose", "run", "-ePASSWORD=literal-credential", "api"],
    ["docker", "compose", "build", "--build-arg", "DB_PASSWORD=literal-credential"],
    ["docker", "compose", "run", "api", "--password", "literal-credential"],
    ["docker", "compose", "run", "api", "--token=literal-credential"],
])
def test_literal_command_credentials_are_known_before_metadata_or_output(argv) -> None:
    command = {"argv": argv, "env": {"FIRST_USER_PASSWORD": "env-credential"}}
    redactor = SecretRedactor(command_secrets(command))
    assert "literal-credential" not in str(redactor.redact_json(command))
    assert "env-credential" not in str(redactor.redact_json(command))
    assert redactor.feed("stdout", "literal-") == ""
    assert redactor.feed("stdout", "credential!") == "[REDACTED]!"


def test_redacts_every_split_point_before_any_text_is_persistable() -> None:
    secret = "project-password-123"
    for split in range(len(secret) + 1):
        redactor = SecretRedactor([secret])
        returned = [
            redactor.feed("stdout", "before " + secret[:split]),
            redactor.feed("stdout", secret[split:] + " after"),
            redactor.finish("stdout"),
        ]
        assert "".join(returned) == "before [REDACTED] after"
        assert all(secret not in chunk for chunk in returned)


def test_longest_prefix_secret_does_not_expose_longer_suffix() -> None:
    for parts in (("abc", "def"), ("a", "b", "c", "d", "ef"), ("abcdef",)):
        redactor = SecretRedactor(["abc", "abcdef", "ab"])
        assert (
            "".join(redactor.feed("stdout", part) for part in parts)
            + redactor.finish("stdout")
            == "[REDACTED]"
        )
    assert SecretRedactor(["abc", "abcdef"]).redact("abc!") == "[REDACTED]!"


def test_independent_streams_do_not_mix_buffers() -> None:
    redactor = SecretRedactor(["alpha-secret", "beta-secret"])
    assert redactor.feed("stdout", "out alpha-") == "out "
    assert redactor.feed("stderr", "err beta-") == "err "
    assert redactor.feed("stderr", "secret!") == "[REDACTED]!"
    assert redactor.feed("stdout", "secret!") == "[REDACTED]!"
    assert redactor.finish("stdout") == ""
    assert redactor.finish("stderr") == ""


def test_finish_never_returns_pending_raw_secret_prefix() -> None:
    redactor = SecretRedactor(["sensitive-value"])
    assert redactor.feed("stdout", "safe: sensi") == "safe: "
    assert redactor.finish("stdout") == "[REDACTED]"
    assert redactor.finish("stdout") == ""
    # Standalone metadata is complete, not a pending stream buffer.
    assert redactor.redact("sensi") == "sensi"
    assert SecretRedactor(["database-password"]).redact("README.md") == "README.md"


def test_false_prefix_does_not_drop_unrelated_output() -> None:
    redactor = SecretRedactor(["password"])
    assert redactor.feed("stdout", "pass") == ""
    assert redactor.feed("stdout", "age!") == "passage!"
    assert redactor.finish("stdout") == ""


def test_pending_memory_is_bounded_even_for_large_output() -> None:
    redactor = SecretRedactor(["a" * 32], max_secret_length=32)
    result = redactor.feed("stdout", "a" * 100_000)
    assert result == "[REDACTED]" * 3125
    assert len(redactor._pending["stdout"]) < 32
    redactor.feed("stdout", "a" * 31)
    assert len(redactor._pending["stdout"]) == 31
    assert redactor.finish("stdout") == "[REDACTED]"


def test_secret_updates_retain_old_values_and_pending_protection() -> None:
    redactor = SecretRedactor(["old-password"])
    assert redactor.feed("stdout", "old-") == ""
    redactor.update_secrets(["new-password"])
    assert redactor.feed("stdout", "password new-password!") == "[REDACTED] [REDACTED]!"
    assert redactor.redact("old-password") == "[REDACTED]"


def test_redacts_nested_workflow_argv_source_and_keys_without_mutating_input() -> None:
    value = {
        "secret-value": {
            "argv": ["compose", "--password=secret-value"],
            "source": "README secret-value",
            "cwd": "directory/secret-value",
        }
    }
    redactor = SecretRedactor(["secret-value"])
    safe = redactor.redact_json(value)
    assert "secret-value" not in str(safe)
    assert "secret-value" in str(value)
    assert safe["[REDACTED]"]["argv"][1] == "--password=[REDACTED]"


def test_resource_limits_fail_closed_without_secret_in_error() -> None:
    with pytest.raises(ValueError, match="bounds") as error:
        SecretRedactor(["private-value"], max_secret_length=3)
    assert "private-value" not in str(error.value)
    with pytest.raises(ValueError, match="bounds"):
        SecretRedactor(itertools.repeat("x" * 3, 10), max_secret_characters=2)
    with pytest.raises(ValueError, match="bounds"):
        SecretRedactor(["one", "two"], max_secrets=1)
    redactor = SecretRedactor(["secret"], max_streams=1)
    redactor.feed("stdout", "sec")
    with pytest.raises(ValueError, match="streams"):
        redactor.feed("stderr", "sec")
    redactor.finish("stdout")
    assert redactor.feed("stderr", "safe!") == "safe!"


def test_redact_does_not_consume_or_expose_stream_buffers() -> None:
    redactor = SecretRedactor(["password"])
    assert redactor.feed("stdout", "pass") == ""
    assert redactor.redact("--key=password") == "--key=[REDACTED]"
    assert redactor.feed("stdout", "word!") == "[REDACTED]!"


def test_plain_text_is_not_html_or_markdown_interpreted() -> None:
    text = "<script>alert(1)</script>\x1b[31m**text**"
    redactor = SecretRedactor()
    assert redactor.redact(text) == text
    assert redactor.feed("stdout", text) == text

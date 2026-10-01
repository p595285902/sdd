from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings


def _settings_data(**overrides: object) -> dict[str, object]:
    data = settings.model_dump(exclude={"emails_enabled"})
    data.update(overrides)
    return data


def _production_settings_data(**overrides: object) -> dict[str, object]:
    data = _settings_data(
        FASTAPI_ENV=None,
        SECRET_KEY="production-secret-key",
        DATABASE_URL="postgresql://postgres:production-password@db:5432/app",
        FIRST_SUPERUSER_PASSWORD="production-superuser-password",
    )
    data.update(overrides)
    return data


def test_repository_configuration_may_be_missing() -> None:
    configured = Settings.model_validate(
        _settings_data(
            DEMO_GITHUB_REPO=None,
            DEMO_GITHUB_TOKEN=None,
        )
    )

    assert configured.DEMO_GITHUB_REPO is None
    assert configured.DEMO_GITHUB_TOKEN is None


@pytest.mark.parametrize(
    "repository_url",
    [
        "https://token@example.com/owner/repository.git",
        "ftp://example.com/owner/repository.git",
        "not-a-url",
    ],
)
def test_repository_url_must_be_tokenless_http_url(repository_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            _settings_data(DEMO_GITHUB_REPO=repository_url)
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("DEVELOP_WORKSPACE_ROOT", Path("relative/workspaces")),
        ("DEVELOP_SETUP_TIMEOUT_SECONDS", 0),
        ("DEVELOP_SETUP_TIMEOUT_SECONDS", 3601),
    ],
)
def test_workspace_configuration_rejects_unsafe_values(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(_settings_data(**{field: value}))


def test_acceptance_mode_rejects_external_provider_endpoint() -> None:
    with pytest.raises(ValidationError, match="loopback OpenAI provider"):
        Settings.model_validate(
            _settings_data(
                DEVELOP_ACCEPTANCE_MODE=True,
                DEVELOP_FAKE_SETUP_RUNNER=True,
                OPENAI_BASE_URL="https://api.openai.com/v1",
            )
        )


def test_acceptance_mode_rejects_real_setup_runner() -> None:
    with pytest.raises(ValidationError, match="fake setup runner"):
        Settings.model_validate(
            _settings_data(
                DEVELOP_ACCEPTANCE_MODE=True,
                DEVELOP_FAKE_SETUP_RUNNER=False,
                OPENAI_BASE_URL="http://127.0.0.1:8000/v1",
            )
        )


def test_acceptance_mode_allows_loopback_provider_endpoint() -> None:
    configured = Settings.model_validate(
        _settings_data(
            DEVELOP_ACCEPTANCE_MODE=True,
            DEVELOP_FAKE_SETUP_RUNNER=True,
            OPENAI_BASE_URL="http://127.0.0.1:8000/v1",
        )
    )

    assert configured.OPENAI_BASE_URL
    assert configured.OPENAI_BASE_URL.host == "127.0.0.1"


def test_production_allows_develop_to_be_disabled() -> None:
    configured = Settings.model_validate(
        _production_settings_data(
            DEMO_GITHUB_REPO=None,
            DEMO_GITHUB_TOKEN=None,
            OPENAI_API_KEY=None,
        )
    )

    assert configured.DEMO_GITHUB_REPO is None
    assert configured.DEMO_GITHUB_TOKEN is None
    assert configured.OPENAI_API_KEY is None


@pytest.mark.parametrize(
    "missing_field",
    ["DEMO_GITHUB_REPO", "DEMO_GITHUB_TOKEN", "OPENAI_API_KEY"],
)
def test_production_rejects_incomplete_develop_configuration(
    missing_field: str,
) -> None:
    develop_configuration: dict[str, object] = {
        "DEMO_GITHUB_REPO": "https://example.com/owner/repository.git",
        "DEMO_GITHUB_TOKEN": "repository-token",
        "OPENAI_API_KEY": "provider-key",
    }
    develop_configuration[missing_field] = None

    with pytest.raises(ValidationError, match=missing_field):
        Settings.model_validate(_production_settings_data(**develop_configuration))


def test_development_allows_partial_develop_configuration() -> None:
    configured = Settings.model_validate(
        _settings_data(
            FASTAPI_ENV="development",
            DEMO_GITHUB_REPO="https://example.com/owner/repository.git",
            DEMO_GITHUB_TOKEN=None,
            OPENAI_API_KEY=None,
        )
    )

    assert configured.DEMO_GITHUB_REPO is not None


def test_turn_lifecycle_configuration_defaults_are_bounded() -> None:
    configured = Settings.model_validate(_settings_data())

    assert configured.DEVELOP_TURN_TIMEOUT_SECONDS == 600
    assert configured.DEVELOP_TURN_PRESENCE_GRACE_SECONDS == 10
    assert configured.DEVELOP_TURN_REPLAY_LIMIT == 200
    assert configured.DEVELOP_USER_CONCURRENT_TURN_LIMIT_DEFAULT == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("DEVELOP_TURN_TIMEOUT_SECONDS", 0),
        ("DEVELOP_TURN_PRESENCE_GRACE_SECONDS", -1),
        ("DEVELOP_TURN_REPLAY_LIMIT", 0),
        ("DEVELOP_USER_CONCURRENT_TURN_LIMIT_DEFAULT", 0),
    ],
)
def test_turn_lifecycle_configuration_rejects_unsafe_values(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(_settings_data(**{field: value}))

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings


def _settings_data(**overrides: object) -> dict[str, object]:
    data = settings.model_dump(exclude={"emails_enabled"})
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

import warnings
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    EmailStr,
    Field,
    HttpUrl,
    PostgresDsn,
    SecretStr,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    DEVELOP_HISTORY_LIMIT: int = Field(default=20, ge=1, le=100)
    DEVELOP_MESSAGE_PAGE_SIZE: int = Field(default=50, ge=1, le=100)
    DEMO_GITHUB_REPO: HttpUrl | None = None
    DEMO_GITHUB_TOKEN: SecretStr | None = None
    DEVELOP_WORKSPACE_ROOT: Path = Path("/tmp/sdd-develop-workspaces")
    DEVELOP_SETUP_TIMEOUT_SECONDS: int = Field(default=300, ge=1, le=3600)
    DEVELOP_FAKE_SETUP_RUNNER: bool = False
    DEVELOP_AGENT_TIMEOUT_SECONDS: int = Field(default=600, ge=1, le=3600)
    DEVELOP_AGENT_TERMINATION_GRACE_SECONDS: float = Field(default=1, gt=0, le=30)
    DEVELOP_TURN_TIMEOUT_SECONDS: int = Field(default=600, ge=1, le=3600)
    DEVELOP_TURN_PRESENCE_GRACE_SECONDS: float = Field(default=10, ge=0, le=300)
    DEVELOP_TURN_REPLAY_LIMIT: int = Field(default=200, ge=1, le=1000)
    DEVELOP_SSE_HEARTBEAT_SECONDS: float = Field(default=15, gt=0, le=60)
    DEVELOP_USER_CONCURRENT_TURN_LIMIT_DEFAULT: int = Field(default=2, ge=1, le=20)
    DEVELOP_AGENT_MAX_ACTIVITY_PARTS: int = Field(default=100, ge=1, le=1000)
    DEVELOP_AGENT_MAX_PART_CHARACTERS: int = Field(default=2000, ge=1, le=10000)
    DEVELOP_AGENT_MAX_RESPONSE_CHARACTERS: int = Field(
        default=100_000, ge=1, le=100_000
    )
    DEVELOP_AGENT_MAX_CONVERSATION_CHARACTERS: int = Field(
        default=100_000, ge=1, le=500_000
    )
    DEVELOP_APPLY_TURN_WEIGHT: int = Field(default=2, ge=1, le=20)
    DEVELOP_AGENT_MODEL: str = "openai/gpt-5.4-mini"
    OPENAI_API_KEY: SecretStr | None = None
    OPENAI_BASE_URL: HttpUrl | None = None
    DEVELOP_ACCEPTANCE_MODE: bool = False
    SECRET_KEY: str
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    FRONTEND_HOST: str = "http://localhost:5173"
    FASTAPI_ENV: Literal["development"] | None = None

    PROJECT_NAME: str
    SENTRY_DSN: HttpUrl | None = None
    DATABASE_URL: PostgresDsn

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _use_psycopg_driver(cls, value: str | PostgresDsn) -> str:
        database_url = str(value)
        for scheme in ("postgres://", "postgresql://"):
            if database_url.startswith(scheme):
                return database_url.replace(scheme, "postgresql+psycopg://", 1)
        return database_url

    @field_validator("DEMO_GITHUB_REPO")
    @classmethod
    def _require_tokenless_repository_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and (value.username or value.password):
            raise ValueError("Repository URL must not contain credentials")
        return value

    @field_validator("DEVELOP_WORKSPACE_ROOT")
    @classmethod
    def _require_absolute_workspace_root(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("Development workspace root must be absolute")
        return value

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.FASTAPI_ENV == "development":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        for host in self.DATABASE_URL.hosts():
            self._check_default_secret("DATABASE_URL password", host["password"])
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        develop_configuration = {
            "DEMO_GITHUB_REPO": self.DEMO_GITHUB_REPO,
            "DEMO_GITHUB_TOKEN": self.DEMO_GITHUB_TOKEN,
            "OPENAI_API_KEY": self.OPENAI_API_KEY,
        }
        configured_develop_values = {
            name for name, value in develop_configuration.items() if value is not None
        }
        if (
            self.FASTAPI_ENV != "development"
            and configured_develop_values
            and len(configured_develop_values) != len(develop_configuration)
        ):
            missing_values = sorted(
                set(develop_configuration) - configured_develop_values
            )
            raise ValueError(
                "Production Develop configuration is incomplete; configure "
                + ", ".join(missing_values)
            )

        if self.DEVELOP_ACCEPTANCE_MODE:
            if not self.DEVELOP_FAKE_SETUP_RUNNER:
                raise ValueError("Acceptance mode requires the fake setup runner")
            if self.OPENAI_BASE_URL is None or self.OPENAI_BASE_URL.host not in {
                "127.0.0.1",
                "localhost",
            }:
                raise ValueError(
                    "Acceptance mode requires a loopback OpenAI provider endpoint"
                )

        return self


settings = Settings()  # type: ignore # ty: ignore[unused-ignore-comment]

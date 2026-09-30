import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import EmailStr, field_validator
from sqlalchemy import JSON, Column, DateTime, Index, String
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


class PresenceMode(StrEnum):
    stop_when_i_leave = "stop_when_i_leave"
    continue_in_background = "continue_in_background"


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)
    concurrent_agent_turn_limit: int = Field(default=2, ge=1, le=20)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    concurrent_agent_turn_limit: int | None = Field(default=None, ge=1, le=20)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    items: list[Item] = Relationship(back_populates="owner", cascade_delete=True)
    development_chats: list[DevelopmentChat] = Relationship(
        back_populates="owner", cascade_delete=True
    )


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


class UsersBulkDelete(SQLModel):
    user_ids: list[uuid.UUID] = Field(min_length=1)


# Shared properties
class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


class DevelopmentChatBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title must not be blank")
        return value


class DevelopmentChatCreate(SQLModel):
    content: str = Field(min_length=1, max_length=100_000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Content must not be blank")
        return value


class DevelopmentChatUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    presence_mode: PresenceMode | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Title must not be blank")
        return value


class DevelopmentMessageCreate(SQLModel):
    content: str = Field(min_length=1, max_length=100_000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Content must not be blank")
        return value


class DevelopmentChat(DevelopmentChatBase, table=True):
    __table_args__ = (
        Index("ix_developmentchat_owner_updated_id", "owner_id", "updated_at", "id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    workspace_ready: bool = Field(default=False, nullable=False)
    agent_session_id: str | None = Field(default=None, max_length=255)
    presence_mode: PresenceMode = Field(
        default=PresenceMode.stop_when_i_leave,
        sa_column=Column(String(32), nullable=False),
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    owner: User | None = Relationship(back_populates="development_chats")
    messages: list[DevelopmentMessage] = Relationship(
        back_populates="chat", cascade_delete=True
    )


class DevelopmentChatPublic(DevelopmentChatBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    workspace_ready: bool
    presence_mode: PresenceMode
    created_at: datetime
    updated_at: datetime


class DevelopmentWorkspacePublic(SQLModel):
    ready: bool
    setup_available: bool


class DevelopmentChatsPublic(SQLModel):
    data: list[DevelopmentChatPublic]
    count: int


class DevelopmentMessageRole(StrEnum):
    user = "user"
    assistant = "assistant"


class DevelopmentMessageBase(SQLModel):
    role: DevelopmentMessageRole
    content: str = Field(min_length=1, max_length=100_000)
    activity: list[dict[str, str]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Content must not be blank")
        return value


class DevelopmentMessage(DevelopmentMessageBase, table=True):
    __table_args__ = (
        Index("ix_developmentmessage_chat_created_id", "chat_id", "created_at", "id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    chat_id: uuid.UUID = Field(
        foreign_key="developmentchat.id", nullable=False, ondelete="CASCADE"
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    chat: DevelopmentChat | None = Relationship(back_populates="messages")


class DevelopmentMessagePublic(DevelopmentMessageBase):
    id: uuid.UUID
    chat_id: uuid.UUID
    created_at: datetime


class DevelopmentMessagesPublic(SQLModel):
    data: list[DevelopmentMessagePublic]
    has_more: bool
    next_cursor: str | None = None


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)

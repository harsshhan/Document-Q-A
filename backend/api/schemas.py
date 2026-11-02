"""Pydantic request/response schemas (the public API contract)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from db.models import DocumentStatus

USERNAME_PATTERN = r"^[A-Za-z0-9_.-]{3,64}$"


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=3, max_length=64, pattern=USERNAME_PATTERN)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserPublic(BaseModel):
    """User representation returned to clients (never includes a hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    username: str
    email: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


class DocumentPublic(BaseModel):
    """Document metadata returned to its owner."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    status: DocumentStatus
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentStatusResponse(BaseModel):
    document_id: uuid.UUID
    status: DocumentStatus
    error_message: str | None = None


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=3, ge=1)


class SourceReference(BaseModel):
    document_id: uuid.UUID
    chunk_index: int
    content: str
    score: float


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceReference]
    no_match: bool

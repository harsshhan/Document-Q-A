"""User lookup helpers (used by authentication and ingestion)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User


async def get_user_by_id(
    session: AsyncSession, user_id: uuid.UUID
) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_username(
    session: AsyncSession, username: str
) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()

"""Async SQLAlchemy engine, session factory and FastAPI dependency.

The engine is created from ``DATABASE_URL`` (see ``core.config``). Nothing here
connects eagerly, so importing this module never requires a running database.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from core.config import get_settings

_settings = get_settings()

# NullPool keeps connections tied to the event loop that created them. This is
# safe (and simple) for a small service and avoids cross-loop reuse in tests.
engine = create_async_engine(
    _settings.database_url,
    echo=_settings.database_echo,
    poolclass=NullPool,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a request-scoped session."""

    async with AsyncSessionLocal() as session:
        yield session

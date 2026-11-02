"""Integration test for the idempotent demo-user seed script.

Requires ``TEST_DATABASE_URL``. The demo user is removed afterwards so the
suite leaves the database as it found it.
"""

import asyncio
import os

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from db.models import User
from scripts import seed_demo_user

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not configured"
    ),
]


async def _count_demo_users() -> int:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(func.count())
            .select_from(User)
            .where(User.username == seed_demo_user.DEMO_USERNAME)
        )
        count = result.scalar_one()
    await engine.dispose()
    return count


async def _delete_demo_user() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(
            delete(User).where(User.username == seed_demo_user.DEMO_USERNAME)
        )
    await engine.dispose()


@pytest.fixture
def clean_demo_user():
    asyncio.run(_delete_demo_user())
    yield
    asyncio.run(_delete_demo_user())


def test_seed_creates_demo_user_once(clean_demo_user):
    asyncio.run(seed_demo_user.seed_demo_user())
    assert asyncio.run(_count_demo_users()) == 1

    # Running again must not create a duplicate or raise.
    asyncio.run(seed_demo_user.seed_demo_user())
    assert asyncio.run(_count_demo_users()) == 1

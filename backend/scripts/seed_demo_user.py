"""Create the demo user idempotently.

Run explicitly, never on application startup::

    python -m scripts.seed_demo_user

The script is safe to run repeatedly. If the demo user already exists it is
left untouched. The password is hashed with Argon2 and only the username, email
and UUID are printed -- never the plaintext password or its hash.
"""

import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

# Allow "python -m scripts.seed_demo_user" and direct execution.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.exc import IntegrityError  # noqa: E402

from core.security import hash_password  # noqa: E402
from db.models import User  # noqa: E402
from db.session import AsyncSessionLocal  # noqa: E402
from services.users import get_user_by_email, get_user_by_username  # noqa: E402

DEMO_NAME = "Demo User"
DEMO_USERNAME = "demo"
DEMO_EMAIL = "demo@example.com"
DEMO_DEFAULT_PASSWORD = "DemoPass123!"

PRODUCTION_WARNING = (
    "WARNING: the demo account uses a well-known password and must NEVER be "
    "used in production."
)


async def seed_demo_user() -> None:
    password = os.environ.get("DEMO_USER_PASSWORD") or DEMO_DEFAULT_PASSWORD

    async with AsyncSessionLocal() as session:
        existing = await get_user_by_username(session, DEMO_USERNAME)
        if existing is None:
            existing = await get_user_by_email(session, DEMO_EMAIL)

        if existing is not None:
            print("Demo user already exists; nothing to do.")
            print(f"  username: {existing.username}")
            print(f"  email:    {existing.email}")
            print(f"  id:       {existing.id}")
            print(PRODUCTION_WARNING)
            return

        user = User(
            id=uuid.uuid4(),
            name=DEMO_NAME,
            username=DEMO_USERNAME,
            email=DEMO_EMAIL,
            password_hash=hash_password(password),
        )
        session.add(user)

        try:
            await session.commit()
        except IntegrityError:
            # Another process created the same user concurrently.
            await session.rollback()
            print("Demo user already exists; nothing to do.")
            return

        print("Created demo user.")
        print(f"  username: {user.username}")
        print(f"  email:    {user.email}")
        print(f"  id:       {user.id}")
        print(PRODUCTION_WARNING)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed_demo_user())


if __name__ == "__main__":
    main()

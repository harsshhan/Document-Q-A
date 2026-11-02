"""SQLAlchemy declarative base.

All ORM models inherit from :class:`Base` so a single metadata object is shared
with Alembic.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""

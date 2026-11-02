"""Integration tests for pgvector retrieval against a real PostgreSQL instance.

These are opt-in: they run only when ``TEST_DATABASE_URL`` points at a database
that already has the migrations applied (see README).

    TEST_DATABASE_URL=postgresql+asyncpg://user@localhost:5432/document_qa_test \
        pytest -m integration
"""

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import get_settings
from db.models import Document, DocumentChunk, DocumentStatus, User
from services.retrieval import search_similar_chunks

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not configured"
    ),
]

DIM = get_settings().embedding_dimension


def _unit_vector(index: int) -> list[float]:
    values = [0.0] * DIM
    values[index] = 1.0
    return values


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with factory() as db_session:
        yield db_session

    await engine.dispose()


@pytest.fixture
async def seeded(session):
    """Two users, each with their own document and chunks."""

    suffix = uuid.uuid4().hex[:8]
    e1 = _unit_vector(0)
    e2 = _unit_vector(1)

    user_a = User(
        name="User A",
        username=f"user_a_{suffix}",
        email=f"a_{suffix}@example.com",
        password_hash="not-a-real-hash",
    )
    user_b = User(
        name="User B",
        username=f"user_b_{suffix}",
        email=f"b_{suffix}@example.com",
        password_hash="not-a-real-hash",
    )
    session.add_all([user_a, user_b])
    await session.flush()

    doc_a = Document(
        user_id=user_a.id, filename="a.pdf", status=DocumentStatus.COMPLETED
    )
    doc_b = Document(
        user_id=user_b.id, filename="b.pdf", status=DocumentStatus.COMPLETED
    )
    session.add_all([doc_a, doc_b])
    await session.flush()

    session.add_all(
        [
            DocumentChunk(
                document_id=doc_a.id,
                user_id=user_a.id,
                chunk_index=0,
                content="alpha",
                embedding=e1,
            ),
            DocumentChunk(
                document_id=doc_a.id,
                user_id=user_a.id,
                chunk_index=1,
                content="beta",
                embedding=e2,
            ),
            DocumentChunk(
                document_id=doc_b.id,
                user_id=user_b.id,
                chunk_index=0,
                content="gamma",
                embedding=e1,
            ),
        ]
    )
    await session.commit()

    yield {"user_a": user_a.id, "user_b": user_b.id, "query": e1}

    for user_id in (user_a.id, user_b.id):
        user = await session.get(User, user_id)
        if user is not None:
            await session.delete(user)
    await session.commit()


async def test_nearest_chunk_is_returned_first(session, seeded):
    results = await search_similar_chunks(
        session,
        user_id=seeded["user_a"],
        query_embedding=seeded["query"],
        top_k=3,
    )

    assert [hit.content for hit in results][0] == "alpha"
    assert results[0].score == pytest.approx(1.0, abs=1e-6)


async def test_other_users_chunks_are_never_returned(session, seeded):
    results = await search_similar_chunks(
        session,
        user_id=seeded["user_a"],
        query_embedding=seeded["query"],
        top_k=10,
    )

    contents = [hit.content for hit in results]
    assert "gamma" not in contents  # belongs to user B
    assert sorted(contents) == ["alpha", "beta"]


async def test_top_k_limits_the_result_set(session, seeded):
    results = await search_similar_chunks(
        session,
        user_id=seeded["user_a"],
        query_embedding=seeded["query"],
        top_k=1,
    )

    assert len(results) == 1
    assert results[0].content == "alpha"


async def test_scores_decrease_with_distance(session, seeded):
    results = await search_similar_chunks(
        session,
        user_id=seeded["user_a"],
        query_embedding=seeded["query"],
        top_k=3,
    )

    scores = [hit.score for hit in results]
    assert scores == sorted(scores, reverse=True)

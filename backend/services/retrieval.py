"""Vector retrieval against PostgreSQL/pgvector.

All similarity search lives here rather than in the API routes, and every query
is scoped by ``user_id`` so a user can only ever retrieve their own chunks.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DocumentChunk

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RetrievedChunk:
    """A single search hit with its cosine similarity score (0..1)."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    content: str
    score: float


async def search_similar_chunks(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    query_embedding: list[float],
    top_k: int,
) -> list[RetrievedChunk]:
    """Return the ``top_k`` chunks closest to ``query_embedding``.

    Uses pgvector's cosine distance operator (``<=>``); the similarity score is
    ``1 - cosine_distance`` so higher is better. Results are filtered by the
    owner's ``user_id`` and ordered by increasing distance.

    Exact (sequential) search is used on purpose: the dataset is small, so an
    approximate index such as ivfflat/HNSW would add complexity and require a
    training step without a measurable benefit.
    """

    distance = DocumentChunk.embedding.cosine_distance(query_embedding)

    statement = (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            DocumentChunk.content,
            distance.label("distance"),
        )
        .where(DocumentChunk.user_id == user_id)
        .order_by(distance)
        .limit(top_k)
    )

    result = await session.execute(statement)

    chunks = [
        RetrievedChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            chunk_index=row.chunk_index,
            content=row.content,
            score=max(0.0, min(1.0, 1.0 - float(row.distance))),
        )
        for row in result.all()
    ]

    logger.info(
        "Vector search returned %d chunk(s) for user %s", len(chunks), user_id
    )
    return chunks

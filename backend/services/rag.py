"""Retrieval-augmented answering.

Pipeline: embed the query (same model/dimension as ingestion) -> cosine search
in pgvector scoped to the authenticated user -> generate an answer strictly from
the retrieved chunks.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from services.embedding import generate_query_embedding
from services.llm import NO_ANSWER_SENTENCE, generate_answer
from services.retrieval import RetrievedChunk, search_similar_chunks

logger = logging.getLogger(__name__)

# Returned when nothing relevant was retrieved, so the model is never asked to
# invent an answer.
SAFE_NO_MATCH_ANSWER = NO_ANSWER_SENTENCE


class RagServiceError(Exception):
    """Raised when the answering pipeline cannot complete."""


@dataclass(slots=True)
class RagResult:
    answer: str
    sources: list[RetrievedChunk]
    no_match: bool


def build_context(hits: list[RetrievedChunk]) -> str:
    """Render retrieved chunks with document references the model can cite."""

    return "\n\n".join(
        f"[{index}] (document {hit.document_id}, chunk {hit.chunk_index})\n{hit.content}"
        for index, hit in enumerate(hits, start=1)
    )


async def answer_question(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    query: str,
    top_k: int,
) -> RagResult:
    settings = get_settings()
    limit = max(1, min(top_k, settings.rag_max_top_k))

    query_embedding = await generate_query_embedding(query)

    hits = await search_similar_chunks(
        session,
        user_id=user_id,
        query_embedding=query_embedding,
        top_k=limit,
    )

    relevant = [hit for hit in hits if hit.score >= settings.rag_min_similarity]

    if not relevant:
        logger.info(
            "No relevant context for user %s (best score: %s)",
            user_id,
            hits[0].score if hits else None,
        )
        return RagResult(answer=SAFE_NO_MATCH_ANSWER, sources=[], no_match=True)

    answer = await generate_answer(build_context(relevant), query)

    # The model is instructed to return this sentence when the context does not
    # answer the question; surface that as an explicit no-match.
    no_match = answer.strip() == NO_ANSWER_SENTENCE

    return RagResult(answer=answer, sources=relevant, no_match=no_match)

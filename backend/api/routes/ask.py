"""Retrieval-augmented question answering route."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from api.schemas import AskRequest, AskResponse, SourceReference
from db.models import User
from db.session import get_session
from services.embedding import EmbeddingError
from services.llm import LLMError
from services.rag import answer_question

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rag"])


@router.post("/ask", response_model=AskResponse, summary="Ask a question about your documents")
async def ask(
    payload: AskRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AskResponse:
    try:
        result = await answer_question(
            session,
            user_id=current_user.id,
            query=payload.query,
            top_k=payload.top_k,
        )
    except EmbeddingError as exc:
        logger.warning("Query embedding failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The embedding service is unavailable.",
        ) from exc
    except LLMError as exc:
        logger.warning("Answer generation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The answer generation service is unavailable.",
        ) from exc

    return AskResponse(
        answer=result.answer,
        no_match=result.no_match,
        sources=[
            SourceReference(
                document_id=hit.document_id,
                chunk_index=hit.chunk_index,
                content=hit.content,
                score=hit.score,
            )
            for hit in result.sources
        ],
    )

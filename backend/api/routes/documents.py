"""Document upload, listing, status and download routes."""

import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from api.schemas import DocumentPublic, DocumentStatusResponse
from core.config import get_settings
from db.models import Document, User
from db.session import get_session
from services import s3_storage
from services.documents import IngestionError, ingest_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}


def _looks_like_pdf(file: UploadFile) -> bool:
    if (file.filename or "").lower().endswith(".pdf"):
        return True
    return (file.content_type or "").lower() in PDF_CONTENT_TYPES


@router.post(
    "",
    response_model=DocumentPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a PDF and ingest it",
)
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Document:
    settings = get_settings()

    if not _looks_like_pdf(file):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are supported.",
        )

    content = await file.read()

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty.",
        )

    if len(content) > settings.max_upload_size_bytes:
        limit_mb = settings.max_upload_size_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {limit_mb} MB upload limit.",
        )

    try:
        return await ingest_pdf(
            session,
            user_id=current_user.id,
            filename=file.filename or "document.pdf",
            content=content,
        )
    except IngestionError as exc:
        # The document row is already stored as FAILED; the client gets only the
        # safe message.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except s3_storage.S3ConfigurationError as exc:
        # Storage is unusable, so nothing was ingested and nothing was stored.
        logger.error("S3 is not configured: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document storage is not configured.",
        ) from exc


@router.get("", response_model=list[DocumentPublic], summary="List your documents")
async def list_documents(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Document]:
    result = await session.execute(
        select(Document)
        .where(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    summary="Get the ingestion status of one document",
)
async def document_status(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DocumentStatusResponse:
    result = await session.execute(
        select(Document).where(
            Document.id == document_id, Document.user_id == current_user.id
        )
    )
    document = result.scalar_one_or_none()

    # "Unknown id" and "belongs to another user" both return 404, so the API
    # never reveals that someone else's document exists.
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found."
        )

    return DocumentStatusResponse(
        document_id=document.id,
        status=document.status,
        error_message=document.error_message,
    )


@router.get(
    "/{document_id}/download",
    summary="Redirect to a short-lived URL for the original PDF",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
)
async def download_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Send the owner to a short-lived presigned URL for their stored PDF.

    The bucket stays private: the response never contains AWS credentials and
    the URL expires, so it cannot be reused as a permanent public link.
    """

    result = await session.execute(
        select(Document).where(
            Document.id == document_id, Document.user_id == current_user.id
        )
    )
    document = result.scalar_one_or_none()

    # Unknown id, another user's document, and a document with nothing stored
    # are all reported identically.
    if document is None or not document.s3_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found."
        )

    try:
        url, _ = await s3_storage.presigned_download_url(document.s3_key)
    except s3_storage.S3ConfigurationError as exc:
        logger.error("S3 is not configured: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document storage is not configured.",
        ) from exc
    except s3_storage.S3StorageError as exc:
        logger.warning("Could not build a download URL for document %s: %s", document_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The stored file could not be retrieved.",
        ) from exc

    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

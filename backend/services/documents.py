"""Document ingestion: PDF bytes -> S3 -> text -> chunks -> Gemini embeddings -> PostgreSQL.

The original PDF is stored privately in S3; only its metadata, chunks and
embeddings live in PostgreSQL.

The work is synchronous (the API waits for it) but kept in this module so it can
be moved behind a background worker later without touching the routes.

S3 and PostgreSQL do not share a distributed transaction, so the object is
written first and removed again on a best-effort basis if a later step fails.
Cleanup never replaces or hides the original error.
"""

import logging
import uuid
from io import BytesIO

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Document, DocumentChunk, DocumentStatus
from services import s3_storage
from services.chunking import chunk_text
from services.embedding import EmbeddingError, generate_embeddings
from services.pdf_loader import extract_text

logger = logging.getLogger(__name__)

# Shown to clients and stored on the document: never contains paths or
# exception details from the internals.
SAFE_FAILURE_MESSAGE = "The document could not be processed."


class IngestionError(Exception):
    """Raised when a document cannot be ingested. The message is client-safe."""


async def _mark_failed(
    session: AsyncSession,
    document: Document,
    message: str,
    *,
    clear_s3_key: bool = False,
) -> None:
    """Record a terminal FAILED state with a safe, human-readable message.

    ``clear_s3_key`` is set when the stored object no longer exists, so the row
    never points at a key that was deleted.
    """

    try:
        await session.rollback()
        document.status = DocumentStatus.FAILED
        document.error_message = message
        if clear_s3_key:
            document.s3_key = None
        await session.commit()
    except Exception:
        logger.exception("Could not mark document as FAILED in the database")


async def _delete_orphaned_object(object_key: str, document_id: uuid.UUID) -> bool:
    """Best-effort removal of an object whose ingestion did not complete.

    Returns ``True`` once the object is gone. This helper never raises: a failed
    delete is logged and reported so it can never mask the error that caused the
    cleanup in the first place.
    """

    try:
        await s3_storage.delete_pdf(object_key)
    except Exception as exc:
        logger.warning(
            "Could not delete the orphaned S3 object for document %s (%s)",
            document_id,
            type(exc).__name__,
        )
        return False

    return True


async def _fail_ingestion(
    session: AsyncSession,
    document: Document,
    object_key: str,
    message: str,
) -> None:
    """Mark the document FAILED and drop its now-orphaned S3 object."""

    removed = await _delete_orphaned_object(object_key, document.id)
    await _mark_failed(session, document, message, clear_s3_key=removed)


async def ingest_pdf(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    filename: str,
    content: bytes,
) -> Document:
    """Ingest a PDF on behalf of ``user_id`` and return the document row.

    Raises :class:`IngestionError` on any failure, after leaving the document in
    the ``FAILED`` state. Raises ``S3ConfigurationError`` (mapped to ``503`` by
    the route) when S3 is unusable, before anything is written.
    """

    # The id is generated here rather than by the database because the S3 object
    # key is derived from it and must exist before the row does.
    document_id = uuid.uuid4()

    # No I/O: an unusable bucket is reported before any row is written.
    s3_storage.ensure_configured()
    object_key = s3_storage.build_object_key(
        user_id=user_id, document_id=document_id
    )

    # 1. The original bytes go to private storage first. If this fails the client
    #    is told the upload failed - nothing is reported as successful.
    try:
        await s3_storage.upload_pdf(object_key, content)
    except s3_storage.S3ConfigurationError:
        raise
    except s3_storage.S3StorageError as exc:
        # The message carries the operation and the AWS error code only.
        logger.warning("S3 upload failed for document %s: %s", document_id, exc)
        raise IngestionError(SAFE_FAILURE_MESSAGE) from exc

    # 2. Only then is the row created, carrying the user id and the object key.
    document = Document(
        id=document_id,
        user_id=user_id,
        filename=filename,
        s3_key=object_key,
        status=DocumentStatus.PROCESSING,
    )

    try:
        session.add(document)
        await session.commit()
        await session.refresh(document)
    except Exception:
        logger.exception("Could not create the document row for %s", document_id)
        # The bytes are stored but nothing references them: remove them again.
        await _delete_orphaned_object(object_key, document_id)
        raise

    try:
        text = extract_text(BytesIO(content))
        chunks = chunk_text(text)

        if not chunks:
            raise IngestionError("No readable text was found in the PDF.")

        embeddings = await generate_embeddings(chunks)

        if len(embeddings) != len(chunks):
            raise IngestionError(SAFE_FAILURE_MESSAGE)

    except IngestionError as exc:
        await _fail_ingestion(session, document, object_key, str(exc))
        raise
    except EmbeddingError as exc:
        logger.warning("Embedding failed for document %s: %s", document_id, exc)
        await _fail_ingestion(session, document, object_key, SAFE_FAILURE_MESSAGE)
        raise IngestionError(SAFE_FAILURE_MESSAGE) from exc
    except Exception as exc:
        logger.exception("Unexpected ingestion failure for document %s", document_id)
        await _fail_ingestion(session, document, object_key, SAFE_FAILURE_MESSAGE)
        raise IngestionError(SAFE_FAILURE_MESSAGE) from exc

    # Chunks and the COMPLETED status are committed together: a document is
    # never marked COMPLETED before its chunks exist.
    try:
        session.add_all(
            [
                DocumentChunk(
                    document_id=document_id,
                    user_id=user_id,
                    chunk_index=index,
                    content=chunk,
                    embedding=embedding,
                )
                for index, (chunk, embedding) in enumerate(zip(chunks, embeddings))
            ]
        )
        document.status = DocumentStatus.COMPLETED
        document.error_message = None
        await session.commit()
    except Exception as exc:
        logger.exception("Failed to persist chunks for document %s", document_id)
        await _fail_ingestion(session, document, object_key, SAFE_FAILURE_MESSAGE)
        raise IngestionError(SAFE_FAILURE_MESSAGE) from exc

    await session.refresh(document)
    logger.info(
        "Ingested document %s with %d chunk(s) for user %s",
        document_id,
        len(chunks),
        user_id,
    )
    return document

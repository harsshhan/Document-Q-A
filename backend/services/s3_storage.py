"""Private Amazon S3 storage for the original uploaded PDF.

Only the original PDF bytes are stored in S3. Users, document metadata, the
extracted text chunks and their embeddings all stay in PostgreSQL - embeddings
are never written to S3.

The module owns exactly one concern: moving bytes to and from the configured
bucket. The boto3 client is built by ``_create_client`` so tests can patch that
single seam and exercise every path without the network, real credentials, or
an AWS account.

Objects are always private: no ACL is ever set, and the only way bytes are
handed out is through a short-lived presigned URL.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError

from core.config import get_settings

logger = logging.getLogger(__name__)

PDF_CONTENT_TYPE = "application/pdf"

# Presigned download URLs are deliberately short-lived, so a leaked URL is
# useless quickly and the object itself never becomes public.
PRESIGNED_URL_EXPIRES_SECONDS = 300

T = TypeVar("T")


class S3StorageError(RuntimeError):
    """Raised when an S3 operation fails. The message is safe to log."""


class S3ConfigurationError(S3StorageError):
    """Raised when S3 is in use but the bucket or region is not configured."""


def _clean(value: str | None) -> str | None:
    """Treat a blank configured value as "not set".

    ``.env`` entries such as ``AWS_ACCESS_KEY_ID=`` arrive as empty strings, and
    an empty credential would otherwise be handed to boto3 as if it were real.
    """

    if value and value.strip():
        return value.strip()
    return None


def _bucket_and_region() -> tuple[str, str]:
    """Return the configured bucket and region, or raise a safe config error."""

    settings = get_settings()
    bucket = _clean(settings.s3_bucket_name)
    region = _clean(settings.aws_region)

    if not bucket:
        raise S3ConfigurationError(
            "S3_BUCKET_NAME is not configured; document storage is unavailable."
        )
    if not region:
        raise S3ConfigurationError(
            "AWS_REGION is not configured; document storage is unavailable."
        )

    return bucket, region


def _static_credentials() -> tuple[str | None, str | None]:
    """Return explicitly configured credentials, or ``(None, None)``.

    Half a pair is a configuration mistake worth failing on: passing only one
    would break signing in a way that is hard to diagnose.
    """

    settings = get_settings()
    access_key = _clean(settings.aws_access_key_id)
    secret_key = _clean(settings.aws_secret_access_key)

    if (access_key is None) != (secret_key is None):
        raise S3ConfigurationError(
            "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set together. "
            "Leave both empty to use the standard AWS credential chain."
        )

    return access_key, secret_key


def ensure_configured() -> None:
    """Verify that S3 can be used, without performing any I/O.

    Called before a document row is created so a configuration problem fails
    the request cleanly instead of leaving a half-ingested document behind.
    """

    _bucket_and_region()


def build_object_key(*, user_id: uuid.UUID, document_id: uuid.UUID) -> str:
    """Return the deterministic object key for a document's original PDF.

    The key is derived entirely from server-side identifiers. The uploaded
    filename is never part of it, so a client cannot influence the storage
    path - it is kept only as ``documents.filename`` for display.
    """

    return f"users/{user_id}/documents/{document_id}/original.pdf"


def _create_client() -> BaseClient:
    """Build the boto3 S3 client. Patched in tests with a fake.

    Static credentials are passed only when both are configured. Otherwise the
    arguments stay ``None`` and boto3 resolves credentials through its normal
    provider chain (environment, shared config file, container or instance
    role), which is what allows an IAM role in production.
    """

    _, region = _bucket_and_region()
    access_key, secret_key = _static_credentials()

    session = boto3.session.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )
    return session.client("s3", region_name=region)


def _error_code(exc: ClientError) -> str:
    """Return the AWS error code for logging - never the full response."""

    error = exc.response.get("Error") if isinstance(exc.response, dict) else None
    code = (error or {}).get("Code") if isinstance(error, dict) else None
    return str(code) if code else "UnknownError"


def _call(operation: str, key: str, action: Callable[[], T]) -> T:
    """Run ``action``, translating boto3 failures into :class:`S3StorageError`.

    The message carries only the operation and the AWS error code. Credentials,
    request bodies and the raw AWS response are never included, and the object
    key is only ever written to the log.
    """

    try:
        return action()
    except ClientError as exc:
        code = _error_code(exc)
        logger.warning("S3 %s failed for key %s (code=%s)", operation, key, code)
        raise S3StorageError(f"S3 {operation} failed ({code}).") from exc
    except BotoCoreError as exc:
        name = type(exc).__name__
        logger.warning("S3 %s failed for key %s (%s)", operation, key, name)
        raise S3StorageError(f"S3 {operation} failed ({name}).") from exc


def _put_object(key: str, content: bytes) -> None:
    bucket, _ = _bucket_and_region()
    client = _create_client()
    _call(
        "PutObject",
        key,
        lambda: client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType=PDF_CONTENT_TYPE,
            # No ACL argument on purpose: the object inherits the bucket's
            # private default and is never made public.
        ),
    )


def _get_object(key: str) -> bytes:
    bucket, _ = _bucket_and_region()
    client = _create_client()

    def _read() -> bytes:
        body: Any = client.get_object(Bucket=bucket, Key=key)["Body"]
        return body.read()

    return _call("GetObject", key, _read)


def _delete_object(key: str) -> None:
    bucket, _ = _bucket_and_region()
    client = _create_client()
    # S3 returns success for a key that does not exist, which makes deletion
    # naturally idempotent for best-effort cleanup.
    _call("DeleteObject", key, lambda: client.delete_object(Bucket=bucket, Key=key))


def _presign_url(key: str, expires_in: int) -> str:
    bucket, _ = _bucket_and_region()
    client = _create_client()
    return _call(
        "GeneratePresignedUrl",
        key,
        lambda: client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        ),
    )


# --------------------------------------------------------------------------- #
# Async API used by the routes.
#
# boto3 is synchronous, so every call is handed to a worker thread with
# asyncio.to_thread rather than blocking the event loop.
# --------------------------------------------------------------------------- #


async def upload_pdf(key: str, content: bytes) -> None:
    """Store the original PDF bytes privately under ``key``."""

    await asyncio.to_thread(_put_object, key, content)


async def download_pdf(key: str) -> bytes:
    """Return the stored PDF bytes for ``key``."""

    return await asyncio.to_thread(_get_object, key)


async def delete_pdf(key: str) -> None:
    """Delete the object at ``key``. Idempotent for missing keys."""

    await asyncio.to_thread(_delete_object, key)


async def presigned_download_url(
    key: str, *, expires_in: int = PRESIGNED_URL_EXPIRES_SECONDS
) -> tuple[str, int]:
    """Return a short-lived presigned GET URL for ``key`` and its lifetime."""

    url = await asyncio.to_thread(_presign_url, key, expires_in)
    return url, expires_in

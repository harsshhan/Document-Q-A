"""Unit tests for the private S3 storage service.

Every test runs against the in-memory fake client installed by the autouse
``fake_s3`` fixture in ``conftest.py``, so nothing here needs AWS credentials,
a bucket, or a network connection.
"""

import uuid

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from core.config import Settings, get_settings, validate_startup_settings
from services import s3_storage


@pytest.fixture
def ids():
    return uuid.uuid4(), uuid.uuid4()


class _FailingClient:
    """Client whose every call fails, to exercise the error mapping."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def _fail(self, *args, **kwargs):
        raise self._exc

    put_object = _fail
    delete_object = _fail

    def get_object(self, *args, **kwargs):
        raise self._exc

    def generate_presigned_url(self, *args, **kwargs):
        raise self._exc


def _client_error(code: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "denied"}, "ResponseMetadata": {}},
        "PutObject",
    )


# --------------------------------------------------------------------------- #
# Key construction
# --------------------------------------------------------------------------- #


def test_build_object_key_is_deterministic_and_server_side(ids):
    user_id, document_id = ids

    key = s3_storage.build_object_key(user_id=user_id, document_id=document_id)

    assert key == f"users/{user_id}/documents/{document_id}/original.pdf"
    # The same inputs always map to the same object.
    assert key == s3_storage.build_object_key(
        user_id=user_id, document_id=document_id
    )


def test_object_key_never_contains_the_uploaded_filename(ids):
    user_id, document_id = ids

    key = s3_storage.build_object_key(user_id=user_id, document_id=document_id)

    assert ".." not in key
    assert key.endswith("original.pdf")


# --------------------------------------------------------------------------- #
# Round trip through the fake bucket
# --------------------------------------------------------------------------- #


async def test_upload_stores_the_bytes_privately(fake_s3, ids):
    user_id, document_id = ids
    key = s3_storage.build_object_key(user_id=user_id, document_id=document_id)
    content = b"%PDF-1.4 original bytes"

    await s3_storage.upload_pdf(key, content)

    stored = fake_s3.objects[(get_settings().s3_bucket_name, key)]
    assert stored == content
    # No ACL argument is ever sent, so the object keeps the bucket's private
    # default instead of being made public.
    assert fake_s3.acl_arguments == []


async def test_upload_then_download_round_trips(fake_s3):
    content = b"%PDF-1.4 round trip"

    await s3_storage.upload_pdf("users/u/documents/d/original.pdf", content)

    assert await s3_storage.download_pdf("users/u/documents/d/original.pdf") == content


async def test_delete_removes_the_object(fake_s3):
    key = "users/u/documents/d/original.pdf"
    await s3_storage.upload_pdf(key, b"%PDF-1.4")

    await s3_storage.delete_pdf(key)

    assert fake_s3.objects == {}


async def test_delete_is_idempotent(fake_s3):
    # S3 reports success for a missing key, so cleanup can always be re-run.
    await s3_storage.delete_pdf("users/u/documents/d/original.pdf")

    assert fake_s3.objects == {}


async def test_presigned_url_is_short_lived(fake_s3):
    key = "users/u/documents/d/original.pdf"

    url, expires_in = await s3_storage.presigned_download_url(key)

    assert url.startswith("https://")
    assert key in url
    assert expires_in == s3_storage.PRESIGNED_URL_EXPIRES_SECONDS
    assert fake_s3.presigned_requests[0]["expires_in"] == expires_in
    # A presigned request, never a permanent public object URL.
    assert fake_s3.presigned_requests[0]["method"] == "get_object"


# --------------------------------------------------------------------------- #
# Failure handling
# --------------------------------------------------------------------------- #


async def test_client_error_becomes_safe_storage_error(monkeypatch):
    monkeypatch.setattr(
        s3_storage, "_create_client", lambda: _FailingClient(_client_error("AccessDenied"))
    )

    with pytest.raises(s3_storage.S3StorageError) as excinfo:
        await s3_storage.upload_pdf("users/u/documents/d/original.pdf", b"%PDF-1.4")

    message = str(excinfo.value)
    # The AWS error code is useful; credentials and request details are not.
    assert "AccessDenied" in message
    assert "denied" not in message
    assert "unit-test-secret-access-key" not in message


async def test_transport_error_becomes_safe_storage_error(monkeypatch):
    monkeypatch.setattr(
        s3_storage,
        "_create_client",
        lambda: _FailingClient(EndpointConnectionError(endpoint_url="https://s3")),
    )

    with pytest.raises(s3_storage.S3StorageError) as excinfo:
        await s3_storage.delete_pdf("users/u/documents/d/original.pdf")

    assert "EndpointConnectionError" in str(excinfo.value)


async def test_missing_configuration_raises_configuration_error(monkeypatch):
    monkeypatch.setattr(get_settings(), "s3_bucket_name", None)

    with pytest.raises(s3_storage.S3ConfigurationError):
        s3_storage.ensure_configured()

    with pytest.raises(s3_storage.S3ConfigurationError):
        await s3_storage.upload_pdf("users/u/documents/d/original.pdf", b"%PDF-1.4")


async def test_missing_region_raises_configuration_error(monkeypatch):
    monkeypatch.setattr(get_settings(), "aws_region", None)

    with pytest.raises(s3_storage.S3ConfigurationError):
        s3_storage.ensure_configured()


def test_no_static_credentials_means_the_provider_chain_is_used(fake_s3, monkeypatch):
    monkeypatch.setattr(get_settings(), "aws_access_key_id", None)
    monkeypatch.setattr(get_settings(), "aws_secret_access_key", None)

    s3_storage._create_client()

    # With nothing configured the arguments stay None, so boto3 resolves
    # credentials itself (environment, shared config, IAM role).
    assert fake_s3.session_kwargs["aws_access_key_id"] is None
    assert fake_s3.session_kwargs["aws_secret_access_key"] is None
    # The configured region still drives the client.
    assert fake_s3.session_kwargs["region_name"] == get_settings().aws_region


def test_configured_credentials_are_passed_to_the_session(fake_s3):
    s3_storage._create_client()

    assert fake_s3.session_kwargs["aws_access_key_id"] == (
        get_settings().aws_access_key_id
    )
    assert fake_s3.session_kwargs["aws_secret_access_key"] == (
        get_settings().aws_secret_access_key
    )


def test_blank_credentials_are_treated_as_unset(fake_s3, monkeypatch):
    # A copied .env with `AWS_ACCESS_KEY_ID=` must not be sent to boto3 as an
    # empty (and therefore invalid) credential.
    monkeypatch.setattr(get_settings(), "aws_access_key_id", "")
    monkeypatch.setattr(get_settings(), "aws_secret_access_key", "   ")

    s3_storage._create_client()

    assert fake_s3.session_kwargs["aws_access_key_id"] is None
    assert fake_s3.session_kwargs["aws_secret_access_key"] is None


def test_half_configured_credentials_are_rejected(fake_s3, monkeypatch):
    monkeypatch.setattr(get_settings(), "aws_access_key_id", "AKIAEXAMPLE")
    monkeypatch.setattr(get_settings(), "aws_secret_access_key", None)

    with pytest.raises(s3_storage.S3ConfigurationError):
        s3_storage._create_client()

    assert fake_s3.session_kwargs == {}


def test_blank_bucket_name_counts_as_not_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "s3_bucket_name", "  ")

    assert get_settings().s3_enabled is False
    with pytest.raises(s3_storage.S3ConfigurationError):
        s3_storage.ensure_configured()


# --------------------------------------------------------------------------- #
# Ingestion cleanup (unit tests: no database, no Gemini)
# --------------------------------------------------------------------------- #


async def test_database_failure_after_upload_removes_the_object(fake_s3, monkeypatch):
    from services import documents as documents_service

    class _BrokenSession:
        """Session whose first commit fails, as a database outage would."""

        def add(self, _instance) -> None:
            pass

        async def commit(self) -> None:
            raise RuntimeError("database is unavailable")

        async def refresh(self, _instance) -> None:
            pass

    with pytest.raises(RuntimeError, match="database is unavailable"):
        await documents_service.ingest_pdf(
            _BrokenSession(),
            user_id=uuid.uuid4(),
            filename="cv.pdf",
            content=b"%PDF-1.4 original bytes",
        )

    # The object was uploaded before the row could be written, so it is removed
    # again instead of being left behind as an orphan.
    assert fake_s3.objects == {}


# --------------------------------------------------------------------------- #
# Startup validation
# --------------------------------------------------------------------------- #


def test_startup_validation_rejects_bucket_without_region():
    settings = Settings(
        jwt_secret_key="x" * 40, s3_bucket_name="my-bucket", aws_region=None
    )

    with pytest.raises(RuntimeError, match="AWS_REGION"):
        validate_startup_settings(settings)


def test_startup_validation_accepts_bucket_with_region():
    settings = Settings(
        jwt_secret_key="x" * 40, s3_bucket_name="my-bucket", aws_region="eu-west-1"
    )

    # Credentials are intentionally absent: they are resolved by boto3.
    validate_startup_settings(settings)


def test_startup_validation_allows_running_without_s3():
    settings = Settings(jwt_secret_key="x" * 40, s3_bucket_name=None)

    validate_startup_settings(settings)

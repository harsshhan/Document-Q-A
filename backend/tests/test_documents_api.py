"""Integration tests for document upload, listing and status endpoints.

All of these require ``TEST_DATABASE_URL``. Gemini calls are mocked so no API
key is needed.
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core.config import get_settings
from services import documents as documents_service
from services import s3_storage
from services.embedding import EmbeddingError

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not configured"
    ),
]

DIM = get_settings().embedding_dimension

PDF_HEADERS = b"%PDF-1.4 not a real pdf"


async def _count_chunks(document_id: str) -> int:
    from db.models import DocumentChunk

    engine = create_async_engine(TEST_DATABASE_URL)
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        )
        count = result.scalar_one()
    await engine.dispose()
    return count


async def _stored_s3_key(document_id: str) -> str | None:
    from db.models import Document

    engine = create_async_engine(TEST_DATABASE_URL)
    async with AsyncSession(engine) as session:
        document = await session.get(Document, uuid.UUID(document_id))
        key = document.s3_key if document is not None else None
    await engine.dispose()
    return key


@pytest.fixture
def fake_embeddings(monkeypatch):
    """Deterministic 768-dim document embeddings."""

    async def _embed(chunks, *, task_type=None):
        return [[0.001 * (index + 1)] * DIM for index, _ in enumerate(chunks)]

    monkeypatch.setattr(documents_service, "generate_embeddings", _embed)


@pytest.fixture
def extractable_text(monkeypatch):
    monkeypatch.setattr(
        documents_service,
        "extract_text",
        lambda file: " ".join(f"word{index}" for index in range(150)),
    )


def _upload(client, headers, filename="doc.pdf", content=PDF_HEADERS, content_type="application/pdf"):
    return client.post(
        "/documents",
        headers=headers,
        files={"file": (filename, content, content_type)},
    )


def test_upload_requires_authentication(client):
    response = _upload(client, headers={})

    assert response.status_code == 401


def test_upload_rejects_non_pdf(client, auth_user):
    response = _upload(
        client,
        auth_user["headers"],
        filename="notes.txt",
        content=b"just some text",
        content_type="text/plain",
    )

    assert response.status_code == 400


def test_upload_rejects_empty_file(client, auth_user):
    response = _upload(client, auth_user["headers"], content=b"")

    assert response.status_code == 400


def test_upload_rejects_oversized_file(client, auth_user, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_size_bytes", 10)

    response = _upload(client, auth_user["headers"], content=b"x" * 11)

    assert response.status_code == 413


def test_upload_ingests_document_and_stores_chunks(
    client, auth_user, extractable_text, fake_embeddings
):
    response = _upload(client, auth_user["headers"])

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["error_message"] is None
    assert asyncio.run(_count_chunks(body["id"])) == 2  # 150 words / (100-20)


def test_upload_marks_document_failed_when_embeddings_fail(
    client, auth_user, extractable_text, monkeypatch
):
    async def _broken(chunks, *, task_type=None):
        raise EmbeddingError("Gemini is unavailable.")

    monkeypatch.setattr(documents_service, "generate_embeddings", _broken)

    response = _upload(client, auth_user["headers"])

    assert response.status_code == 422
    # The failure is recorded, and no internal detail leaks to the client.
    assert "Gemini" not in response.json()["detail"]

    listing = client.get("/documents", headers=auth_user["headers"]).json()
    assert listing[0]["status"] == "FAILED"
    assert listing[0]["error_message"] == documents_service.SAFE_FAILURE_MESSAGE
    assert asyncio.run(_count_chunks(listing[0]["id"])) == 0


def test_upload_marks_document_failed_for_unreadable_pdf(client, auth_user):
    response = _upload(client, auth_user["headers"], content=b"not a pdf at all")

    assert response.status_code == 422

    listing = client.get("/documents", headers=auth_user["headers"]).json()
    assert listing[0]["status"] == "FAILED"


def test_list_documents_returns_only_own_documents(
    client, auth_user, extractable_text, fake_embeddings, new_user_payload
):
    _upload(client, auth_user["headers"])

    other_payload = new_user_payload()
    client.post("/auth/register", json=other_payload)
    other_token = client.post(
        "/auth/login",
        json={
            "username": other_payload["username"],
            "password": other_payload["password"],
        },
    ).json()["access_token"]

    own = client.get("/documents", headers=auth_user["headers"]).json()
    other = client.get(
        "/documents", headers={"Authorization": f"Bearer {other_token}"}
    ).json()

    assert len(own) == 1
    assert other == []


def test_status_returns_owned_document(client, auth_user, extractable_text, fake_embeddings):
    document_id = _upload(client, auth_user["headers"]).json()["id"]

    response = client.get(
        f"/documents/{document_id}/status", headers=auth_user["headers"]
    )

    assert response.status_code == 200
    assert response.json() == {
        "document_id": document_id,
        "status": "COMPLETED",
        "error_message": None,
    }


def test_status_hides_another_users_document(
    client, auth_user, extractable_text, fake_embeddings, new_user_payload
):
    document_id = _upload(client, auth_user["headers"]).json()["id"]

    other_payload = new_user_payload()
    client.post("/auth/register", json=other_payload)
    other_token = client.post(
        "/auth/login",
        json={
            "username": other_payload["username"],
            "password": other_payload["password"],
        },
    ).json()["access_token"]

    response = client.get(
        f"/documents/{document_id}/status",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    # Same 404 as an unknown id: existence of another user's document is hidden.
    assert response.status_code == 404


def test_status_returns_404_for_unknown_document(client, auth_user):
    response = client.get(
        "/documents/11111111-1111-1111-1111-111111111111/status",
        headers=auth_user["headers"],
    )

    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# S3 storage
#
# The autouse ``fake_s3`` fixture from conftest.py replaces the boto3 client, so
# these tests exercise the real service code against an in-memory bucket.
# --------------------------------------------------------------------------- #


def test_upload_stores_the_original_pdf_under_a_server_generated_key(
    client, auth_user, extractable_text, fake_embeddings, fake_s3
):
    response = _upload(client, auth_user["headers"], filename="../../etc/passwd.pdf")

    assert response.status_code == 201
    document_id = response.json()["id"]
    user_id = auth_user["user"]["id"]
    expected_key = f"users/{user_id}/documents/{document_id}/original.pdf"

    # Exactly one object, named from server-side identifiers only: the supplied
    # filename must never influence the key.
    assert list(fake_s3.objects) == [(get_settings().s3_bucket_name, expected_key)]
    assert fake_s3.objects[(get_settings().s3_bucket_name, expected_key)] == PDF_HEADERS
    # Never a public-read ACL.
    assert fake_s3.acl_arguments == []

    # The row records the same key, and the displayed filename is unchanged.
    assert asyncio.run(_stored_s3_key(document_id)) == expected_key
    assert response.json()["filename"] == "../../etc/passwd.pdf"
    assert asyncio.run(_count_chunks(document_id)) == 2


def test_s3_upload_failure_reports_a_safe_error_and_creates_nothing(
    client, auth_user, extractable_text, fake_embeddings, fake_s3, monkeypatch
):
    async def _broken_upload(key, content):
        raise s3_storage.S3StorageError("S3 PutObject failed (AccessDenied).")

    monkeypatch.setattr(s3_storage, "upload_pdf", _broken_upload)

    response = _upload(client, auth_user["headers"])

    # Never reported as success, and no internal detail leaks.
    assert response.status_code == 422
    assert response.json()["detail"] == documents_service.SAFE_FAILURE_MESSAGE
    assert "AccessDenied" not in response.json()["detail"]

    # Nothing was stored and no document row was written.
    assert fake_s3.objects == {}
    assert client.get("/documents", headers=auth_user["headers"]).json() == []


def test_failed_ingestion_removes_the_uploaded_object(
    client, auth_user, extractable_text, fake_s3, monkeypatch
):
    async def _broken_embeddings(chunks, *, task_type=None):
        raise EmbeddingError("Gemini is unavailable.")

    monkeypatch.setattr(documents_service, "generate_embeddings", _broken_embeddings)

    response = _upload(client, auth_user["headers"])

    assert response.status_code == 422
    # The orphaned object is deleted again, and the FAILED row no longer points
    # at a key that does not exist.
    assert fake_s3.objects == {}
    listing = client.get("/documents", headers=auth_user["headers"]).json()
    assert listing[0]["status"] == "FAILED"
    assert listing[0]["error_message"] == documents_service.SAFE_FAILURE_MESSAGE
    assert asyncio.run(_stored_s3_key(listing[0]["id"])) is None


def test_cleanup_failure_does_not_hide_the_original_error(
    client, auth_user, extractable_text, fake_s3, monkeypatch
):
    async def _broken_embeddings(chunks, *, task_type=None):
        raise EmbeddingError("Gemini is unavailable.")

    async def _broken_delete(key):
        raise s3_storage.S3StorageError("S3 DeleteObject failed (AccessDenied).")

    monkeypatch.setattr(documents_service, "generate_embeddings", _broken_embeddings)
    monkeypatch.setattr(s3_storage, "delete_pdf", _broken_delete)

    response = _upload(client, auth_user["headers"])

    # The original ingestion failure is reported, not the cleanup failure.
    assert response.status_code == 422
    assert response.json()["detail"] == documents_service.SAFE_FAILURE_MESSAGE

    listing = client.get("/documents", headers=auth_user["headers"]).json()
    assert listing[0]["status"] == "FAILED"
    # The object could not be removed, so the key is kept for a later retry.
    assert asyncio.run(_stored_s3_key(listing[0]["id"])) is not None
    assert len(fake_s3.objects) == 1


def test_upload_is_rejected_when_s3_is_not_configured(
    client, auth_user, extractable_text, fake_embeddings, fake_s3, monkeypatch
):
    monkeypatch.setattr(get_settings(), "s3_bucket_name", None)

    response = _upload(client, auth_user["headers"])

    assert response.status_code == 503
    assert fake_s3.objects == {}
    assert client.get("/documents", headers=auth_user["headers"]).json() == []


def test_download_redirects_the_owner_to_a_short_lived_url(
    client, auth_user, extractable_text, fake_embeddings, fake_s3
):
    document_id = _upload(client, auth_user["headers"]).json()["id"]

    response = client.get(
        f"/documents/{document_id}/download",
        headers=auth_user["headers"],
        follow_redirects=False,
    )

    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith("https://")
    assert f"documents/{document_id}/original.pdf" in location
    # Short-lived and presigned: never a permanent public object URL.
    assert f"X-Amz-Expires={s3_storage.PRESIGNED_URL_EXPIRES_SECONDS}" in location
    assert fake_s3.presigned_requests[0]["expires_in"] == (
        s3_storage.PRESIGNED_URL_EXPIRES_SECONDS
    )


def test_download_requires_authentication(client, auth_user, extractable_text, fake_embeddings):
    document_id = _upload(client, auth_user["headers"]).json()["id"]

    response = client.get(
        f"/documents/{document_id}/download", follow_redirects=False
    )

    assert response.status_code == 401


def test_download_hides_another_users_document(
    client, auth_user, extractable_text, fake_embeddings, new_user_payload, fake_s3
):
    document_id = _upload(client, auth_user["headers"]).json()["id"]

    other_payload = new_user_payload()
    client.post("/auth/register", json=other_payload)
    other_token = client.post(
        "/auth/login",
        json={
            "username": other_payload["username"],
            "password": other_payload["password"],
        },
    ).json()["access_token"]

    response = client.get(
        f"/documents/{document_id}/download",
        headers={"Authorization": f"Bearer {other_token}"},
        follow_redirects=False,
    )

    # Identical to an unknown id: the caller learns nothing about the document.
    assert response.status_code == 404
    assert fake_s3.presigned_requests == []


def test_download_returns_404_for_unknown_document(client, auth_user, fake_s3):
    response = client.get(
        "/documents/11111111-1111-1111-1111-111111111111/download",
        headers=auth_user["headers"],
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert fake_s3.presigned_requests == []


def test_download_reports_a_gateway_error_when_signing_fails(
    client, auth_user, extractable_text, fake_embeddings, fake_s3, monkeypatch
):
    document_id = _upload(client, auth_user["headers"]).json()["id"]

    async def _broken_presign(key, *, expires_in=s3_storage.PRESIGNED_URL_EXPIRES_SECONDS):
        raise s3_storage.S3StorageError("S3 GeneratePresignedUrl failed (AccessDenied).")

    monkeypatch.setattr(s3_storage, "presigned_download_url", _broken_presign)

    response = client.get(
        f"/documents/{document_id}/download",
        headers=auth_user["headers"],
        follow_redirects=False,
    )

    assert response.status_code == 502
    # The AWS error code stays in the logs, not in the response.
    assert "AccessDenied" not in response.json()["detail"]


def test_download_returns_404_when_no_object_was_stored(
    client, auth_user, extractable_text, fake_s3, monkeypatch
):
    async def _broken_embeddings(chunks, *, task_type=None):
        raise EmbeddingError("Gemini is unavailable.")

    monkeypatch.setattr(documents_service, "generate_embeddings", _broken_embeddings)
    _upload(client, auth_user["headers"])
    listing = client.get("/documents", headers=auth_user["headers"]).json()

    response = client.get(
        f"/documents/{listing[0]['id']}/download",
        headers=auth_user["headers"],
        follow_redirects=False,
    )

    # The row survived the failure but the object was cleaned up, so there is
    # still nothing to download.
    assert response.status_code == 404
    assert fake_s3.presigned_requests == []

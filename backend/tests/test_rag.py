"""Tests for the retrieval-augmented answering pipeline (``/ask``).

Unit tests exercise ``services.rag`` directly with mocked collaborators.
Integration tests drive the ``POST /ask`` endpoint end to end and require
``TEST_DATABASE_URL``; Gemini calls are always mocked, so no API key is needed.
"""

import os
import uuid

import pytest

from core.config import get_settings
from services import rag
from services.embedding import EmbeddingError
from services.llm import LLMError, NO_ANSWER_SENTENCE
from services.retrieval import RetrievedChunk

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

DIM = get_settings().embedding_dimension
PDF_HEADERS = b"%PDF-1.4 not a real pdf"


# --------------------------------------------------------------------------- #
# Pure unit tests (no database, no API key)
# --------------------------------------------------------------------------- #


def test_build_context_includes_references_and_content():
    hits = [
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            document_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            chunk_index=0,
            content="Alice is the user.",
            score=0.9,
        ),
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            document_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            chunk_index=4,
            content="Project codename is Falcon.",
            score=0.8,
        ),
    ]

    context = rag.build_context(hits)

    assert "[1]" in context and "[2]" in context
    assert "11111111-1111-1111-1111-111111111111" in context
    assert "chunk 4" in context
    assert "Alice is the user." in context
    assert "Project codename is Falcon." in context


async def test_answer_question_clamps_top_k(monkeypatch):
    captured = {}

    async def _embed(query):
        return [0.0] * DIM

    async def _search(session, *, user_id, query_embedding, top_k):
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr(rag, "generate_query_embedding", _embed)
    monkeypatch.setattr(rag, "search_similar_chunks", _search)

    result = await rag.answer_question(
        object(), user_id=uuid.uuid4(), query="hello", top_k=9999
    )

    assert captured["top_k"] == get_settings().rag_max_top_k
    assert result.no_match is True
    assert result.sources == []
    assert result.answer == rag.SAFE_NO_MATCH_ANSWER


async def test_answer_question_no_match_below_similarity_threshold(monkeypatch):
    """A chunk that does not clear the threshold must not reach the LLM."""

    def _boom(*args, **kwargs):
        raise AssertionError("generate_answer must not be called")

    async def _embed(query):
        return [0.0] * DIM

    async def _search(session, *, user_id, query_embedding, top_k):
        return [
            RetrievedChunk(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                chunk_index=0,
                content="Unrelated text.",
                score=get_settings().rag_min_similarity - 0.1,
            )
        ]

    monkeypatch.setattr(rag, "generate_query_embedding", _embed)
    monkeypatch.setattr(rag, "search_similar_chunks", _search)
    monkeypatch.setattr(rag, "generate_answer", _boom)

    result = await rag.answer_question(
        object(), user_id=uuid.uuid4(), query="hello", top_k=3
    )

    assert result.no_match is True
    assert result.sources == []
    assert result.answer == rag.SAFE_NO_MATCH_ANSWER


async def test_answer_question_flags_model_no_match(monkeypatch):
    """When the model returns the sentinel sentence it is reported as no-match."""

    async def _embed(query):
        return [0.0] * DIM

    async def _search(session, *, user_id, query_embedding, top_k):
        return [
            RetrievedChunk(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                chunk_index=0,
                content="Some content.",
                score=0.99,
            )
        ]

    async def _answer(context, query):
        return NO_ANSWER_SENTENCE

    monkeypatch.setattr(rag, "generate_query_embedding", _embed)
    monkeypatch.setattr(rag, "search_similar_chunks", _search)
    monkeypatch.setattr(rag, "generate_answer", _answer)

    result = await rag.answer_question(
        object(), user_id=uuid.uuid4(), query="hello", top_k=3
    )

    assert result.no_match is True
    assert result.answer == NO_ANSWER_SENTENCE
    assert len(result.sources) == 1


# --------------------------------------------------------------------------- #
# Endpoint tests
# --------------------------------------------------------------------------- #

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not configured"
    ),
]


@pytest.fixture
def fake_document_embeddings(monkeypatch):
    """Deterministic document embeddings; chunk 0 is identical to the query."""

    from services import documents as documents_service

    async def _embed(chunks, *, task_type=None):
        return [[0.001 * (index + 1)] * DIM for index, _ in enumerate(chunks)]

    monkeypatch.setattr(documents_service, "generate_embeddings", _embed)


@pytest.fixture
def extractable_text(monkeypatch):
    from services import documents as documents_service

    monkeypatch.setattr(
        documents_service,
        "extract_text",
        lambda file: " ".join(f"word{index}" for index in range(150)),
    )


@pytest.fixture
def matching_query_embedding(monkeypatch):
    """Query embedding identical to chunk 0 -> cosine similarity 1.0."""

    async def _embed(query):
        return [0.001] * DIM

    monkeypatch.setattr(rag, "generate_query_embedding", _embed)


def _upload(client, headers):
    return client.post(
        "/documents",
        headers=headers,
        files={"file": ("doc.pdf", PDF_HEADERS, "application/pdf")},
    )


def test_ask_requires_authentication(client):
    response = client.post("/ask", json={"query": "What is my name?"})

    assert response.status_code == 401


def test_ask_returns_answer_with_sources(
    client, auth_user, extractable_text, fake_document_embeddings,
    matching_query_embedding, monkeypatch
):
    document_id = _upload(client, auth_user["headers"]).json()["id"]

    async def _answer(context, query):
        assert "Alice" in context or "word" in context
        return "Your name is Demo User."

    monkeypatch.setattr(rag, "generate_answer", _answer)

    response = client.post(
        "/ask",
        headers=auth_user["headers"],
        json={"query": "What is my name?", "top_k": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Your name is Demo User."
    assert body["no_match"] is False
    assert len(body["sources"]) >= 1

    source = body["sources"][0]
    assert source["document_id"] == document_id
    assert isinstance(source["chunk_index"], int)
    assert source["content"]
    assert 0.0 <= source["score"] <= 1.0


def test_ask_no_match_when_nothing_relevant(client, auth_user, monkeypatch):
    async def _embed(query):
        return [0.0] * DIM

    async def _search(session, *, user_id, query_embedding, top_k):
        return []

    def _boom(*args, **kwargs):
        raise AssertionError("generate_answer must not be called for no-match")

    monkeypatch.setattr(rag, "generate_query_embedding", _embed)
    monkeypatch.setattr(rag, "search_similar_chunks", _search)
    monkeypatch.setattr(rag, "generate_answer", _boom)

    response = client.post(
        "/ask", headers=auth_user["headers"], json={"query": "anything"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["no_match"] is True
    assert body["sources"] == []
    assert body["answer"] == rag.SAFE_NO_MATCH_ANSWER


def test_ask_sources_are_scoped_to_authenticated_user(
    client, auth_user, new_user_payload, extractable_text,
    fake_document_embeddings, matching_query_embedding, monkeypatch
):
    own_document_id = _upload(client, auth_user["headers"]).json()["id"]

    other_payload = new_user_payload()
    client.post("/auth/register", json=other_payload)
    other_token = client.post(
        "/auth/login",
        json={
            "username": other_payload["username"],
            "password": other_payload["password"],
        },
    ).json()["access_token"]
    other_headers = {"Authorization": f"Bearer {other_token}"}
    _upload(client, other_headers)

    async def _answer(context, query):
        return "Scoped answer."

    monkeypatch.setattr(rag, "generate_answer", _answer)

    response = client.post(
        "/ask", headers=auth_user["headers"], json={"query": "hello", "top_k": 10}
    )

    assert response.status_code == 200
    sources = response.json()["sources"]
    assert sources, "expected the caller's own chunks to be retrieved"
    assert {source["document_id"] for source in sources} == {own_document_id}


def test_ask_returns_502_when_embedding_fails(client, auth_user, monkeypatch):
    async def _embed(query):
        raise EmbeddingError("Gemini is unavailable.")

    monkeypatch.setattr(rag, "generate_query_embedding", _embed)

    response = client.post(
        "/ask", headers=auth_user["headers"], json={"query": "hello"}
    )

    assert response.status_code == 502
    assert "Gemini" not in response.json()["detail"]


def test_ask_returns_502_when_llm_fails(
    client, auth_user, extractable_text, fake_document_embeddings,
    matching_query_embedding, monkeypatch
):
    _upload(client, auth_user["headers"])

    async def _answer(context, query):
        raise LLMError("Gemini is unavailable.")

    monkeypatch.setattr(rag, "generate_answer", _answer)

    response = client.post(
        "/ask", headers=auth_user["headers"], json={"query": "hello"}
    )

    assert response.status_code == 502
    assert "Gemini" not in response.json()["detail"]


def test_ask_rejects_empty_query(client, auth_user):
    response = client.post("/ask", headers=auth_user["headers"], json={"query": ""})

    assert response.status_code == 422


def test_ask_propagates_database_failure(client, auth_user, monkeypatch):
    """A database error must not be masked by a fake answer."""

    from fastapi.testclient import TestClient
    from sqlalchemy.exc import OperationalError

    from main import app

    async def _embed(query):
        return [0.0] * DIM

    async def _search(session, *, user_id, query_embedding, top_k):
        raise OperationalError("SELECT 1", {}, Exception("database is down"))

    monkeypatch.setattr(rag, "generate_query_embedding", _embed)
    monkeypatch.setattr(rag, "search_similar_chunks", _search)

    with TestClient(app, raise_server_exceptions=False) as failing_client:
        response = failing_client.post(
            "/ask", headers=auth_user["headers"], json={"query": "hello"}
        )

    assert response.status_code == 500
    assert "database is down" not in response.text

"""Tests for services/embedding.py.

The Gemini HTTP call is mocked through the ``post_json`` seam imported into this
module, so the tests never touch the network and never need a real API key.
"""

import math

import pytest

from services import embedding

DIM = 768


@pytest.fixture
def fake_post(monkeypatch):
    """Replace the Gemini call and capture the request payload."""

    captured = {}

    async def _post(path, payload, *, timeout=None):
        captured["path"] = path
        captured["payload"] = payload
        captured["timeout"] = timeout
        return {"embeddings": [{"values": [0.1] * DIM} for _ in payload["requests"]]}

    monkeypatch.setattr(embedding, "post_json", _post)
    return captured


async def test_document_embeddings_use_retrieval_document_task(fake_post):
    vectors = await embedding.generate_embeddings(["chunk one", "chunk two"])

    assert len(vectors) == 2
    assert fake_post["payload"]["requests"][0]["taskType"] == "RETRIEVAL_DOCUMENT"


async def test_query_embedding_uses_retrieval_query_task(fake_post):
    vector = await embedding.generate_query_embedding("what is the capital?")

    assert len(vector) == DIM
    assert fake_post["payload"]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"


async def test_requests_declare_model_and_dimension(fake_post):
    await embedding.generate_embeddings(["chunk"])

    request = fake_post["payload"]["requests"][0]
    model = embedding.get_settings().gemini_embedding_model
    assert request["model"] == f"models/{model}"
    assert request["outputDimensionality"] == DIM
    assert fake_post["path"] == f"models/{model}:batchEmbedContents"


async def test_vectors_are_l2_normalized(fake_post):
    vector = (await embedding.generate_embeddings(["chunk"]))[0]

    norm = math.sqrt(sum(value * value for value in vector))
    assert norm == pytest.approx(1.0)


async def test_empty_input_makes_no_request(fake_post):
    assert await embedding.generate_embeddings([]) == []
    assert "payload" not in fake_post


async def test_batching_splits_large_inputs(fake_post, monkeypatch):
    monkeypatch.setattr(embedding.get_settings(), "embedding_batch_size", 2)

    original = embedding.post_json
    batch_sizes = []

    async def counting_post(path, payload, *, timeout=None):
        batch_sizes.append(len(payload["requests"]))
        return await original(path, payload, timeout=timeout)

    monkeypatch.setattr(embedding, "post_json", counting_post)

    await embedding.generate_embeddings(["a", "b", "c"])

    assert batch_sizes == [2, 1]


async def test_embedding_count_mismatch_raises(monkeypatch):
    async def _post(path, payload, *, timeout=None):
        return {"embeddings": [{"values": [0.0] * DIM}]}  # one vector for two inputs

    monkeypatch.setattr(embedding, "post_json", _post)

    with pytest.raises(embedding.EmbeddingError):
        await embedding.generate_embeddings(["a", "b"])


async def test_embedding_dimension_mismatch_raises(monkeypatch):
    async def _post(path, payload, *, timeout=None):
        return {"embeddings": [{"values": [0.0] * 10}]}

    monkeypatch.setattr(embedding, "post_json", _post)

    with pytest.raises(embedding.EmbeddingError):
        await embedding.generate_embeddings(["a"])


async def test_api_failure_is_propagated_not_faked(monkeypatch):
    from core.gemini import GeminiAPIError

    async def _post(path, payload, *, timeout=None):
        raise GeminiAPIError("Gemini API returned HTTP 500.")

    monkeypatch.setattr(embedding, "post_json", _post)

    # No silent fallback to random/fake vectors: the error must surface.
    with pytest.raises(embedding.EmbeddingError):
        await embedding.generate_embeddings(["a"])


async def test_blank_text_is_rejected(fake_post):
    with pytest.raises(embedding.EmbeddingError):
        await embedding.generate_embeddings(["   "])


async def test_empty_query_is_rejected(fake_post):
    with pytest.raises(embedding.EmbeddingError):
        await embedding.generate_query_embedding("")

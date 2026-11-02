"""Embedding generation through the Gemini embedding API.

This replaces the previous Sentence Transformers implementation. Document
chunks and queries share the same model and output dimension; only the Gemini
``taskType`` differs, which is what makes the vectors compatible for retrieval.
There is no local model and no random/fake fallback: if Gemini cannot be
reached the error is raised to the caller.
"""

import logging
import math

from core.config import get_settings
from core.gemini import GeminiAPIError, post_json

logger = logging.getLogger(__name__)

TASK_TYPE_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_TYPE_QUERY = "RETRIEVAL_QUERY"


class EmbeddingError(RuntimeError):
    """Raised when embeddings cannot be produced."""


def _normalize(values: list[float]) -> list[float]:
    """L2-normalize a vector.

    ``gemini-embedding-001`` produces non-normalized vectors when a reduced
    ``outputDimensionality`` is requested, so the vector is normalized here.
    Cosine distance is unaffected by scaling, but normalizing keeps stored
    vectors comparable and well conditioned.
    """

    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0.0:
        return [float(v) for v in values]
    return [v / norm for v in values]


def _build_requests(
    texts: list[str], task_type: str, model: str, dimension: int
) -> list[dict]:
    return [
        {
            "model": f"models/{model}",
            "content": {"parts": [{"text": text}]},
            "taskType": task_type,
            "outputDimensionality": dimension,
        }
        for text in texts
    ]


async def _embed_batch(texts: list[str], task_type: str) -> list[list[float]]:
    settings = get_settings()

    payload = {
        "requests": _build_requests(
            texts,
            task_type,
            settings.gemini_embedding_model,
            settings.embedding_dimension,
        )
    }

    path = f"models/{settings.gemini_embedding_model}:batchEmbedContents"

    try:
        data = await post_json(path, payload)
    except GeminiAPIError as exc:
        raise EmbeddingError(str(exc)) from exc

    embeddings = data.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise EmbeddingError(
            "Gemini returned an unexpected number of embeddings "
            f"(expected {len(texts)})."
        )

    vectors: list[list[float]] = []
    for item in embeddings:
        values = item.get("values") if isinstance(item, dict) else None
        if not isinstance(values, list) or len(values) != settings.embedding_dimension:
            raise EmbeddingError(
                "Gemini returned an embedding with an unexpected dimension "
                f"(expected {settings.embedding_dimension})."
            )
        try:
            vectors.append(_normalize([float(value) for value in values]))
        except (TypeError, ValueError) as exc:
            raise EmbeddingError("Gemini returned a non-numeric embedding.") from exc

    return vectors


async def generate_embeddings(
    chunks: list[str], *, task_type: str = TASK_TYPE_DOCUMENT
) -> list[list[float]]:
    """Embed document chunks with the task type used for indexing."""

    texts = list(chunks)
    if not texts:
        return []

    for text in texts:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingError("Embedding input must be non-empty text.")

    settings = get_settings()
    batch_size = max(1, settings.embedding_batch_size)

    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors.extend(await _embed_batch(batch, task_type))

    logger.info(
        "Generated %d embeddings (model=%s, dim=%d, task=%s)",
        len(vectors),
        settings.gemini_embedding_model,
        settings.embedding_dimension,
        task_type,
    )
    return vectors


async def generate_query_embedding(query: str) -> list[float]:
    """Embed a search query with the task type used for retrieval."""

    if not query or not query.strip():
        raise EmbeddingError("Query text must not be empty.")

    vectors = await generate_embeddings([query], task_type=TASK_TYPE_QUERY)
    return vectors[0]

"""Answer generation through the Gemini API.

Kept deliberately separate from ``services.embedding``: this module never
produces vectors and the embedding module never generates text.
"""

import logging

from core.config import get_settings
from core.gemini import GeminiAPIError, post_json

logger = logging.getLogger(__name__)

# The exact sentence the model must return when the context does not contain the
# answer. Reported by the RAG service as a "no match".
NO_ANSWER_SENTENCE = "I could not find the answer in the provided documents."

SYSTEM_INSTRUCTION = (
    "You are a document question answering assistant. "
    "Answer the user's question using only the provided context. "
    "If the answer cannot be found in the context, reply exactly with: "
    f"{NO_ANSWER_SENTENCE} "
    "Never use outside knowledge and never invent facts."
)


class LLMError(RuntimeError):
    """Raised when Gemini cannot produce an answer."""


def build_prompt(context: str, query: str) -> str:
    return (
        "Context:\n"
        f"{context}\n\n"
        "Question:\n"
        f"{query}\n\n"
        "Answer using only the context above."
    )


def _extract_text(data: dict) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        return ""

    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []

    return "".join(
        part.get("text", "") for part in parts if isinstance(part, dict)
    ).strip()


async def generate_answer(
    context: str, query: str, *, system_instruction: str | None = None
) -> str:
    """Return an answer grounded in ``context`` (same interface as before)."""

    settings = get_settings()

    payload = {
        "systemInstruction": {
            "parts": [{"text": system_instruction or SYSTEM_INSTRUCTION}]
        },
        "contents": [
            {"role": "user", "parts": [{"text": build_prompt(context, query)}]}
        ],
        "generationConfig": {
            "temperature": settings.gemini_temperature,
            "maxOutputTokens": settings.gemini_max_output_tokens,
        },
    }

    path = f"models/{settings.gemini_chat_model}:generateContent"

    try:
        data = await post_json(path, payload)
    except GeminiAPIError as exc:
        raise LLMError(str(exc)) from exc

    answer = _extract_text(data)
    if not answer:
        logger.warning("Gemini returned no answer text for the generation request")
        raise LLMError("Gemini returned an empty answer.")

    return answer

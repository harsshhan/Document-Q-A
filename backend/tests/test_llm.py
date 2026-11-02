"""Tests for services/llm.py. All Gemini calls are mocked."""

import pytest

from core.gemini import GeminiAPIError
from services import llm


@pytest.fixture
def fake_post(monkeypatch):
    captured = {}

    async def _post(path, payload, *, timeout=None):
        captured["path"] = path
        captured["payload"] = payload
        return {"candidates": [{"content": {"parts": [{"text": "Paris"}]}}]}

    monkeypatch.setattr(llm, "post_json", _post)
    return captured


async def test_returns_model_answer_and_sends_prompt(fake_post):
    answer = await llm.generate_answer(
        "France's capital is Paris.", "What is the capital?"
    )

    assert answer == "Paris"
    prompt = fake_post["payload"]["contents"][0]["parts"][0]["text"]
    assert "France's capital is Paris." in prompt
    assert "What is the capital?" in prompt


async def test_system_instruction_is_sent(fake_post):
    await llm.generate_answer("ctx", "q")

    instruction = fake_post["payload"]["systemInstruction"]["parts"][0]["text"]
    assert "only the provided context" in instruction


async def test_generation_uses_chat_model_endpoint(fake_post):
    await llm.generate_answer("ctx", "q")

    assert fake_post["path"].endswith(":generateContent")


async def test_empty_candidates_raise(monkeypatch):
    async def _post(path, payload, *, timeout=None):
        return {"candidates": []}

    monkeypatch.setattr(llm, "post_json", _post)

    with pytest.raises(llm.LLMError):
        await llm.generate_answer("ctx", "q")


async def test_api_error_is_mapped(monkeypatch):
    async def _post(path, payload, *, timeout=None):
        raise GeminiAPIError("Gemini request timed out.")

    monkeypatch.setattr(llm, "post_json", _post)

    with pytest.raises(llm.LLMError):
        await llm.generate_answer("ctx", "q")


def test_build_prompt_contains_context_and_question():
    prompt = llm.build_prompt("some context", "some question")

    assert "some context" in prompt
    assert "some question" in prompt

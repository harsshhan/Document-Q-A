"""Tests for core/gemini.py: key handling, error mapping and safe requests."""

import httpx
import pytest

from core import gemini
from core.config import get_settings


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FakeClient:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, json=None, headers=None):
        if self._exc is not None:
            raise self._exc
        return self._response


def _patch_client(monkeypatch, **kwargs):
    monkeypatch.setattr(gemini, "_http_client", lambda timeout: _FakeClient(**kwargs))


async def test_missing_api_key_raises(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", None)

    with pytest.raises(gemini.GeminiAPIError):
        await gemini.post_json("models/x:y", {})


async def test_successful_response_is_decoded(monkeypatch):
    _patch_client(monkeypatch, response=_FakeResponse(200, {"ok": True}))

    assert await gemini.post_json("models/x:y", {}) == {"ok": True}


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "authentication failed"),
        (403, "authentication failed"),
        (429, "rate limit"),
        (500, "HTTP 500"),
    ],
)
async def test_error_statuses_are_mapped(monkeypatch, status, expected):
    _patch_client(monkeypatch, response=_FakeResponse(status, text="boom"))

    with pytest.raises(gemini.GeminiAPIError) as exc_info:
        await gemini.post_json("models/x:y", {})

    assert expected in str(exc_info.value)


async def test_timeout_is_mapped(monkeypatch):
    _patch_client(monkeypatch, exc=httpx.TimeoutException("slow"))

    with pytest.raises(gemini.GeminiAPIError):
        await gemini.post_json("models/x:y", {})


async def test_transport_error_is_mapped(monkeypatch):
    _patch_client(monkeypatch, exc=httpx.ConnectError("no route"))

    with pytest.raises(gemini.GeminiAPIError):
        await gemini.post_json("models/x:y", {})


async def test_api_key_is_sent_as_header_and_not_in_url(monkeypatch):
    captured = {}

    class _CapturingClient(_FakeClient):
        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            return _FakeResponse(200, {"ok": True})

    monkeypatch.setattr(gemini, "_http_client", lambda timeout: _CapturingClient())

    await gemini.post_json("models/x:y", {})

    api_key = get_settings().gemini_api_key
    assert api_key
    assert api_key not in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == api_key

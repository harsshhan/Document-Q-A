"""Minimal async client for the Gemini REST API.

Only transport concerns live here: authentication, timeouts, retries-free error
mapping and safe logging. The API key is sent as a request header (never in the
URL) and is never written to logs.
"""

import logging
from typing import Any

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)

MAX_LOGGED_BODY_CHARS = 300


class GeminiAPIError(RuntimeError):
    """Raised when Gemini is misconfigured, unreachable, or returns an error."""


def _http_client(timeout: float) -> httpx.AsyncClient:
    """Build the HTTP client. Patched in tests with a mock transport."""

    return httpx.AsyncClient(timeout=timeout)


def _short(body: str) -> str:
    """Trim a response body so logs stay small and free of newlines."""

    return (body or "").strip().replace("\n", " ")[:MAX_LOGGED_BODY_CHARS]


async def post_json(
    path: str,
    payload: dict[str, Any],
    *,
    timeout: float | None = None,
) -> dict[str, Any]:
    """POST ``payload`` to a Gemini ``path`` and return the decoded JSON body."""

    settings = get_settings()
    api_key = settings.gemini_api_key

    if not api_key:
        raise GeminiAPIError(
            "GEMINI_API_KEY is not configured; Gemini requests cannot be made."
        )

    url = f"{settings.gemini_base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    try:
        async with _http_client(timeout or settings.gemini_timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        logger.warning("Gemini request timed out: %s", path)
        raise GeminiAPIError("Gemini request timed out.") from exc
    except httpx.HTTPError as exc:
        logger.warning("Gemini request failed: %s (%s)", path, type(exc).__name__)
        raise GeminiAPIError(f"Gemini request failed: {type(exc).__name__}.") from exc

    status = response.status_code

    if status in (401, 403):
        logger.warning("Gemini authentication failure: HTTP %s on %s", status, path)
        raise GeminiAPIError("Gemini authentication failed. Check GEMINI_API_KEY.")
    if status == 429:
        logger.warning("Gemini rate limit reached on %s", path)
        raise GeminiAPIError("Gemini rate limit exceeded. Please retry later.")
    if status >= 400:
        logger.warning(
            "Gemini API error: HTTP %s on %s: %s", status, path, _short(response.text)
        )
        raise GeminiAPIError(f"Gemini API returned HTTP {status}.")

    try:
        return response.json()
    except ValueError as exc:
        logger.warning("Gemini returned a non-JSON response on %s", path)
        raise GeminiAPIError("Gemini returned a non-JSON response.") from exc

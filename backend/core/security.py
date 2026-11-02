"""Password hashing and JWT handling.

Passwords are hashed with Argon2 (via pwdlib) and signed tokens are created with
PyJWT. The signing key comes from ``JWT_SECRET_KEY`` and is never the Gemini API
key. Passwords and tokens are never logged.
"""

import logging
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from core.config import get_settings

logger = logging.getLogger(__name__)

# Argon2id as recommended by pwdlib.
_password_hasher = PasswordHash.recommended()


class TokenError(Exception):
    """Raised when a JWT is malformed, tampered with, or expired."""


def hash_password(password: str) -> str:
    """Return an Argon2 hash of ``password`` (never the plaintext)."""

    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check ``password`` against a stored hash. Never raises on bad input."""

    try:
        return _password_hasher.verify(password, password_hash)
    except Exception:  # malformed/unknown hash format
        logger.warning("Rejected a password check against an invalid hash")
        return False


def create_access_token(subject: str) -> tuple[str, int]:
    """Create a signed access token for ``subject`` (the user's UUID).

    Returns the encoded token and its lifetime in seconds.
    """

    settings = get_settings()

    if not settings.jwt_secret_key:
        raise RuntimeError("JWT_SECRET_KEY is not configured.")

    expires_in = settings.access_token_expire_seconds
    issued_at = datetime.now(timezone.utc)

    payload = {
        "sub": str(subject),
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(seconds=expires_in)).timestamp()),
    }

    token = jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    return token, expires_in


def decode_access_token(token: str) -> dict:
    """Validate ``token`` and return its claims.

    Raises :class:`TokenError` for expired, tampered with, or malformed tokens.
    """

    settings = get_settings()

    if not settings.jwt_secret_key:
        raise TokenError("JWT_SECRET_KEY is not configured.")

    try:
        return jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Token is invalid.") from exc

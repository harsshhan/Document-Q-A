"""Tests for core/security.py (password hashing and JWTs)."""

import time

import jwt
import pytest

from core import security
from core.config import get_settings


def test_password_hash_is_verifiable_and_not_plaintext():
    hashed = security.hash_password("DemoPass123!")

    assert hashed != "DemoPass123!"
    assert security.verify_password("DemoPass123!", hashed) is True


def test_wrong_password_is_rejected():
    hashed = security.hash_password("DemoPass123!")

    assert security.verify_password("wrong-password", hashed) is False


def test_invalid_hash_format_is_rejected_without_raising():
    assert security.verify_password("anything", "not-a-valid-hash") is False


def test_hashes_are_salted():
    assert security.hash_password("same") != security.hash_password("same")


def test_token_round_trip_contains_expected_claims():
    token, expires_in = security.create_access_token("11111111-1111-1111-1111-111111111111")
    payload = security.decode_access_token(token)

    assert payload["sub"] == "11111111-1111-1111-1111-111111111111"
    assert "iat" in payload
    assert "exp" in payload
    assert expires_in == get_settings().access_token_expire_seconds


def test_tampered_token_is_rejected():
    token, _ = security.create_access_token("subject")

    with pytest.raises(security.TokenError):
        security.decode_access_token(token + "tampered")


def test_token_signed_with_another_key_is_rejected():
    forged = jwt.encode(
        {"sub": "subject", "exp": int(time.time()) + 60},
        "a-completely-different-signing-key",
        algorithm="HS256",
    )

    with pytest.raises(security.TokenError):
        security.decode_access_token(forged)


def test_expired_token_is_rejected(monkeypatch):
    monkeypatch.setattr(get_settings(), "access_token_expire_seconds", -10)
    token, _ = security.create_access_token("subject")

    with pytest.raises(security.TokenError):
        security.decode_access_token(token)

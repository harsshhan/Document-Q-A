"""API tests for the health endpoint and authentication.

The health endpoint needs no database. Authentication tests are marked
``integration`` and only run when ``TEST_DATABASE_URL`` is configured.
"""

import os
import uuid

import pytest

from core.config import get_settings
from core.security import create_access_token

requires_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is not configured",
)


def test_home_endpoint(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Backend running"}


@pytest.mark.integration
@requires_db
def test_register_returns_public_profile_without_secrets(client, new_user_payload):
    payload = new_user_payload()

    response = client.post("/auth/register", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == payload["username"]
    assert body["email"] == payload["email"]
    assert body["name"] == "Test User"
    assert uuid.UUID(body["id"])
    assert "password" not in body
    assert "password_hash" not in body


@pytest.mark.integration
@requires_db
def test_register_rejects_duplicate_username(client, new_user_payload):
    payload = new_user_payload()
    assert client.post("/auth/register", json=payload).status_code == 201

    duplicate = new_user_payload(username=payload["username"])

    assert client.post("/auth/register", json=duplicate).status_code == 409


@pytest.mark.integration
@requires_db
def test_register_rejects_duplicate_email(client, new_user_payload):
    payload = new_user_payload()
    assert client.post("/auth/register", json=payload).status_code == 201

    duplicate = new_user_payload(email=payload["email"])

    assert client.post("/auth/register", json=duplicate).status_code == 409


@pytest.mark.integration
@requires_db
def test_register_validates_input(client, new_user_payload):
    assert client.post("/auth/register", json=new_user_payload(password="short")).status_code == 422
    assert client.post("/auth/register", json=new_user_payload(email="not-an-email")).status_code == 422
    assert client.post("/auth/register", json=new_user_payload(username="ab")).status_code == 422


@pytest.mark.integration
@requires_db
def test_login_returns_token_and_user(client, auth_user):
    payload = auth_user["payload"]

    response = client.post(
        "/auth/login",
        json={"username": payload["username"], "password": payload["password"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] == get_settings().access_token_expire_seconds
    assert body["user"]["username"] == payload["username"]
    assert "password_hash" not in body["user"]


@pytest.mark.integration
@requires_db
def test_login_rejects_wrong_password(client, auth_user):
    payload = auth_user["payload"]

    response = client.post(
        "/auth/login",
        json={"username": payload["username"], "password": "wrong-password"},
    )

    assert response.status_code == 401


@pytest.mark.integration
@requires_db
def test_login_rejects_unknown_user(client):
    response = client.post(
        "/auth/login", json={"username": "user_does_not_exist", "password": "whatever"}
    )

    assert response.status_code == 401


@pytest.mark.integration
@requires_db
def test_me_returns_profile_for_valid_token(client, auth_user):
    response = client.get("/auth/me", headers=auth_user["headers"])

    assert response.status_code == 200
    assert response.json()["id"] == auth_user["user"]["id"]


@pytest.mark.integration
@requires_db
def test_me_requires_a_token(client):
    assert client.get("/auth/me").status_code == 401


@pytest.mark.integration
@requires_db
def test_me_rejects_invalid_token(client):
    response = client.get(
        "/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )

    assert response.status_code == 401


@pytest.mark.integration
@requires_db
def test_me_rejects_expired_token(client, auth_user, monkeypatch):
    monkeypatch.setattr(get_settings(), "access_token_expire_seconds", -10)
    expired_token, _ = create_access_token(auth_user["user"]["id"])

    response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
    )

    assert response.status_code == 401

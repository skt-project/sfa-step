"""Tests for /auth endpoints."""
import os

import pytest

# Read from env so these keep passing after the seeded defaults are rotated.
_TEST_PASSWORD = os.environ.get("STEP_TEST_PASSWORD", "STEP@2026")
_ADMIN_PASSWORD = os.environ.get("STEP_ADMIN_PASSWORD", "Step@2026!")


def test_login_admin_ok(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": _ADMIN_PASSWORD})
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert data["user"]["role"] == "ho_admin"


def test_login_se_ok(client):
    r = client.post("/api/v1/auth/login", json={"username": "demo", "password": _TEST_PASSWORD})
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "se"


def test_login_wrong_password(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_login_unknown_user(client):
    r = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
    assert r.status_code == 401


def test_me_returns_user(client, admin_token):
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert r.json()["username"] == "admin"


def test_me_requires_auth(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 403


def test_reset_password_invalid_token(client):
    r = client.post("/api/v1/auth/reset-password", json={
        "reset_token": "not-a-valid-token",
        "new_password": "NewPass123!",
    })
    assert r.status_code == 400


def test_reset_token_requires_admin(client, se_token):
    r = client.post(
        "/api/v1/admin/users/some-id/reset-token",
        headers={"Authorization": f"Bearer {se_token}"},
    )
    assert r.status_code == 403

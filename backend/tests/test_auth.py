from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, admin_user) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "TestPassword1!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, admin_user) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "WrongPassword1!"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@test.com", "password": "SomePassword1!"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient, admin_token: str) -> None:
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "admin@test.com"
    assert data["role"] == "admin"


@pytest.mark.asyncio
async def test_refresh_token(client: AsyncClient, admin_user) -> None:
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "TestPassword1!"},
    )
    refresh_token = login_resp.json()["refresh_token"]
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_get_me_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401

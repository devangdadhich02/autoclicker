from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_ping(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health/ping")
    assert resp.status_code == 200
    assert resp.json()["pong"] is True


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_health_detailed(client: AsyncClient, admin_token: str) -> None:
    resp = await client.get(
        "/api/v1/health/detailed",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "uptime_seconds" in data
    assert "memory" in data
    assert "automation" in data

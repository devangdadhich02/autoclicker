from __future__ import annotations

import pytest
from httpx import AsyncClient


JOB_PAYLOAD = {
    "name": "Test IndiaMART Job",
    "target_url": "https://seller.indiamart.com/messageboxnew/",
    "description": "Monitor new inquiries",
    "poll_interval_seconds": 30,
}


@pytest.mark.asyncio
async def test_create_job(client: AsyncClient, operator_token: str) -> None:
    resp = await client.post(
        "/api/v1/jobs",
        json=JOB_PAYLOAD,
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == JOB_PAYLOAD["name"]
    assert data["status"] == "idle"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_list_jobs(client: AsyncClient, operator_token: str) -> None:
    await client.post(
        "/api/v1/jobs",
        json=JOB_PAYLOAD,
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    resp = await client.get(
        "/api/v1/jobs",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_get_job(client: AsyncClient, operator_token: str) -> None:
    create_resp = await client.post(
        "/api/v1/jobs",
        json=JOB_PAYLOAD,
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    job_id = create_resp.json()["id"]
    resp = await client.get(
        f"/api/v1/jobs/{job_id}",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == job_id


@pytest.mark.asyncio
async def test_update_job(client: AsyncClient, operator_token: str) -> None:
    create_resp = await client.post(
        "/api/v1/jobs",
        json=JOB_PAYLOAD,
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    job_id = create_resp.json()["id"]
    resp = await client.patch(
        f"/api/v1/jobs/{job_id}",
        json={"name": "Updated Job Name", "poll_interval_seconds": 60},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Job Name"
    assert resp.json()["poll_interval_seconds"] == 60


@pytest.mark.asyncio
async def test_delete_job(client: AsyncClient, operator_token: str) -> None:
    create_resp = await client.post(
        "/api/v1/jobs",
        json=JOB_PAYLOAD,
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    job_id = create_resp.json()["id"]
    del_resp = await client.delete(
        f"/api/v1/jobs/{job_id}",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert del_resp.status_code == 204
    get_resp = await client.get(
        f"/api/v1/jobs/{job_id}",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_unauthorized_access(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/jobs")
    assert resp.status_code == 401

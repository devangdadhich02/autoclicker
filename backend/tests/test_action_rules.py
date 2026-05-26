from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_action_rule(client: AsyncClient, admin_token: str) -> None:
    job_resp = await client.post(
        "/api/v1/jobs",
        json={"name": "Action Test Job", "target_url": "https://example.com"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert job_resp.status_code == 201
    job_id = job_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/jobs/{job_id}/actions",
        json={"name": "Open Inquiry", "action_type": "click", "selector": ".btn-inquiry"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Open Inquiry"
    assert data["action_type"] == "click"
    assert data["selector"] == ".btn-inquiry"
    assert data["execution_count"] == 0


@pytest.mark.asyncio
async def test_list_action_rules(client: AsyncClient, admin_token: str) -> None:
    job_resp = await client.post(
        "/api/v1/jobs",
        json={"name": "List Actions Job", "target_url": "https://example.com"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    job_id = job_resp.json()["id"]

    for i in range(3):
        await client.post(
            f"/api/v1/jobs/{job_id}/actions",
            json={"name": f"Rule {i}", "action_type": "screenshot"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    resp = await client.get(
        f"/api/v1/jobs/{job_id}/actions",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 3


@pytest.mark.asyncio
async def test_update_action_rule(client: AsyncClient, admin_token: str) -> None:
    job_resp = await client.post(
        "/api/v1/jobs",
        json={"name": "Update Action Job", "target_url": "https://example.com"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    job_id = job_resp.json()["id"]

    rule_resp = await client.post(
        f"/api/v1/jobs/{job_id}/actions",
        json={"name": "Old Name", "action_type": "click"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    rule_id = rule_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/jobs/{job_id}/actions/{rule_id}",
        json={"name": "New Name", "action_type": "navigate"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"
    assert resp.json()["action_type"] == "navigate"


@pytest.mark.asyncio
async def test_delete_action_rule(client: AsyncClient, admin_token: str) -> None:
    job_resp = await client.post(
        "/api/v1/jobs",
        json={"name": "Delete Action Job", "target_url": "https://example.com"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    job_id = job_resp.json()["id"]

    rule_resp = await client.post(
        f"/api/v1/jobs/{job_id}/actions",
        json={"name": "Temp Rule", "action_type": "screenshot"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    rule_id = rule_resp.json()["id"]

    del_resp = await client.delete(
        f"/api/v1/jobs/{job_id}/actions/{rule_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 204

    list_resp = await client.get(
        f"/api/v1/jobs/{job_id}/actions",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_action_rule_unauthorized(client: AsyncClient, operator_token: str) -> None:
    resp = await client.post(
        "/api/v1/jobs/nonexistent-id/actions",
        json={"name": "TestRule", "action_type": "click"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert resp.status_code in (403, 404)

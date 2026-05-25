from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_list_keywords(client: AsyncClient, operator_token: str) -> None:
    job_resp = await client.post(
        "/api/v1/jobs",
        json={"name": "KW Test Job", "target_url": "https://example.com"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    job_id = job_resp.json()["id"]

    kw_resp = await client.post(
        f"/api/v1/jobs/{job_id}/keywords",
        json={"value": "steel pipe", "match_type": "contains", "priority": 7},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert kw_resp.status_code == 201
    kw = kw_resp.json()
    assert kw["value"] == "steel pipe"
    assert kw["priority"] == 7

    list_resp = await client.get(
        f"/api/v1/jobs/{job_id}/keywords",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


@pytest.mark.asyncio
async def test_update_keyword(client: AsyncClient, operator_token: str) -> None:
    job_resp = await client.post(
        "/api/v1/jobs",
        json={"name": "KW Update Test", "target_url": "https://example.com"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    job_id = job_resp.json()["id"]

    kw_resp = await client.post(
        f"/api/v1/jobs/{job_id}/keywords",
        json={"value": "copper wire"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    kw_id = kw_resp.json()["id"]

    upd_resp = await client.patch(
        f"/api/v1/jobs/{job_id}/keywords/{kw_id}",
        json={"value": "copper rod", "priority": 9},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert upd_resp.status_code == 200
    assert upd_resp.json()["value"] == "copper rod"


@pytest.mark.asyncio
async def test_delete_keyword(client: AsyncClient, operator_token: str) -> None:
    job_resp = await client.post(
        "/api/v1/jobs",
        json={"name": "KW Del Test", "target_url": "https://example.com"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    job_id = job_resp.json()["id"]

    kw_resp = await client.post(
        f"/api/v1/jobs/{job_id}/keywords",
        json={"value": "to delete"},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    kw_id = kw_resp.json()["id"]

    del_resp = await client.delete(
        f"/api/v1/jobs/{job_id}/keywords/{kw_id}",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert del_resp.status_code == 204

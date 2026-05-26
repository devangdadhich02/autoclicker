from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event_log import EventLog, EventSeverity


async def _seed_logs(db: AsyncSession, job_id: str, count: int = 5) -> None:
    for i in range(count):
        sev = EventSeverity.info if i % 2 == 0 else EventSeverity.warning
        log = EventLog(
            job_id=job_id,
            event_type="keyword_matched",
            severity=sev,
            message=f"Test log entry {i}",
            keyword_matched=f"keyword_{i}",
        )
        db.add(log)
    await db.commit()


@pytest.mark.asyncio
async def test_list_logs_empty(client: AsyncClient, admin_token: str) -> None:
    resp = await client.get(
        "/api/v1/logs",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_list_logs_with_data(
    client: AsyncClient,
    admin_token: str,
    db_session: AsyncSession,
) -> None:
    job_resp = await client.post(
        "/api/v1/jobs",
        json={"name": "Log Test Job", "target_url": "https://example.com"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    job_id = job_resp.json()["id"]
    await _seed_logs(db_session, job_id, count=5)

    resp = await client.get(
        "/api/v1/logs",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) >= 5


@pytest.mark.asyncio
async def test_list_logs_filter_severity(
    client: AsyncClient,
    admin_token: str,
    db_session: AsyncSession,
) -> None:
    job_resp = await client.post(
        "/api/v1/jobs",
        json={"name": "Filter Log Job", "target_url": "https://example.com"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    job_id = job_resp.json()["id"]
    await _seed_logs(db_session, job_id, count=6)

    resp = await client.get(
        "/api/v1/logs?severity=warning",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    for log in resp.json():
        assert log["severity"] == "warning"


@pytest.mark.asyncio
async def test_logs_analytics_summary(
    client: AsyncClient,
    admin_token: str,
    db_session: AsyncSession,
) -> None:
    job_resp = await client.post(
        "/api/v1/jobs",
        json={"name": "Analytics Job", "target_url": "https://example.com"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    job_id = job_resp.json()["id"]
    await _seed_logs(db_session, job_id, count=4)

    resp = await client.get(
        "/api/v1/logs/analytics/summary",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total_jobs" in data
    assert "running_jobs" in data
    assert "total_leads_detected" in data
    assert "severity_breakdown" in data


@pytest.mark.asyncio
async def test_logs_csv_export(
    client: AsyncClient,
    admin_token: str,
    db_session: AsyncSession,
) -> None:
    job_resp = await client.post(
        "/api/v1/jobs",
        json={"name": "CSV Export Job", "target_url": "https://example.com"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    job_id = job_resp.json()["id"]
    await _seed_logs(db_session, job_id, count=3)

    resp = await client.get(
        "/api/v1/logs/export/csv",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    content = resp.text
    assert "severity" in content.lower()

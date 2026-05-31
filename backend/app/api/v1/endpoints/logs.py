from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.api.schemas.event_log import AnalyticsSummary, EventLogResponse
from app.models.event_log import EventSeverity
from app.services.event_log_service import EventLogService
from app.services.job_service import JobService

router = APIRouter()


@router.get("", response_model=list[EventLogResponse])
async def list_logs(
    db: DbSession,
    current_user: CurrentUser,
    job_id: str | None = Query(default=None),
    severity: EventSeverity | None = Query(default=None),
    event_type: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[EventLogResponse]:
    svc = EventLogService(db)
    logs = await svc.list_logs(
        job_id=job_id,
        severity=severity,
        event_type=event_type,
        skip=skip,
        limit=limit,
    )
    return [EventLogResponse.model_validate(log) for log in logs]


@router.get("/analytics/summary", response_model=AnalyticsSummary)
async def get_analytics_summary(
    db: DbSession,
    current_user: CurrentUser,
    job_id: str | None = Query(default=None),
) -> AnalyticsSummary:
    from sqlalchemy import func, select
    from app.models.automation_job import AutomationJob, JobStatus

    job_svc = JobService(db)
    log_svc = EventLogService(db)

    from app.models.user import UserRole
    owner_id = None if current_user.role == UserRole.admin else current_user.id
    all_jobs = await job_svc.list_jobs(owner_id=owner_id, limit=1000)

    severity_breakdown = await log_svc.count_by_severity(job_id=job_id)
    running_jobs = sum(1 for j in all_jobs if j.status == JobStatus.running)
    total_leads = sum(j.total_leads_detected for j in all_jobs)
    total_actions = sum(j.total_actions_executed for j in all_jobs)
    total_errors = sum(j.error_count for j in all_jobs)

    return AnalyticsSummary(
        total_jobs=len(all_jobs),
        running_jobs=running_jobs,
        total_leads_detected=total_leads,
        total_actions_executed=total_actions,
        total_errors=total_errors,
        severity_breakdown=severity_breakdown,
    )


def _flatten_lead_details(details: dict) -> dict:
    if "lead" in details and isinstance(details["lead"], dict):
        return details["lead"]
    return details


@router.delete("/clear")
async def clear_logs(
    db: DbSession,
    _admin: AdminUser,
    job_id: str | None = Query(default=None),
    reset_job_stats: bool = Query(default=True),
    clear_csv_files: bool = Query(default=True),
) -> dict:
    """Delete event logs from DB (optional: one job). Resets counters and lead CSV files."""
    from app.services.lead_store import clear_lead_csv_files

    log_svc = EventLogService(db)
    deleted = await log_svc.delete_all(job_id=job_id)
    jobs_reset = 0
    csv_removed = 0
    if reset_job_stats:
        job_svc = JobService(db)
        jobs_reset = await job_svc.reset_stats(job_id=job_id)
    if clear_csv_files:
        csv_removed = clear_lead_csv_files(job_id=job_id)
    await db.commit()
    return {
        "deleted_logs": deleted,
        "jobs_reset": jobs_reset,
        "csv_files_removed": csv_removed,
    }


@router.get("/export/csv")
async def export_logs_csv(
    db: DbSession,
    current_user: CurrentUser,
    job_id: str | None = Query(default=None),
    severity: EventSeverity | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
) -> StreamingResponse:
    svc = EventLogService(db)
    logs = await svc.list_logs(
        job_id=job_id,
        severity=severity,
        event_type=event_type,
        limit=limit,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "created_at", "job_id", "severity", "event_type", "message", "keyword_matched",
        "product_title", "buyer_name", "buyer_phone", "buyer_email",
        "buyer_location", "buyer_address", "inquiry_message", "context_snippet", "page_url",
    ])
    for log in logs:
        details: dict = {}
        if log.details:
            try:
                details = _flatten_lead_details(json.loads(log.details))
            except Exception:
                pass

        writer.writerow([
            log.created_at.isoformat() if log.created_at else "",
            log.job_id or "",
            log.severity,
            log.event_type,
            log.message,
            log.keyword_matched or "",
            details.get("product_title", ""),
            details.get("buyer_name", ""),
            details.get("buyer_phone", ""),
            details.get("buyer_email", ""),
            details.get("buyer_location", ""),
            details.get("buyer_address", ""),
            details.get("message", details.get("inquiry_message", details.get("text", ""))),
            details.get("context_snippet", ""),
            details.get("page_url", ""),
        ])

    output.seek(0)
    filename = f"velora_logs_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/export/leads/csv")
async def export_leads_csv(
    db: DbSession,
    current_user: CurrentUser,
    job_id: str | None = Query(default=None),
    severity: EventSeverity | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=5000),
) -> StreamingResponse:
    """Export lead events; respects same filters as the logs table."""
    svc = EventLogService(db)
    logs = await svc.list_logs(
        job_id=job_id,
        severity=severity,
        event_type=event_type or None,
        limit=limit,
    )
    lead_types = ("keyword_detected", "lead_extracted")
    if event_type and event_type in lead_types:
        lead_logs = list(logs)
    else:
        lead_logs = [log for log in logs if log.event_type in lead_types]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "created_at", "job_id", "event_type", "keyword_matched", "message",
        "product_title", "buyer_name", "buyer_phone", "buyer_email",
        "buyer_location", "buyer_address", "inquiry_message", "context_snippet", "page_url",
    ])
    for log in lead_logs:
        details: dict = {}
        if log.details:
            try:
                details = _flatten_lead_details(json.loads(log.details))
            except Exception:
                pass
        writer.writerow([
            log.created_at.isoformat() if log.created_at else "",
            log.job_id or "",
            log.event_type,
            log.keyword_matched or "",
            log.message,
            details.get("product_title", ""),
            details.get("buyer_name", ""),
            details.get("buyer_phone", ""),
            details.get("buyer_email", ""),
            details.get("buyer_location", ""),
            details.get("buyer_address", ""),
            details.get("message", details.get("inquiry_message", details.get("text", ""))),
            details.get("context_snippet", ""),
            details.get("page_url", ""),
        ])

    output.seek(0)
    filename = f"velora_leads_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

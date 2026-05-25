from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.event_log import EventSeverity


class EventLogResponse(BaseModel):
    id: str
    job_id: str | None
    severity: EventSeverity
    event_type: str
    message: str
    details: str | None
    screenshot_path: str | None
    keyword_matched: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class LogSeverityCount(BaseModel):
    severity: str
    count: int


class AnalyticsSummary(BaseModel):
    total_jobs: int
    running_jobs: int
    total_leads_detected: int
    total_actions_executed: int
    total_errors: int
    severity_breakdown: dict[str, int]

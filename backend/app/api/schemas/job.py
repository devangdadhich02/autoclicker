from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

from app.models.automation_job import JobStatus


class JobCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    target_url: str = Field(min_length=5, max_length=2048)
    description: str | None = None
    poll_interval_seconds: float = Field(default=5.0, ge=0.1, le=3600)
    browser_profile_name: str | None = None
    scheduler_cron: str | None = None


class JobUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    target_url: str | None = Field(default=None, min_length=5, max_length=2048)
    description: str | None = None
    poll_interval_seconds: float | None = Field(default=None, ge=0.1, le=3600)
    browser_profile_name: str | None = None
    scheduler_cron: str | None = None
    is_active: bool | None = None


class JobResponse(BaseModel):
    id: str
    owner_id: str
    name: str
    description: str | None
    target_url: str
    status: JobStatus
    is_active: bool
    poll_interval_seconds: int
    last_heartbeat: datetime | None
    last_error: str | None
    error_count: int
    restart_count: int
    total_actions_executed: int
    total_leads_detected: int
    browser_profile_name: str | None
    scheduler_cron: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobControlRequest(BaseModel):
    action: str = Field(pattern="^(start|stop|restart)$")

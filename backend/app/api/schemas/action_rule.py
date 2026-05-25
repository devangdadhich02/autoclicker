from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.action_rule import ActionType


class ActionRuleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    action_type: ActionType
    selector: str | None = Field(default=None, max_length=1000)
    fallback_selector: str | None = Field(default=None, max_length=1000)
    target_url: str | None = Field(default=None, max_length=2048)
    payload: str | None = None
    order: int = Field(default=0, ge=0)
    retry_count: int = Field(default=3, ge=1, le=10)
    timeout_ms: int = Field(default=10000, ge=1000, le=60000)
    delay_after_ms: int = Field(default=500, ge=0, le=10000)


class ActionRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    action_type: ActionType | None = None
    selector: str | None = Field(default=None, max_length=1000)
    fallback_selector: str | None = Field(default=None, max_length=1000)
    target_url: str | None = Field(default=None, max_length=2048)
    payload: str | None = None
    order: int | None = Field(default=None, ge=0)
    retry_count: int | None = Field(default=None, ge=1, le=10)
    timeout_ms: int | None = Field(default=None, ge=1000, le=60000)
    delay_after_ms: int | None = Field(default=None, ge=0, le=10000)
    is_active: bool | None = None


class ActionRuleResponse(BaseModel):
    id: str
    job_id: str
    name: str
    action_type: ActionType
    selector: str | None
    fallback_selector: str | None
    target_url: str | None
    payload: str | None
    order: int
    is_active: bool
    retry_count: int
    timeout_ms: int
    delay_after_ms: int
    execution_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

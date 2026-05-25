from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.keyword import MatchType


class KeywordCreate(BaseModel):
    value: str = Field(min_length=1, max_length=500)
    match_type: MatchType = MatchType.contains
    case_sensitive: bool = False
    priority: int = Field(default=5, ge=1, le=10)
    score: float = Field(default=1.0, ge=0.0, le=10.0)
    category: str | None = None
    location_filter: str | None = None
    cooldown_seconds: int = Field(default=300, ge=0)


class KeywordUpdate(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=500)
    match_type: MatchType | None = None
    case_sensitive: bool | None = None
    priority: int | None = Field(default=None, ge=1, le=10)
    score: float | None = Field(default=None, ge=0.0, le=10.0)
    category: str | None = None
    location_filter: str | None = None
    is_active: bool | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0)


class KeywordResponse(BaseModel):
    id: str
    job_id: str
    value: str
    match_type: MatchType
    case_sensitive: bool
    priority: int
    score: float
    category: str | None
    location_filter: str | None
    is_active: bool
    cooldown_seconds: int
    match_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

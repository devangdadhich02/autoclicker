from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LinkedJobSummary(BaseModel):
    id: str
    name: str
    status: str
    target_url: str


class BrowserProfileStatus(BaseModel):
    profile_name: str
    status: str  # missing | incomplete | ready
    status_message: str
    storage_path: str
    file_count: int
    size_bytes: int
    has_cookies: bool
    has_local_storage: bool
    uploaded_at: datetime | None = None
    login_url: str | None = None
    uploaded_from: str | None = None
    last_modified_at: datetime | None = None
    linked_jobs: list[LinkedJobSummary] = []

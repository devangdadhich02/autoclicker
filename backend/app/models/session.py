from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class SessionStatus(str, enum.Enum):
    active = "active"
    idle = "idle"
    crashed = "crashed"
    closed = "closed"
    recovering = "recovering"


class BrowserSession(TimestampMixin, Base):
    __tablename__ = "browser_sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("automation_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus), nullable=False, default=SessionStatus.idle
    )
    browser_type: Mapped[str] = mapped_column(String(50), nullable=False, default="chromium")
    current_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    profile_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_activity: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    crash_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_crash_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cookies_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[AutomationJob] = relationship(  # type: ignore[name-defined]
        "AutomationJob", back_populates="browser_sessions"
    )

    def __repr__(self) -> str:
        return f"<BrowserSession id={self.id} job={self.job_id} status={self.status}>"

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class JobStatus(str, enum.Enum):
    idle = "idle"
    running = "running"
    paused = "paused"
    error = "error"
    stopped = "stopped"
    recovering = "recovering"


class AutomationJob(TimestampMixin, Base):
    __tablename__ = "automation_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), nullable=False, default=JobStatus.idle
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    last_heartbeat: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    restart_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_actions_executed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_leads_detected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    browser_profile_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scheduler_cron: Mapped[str | None] = mapped_column(String(100), nullable=True)

    owner: Mapped[User] = relationship("User", back_populates="automation_jobs")  # type: ignore[name-defined]
    keywords: Mapped[list[Keyword]] = relationship(  # type: ignore[name-defined]
        "Keyword", back_populates="job", cascade="all, delete-orphan"
    )
    action_rules: Mapped[list[ActionRule]] = relationship(  # type: ignore[name-defined]
        "ActionRule", back_populates="job", cascade="all, delete-orphan"
    )
    event_logs: Mapped[list[EventLog]] = relationship(  # type: ignore[name-defined]
        "EventLog", back_populates="job", cascade="all, delete-orphan"
    )
    browser_sessions: Mapped[list[BrowserSession]] = relationship(  # type: ignore[name-defined]
        "BrowserSession", back_populates="job", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<AutomationJob id={self.id} name={self.name} status={self.status}>"

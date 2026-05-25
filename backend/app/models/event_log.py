from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class EventSeverity(str, enum.Enum):
    debug = "debug"
    info = "info"
    warning = "warning"
    error = "error"
    critical = "critical"


class EventLog(TimestampMixin, Base):
    __tablename__ = "event_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("automation_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    severity: Mapped[EventSeverity] = mapped_column(
        Enum(EventSeverity), nullable=False, default=EventSeverity.info
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    keyword_matched: Mapped[str | None] = mapped_column(String(500), nullable=True)

    job: Mapped[AutomationJob | None] = relationship(  # type: ignore[name-defined]
        "AutomationJob", back_populates="event_logs"
    )

    def __repr__(self) -> str:
        return f"<EventLog id={self.id} type={self.event_type} severity={self.severity}>"

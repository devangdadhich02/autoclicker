from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ActionType(str, enum.Enum):
    click = "click"
    navigate = "navigate"
    fill_form = "fill_form"
    extract_text = "extract_text"
    screenshot = "screenshot"
    wait = "wait"
    scroll = "scroll"
    webhook = "webhook"
    notify = "notify"
    mark_important = "mark_important"
    open_inquiry = "open_inquiry"
    copy_lead = "copy_lead"


class ActionRule(TimestampMixin, Base):
    __tablename__ = "action_rules"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("automation_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    action_type: Mapped[ActionType] = mapped_column(Enum(ActionType), nullable=False)
    selector: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    fallback_selector: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    target_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    delay_after_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    execution_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    job: Mapped[AutomationJob] = relationship(  # type: ignore[name-defined]
        "AutomationJob", back_populates="action_rules"
    )

    def __repr__(self) -> str:
        return f"<ActionRule id={self.id} type={self.action_type} name={self.name!r}>"

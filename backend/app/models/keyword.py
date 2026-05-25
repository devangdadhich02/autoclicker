from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class MatchType(str, enum.Enum):
    exact = "exact"
    contains = "contains"
    regex = "regex"
    starts_with = "starts_with"
    ends_with = "ends_with"


class Keyword(TimestampMixin, Base):
    __tablename__ = "keywords"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("automation_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    match_type: Mapped[MatchType] = mapped_column(
        Enum(MatchType), nullable=False, default=MatchType.contains
    )
    case_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    location_filter: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    match_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    job: Mapped[AutomationJob] = relationship(  # type: ignore[name-defined]
        "AutomationJob", back_populates="keywords"
    )

    def __repr__(self) -> str:
        return f"<Keyword id={self.id} value={self.value!r} type={self.match_type}>"

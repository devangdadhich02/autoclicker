from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, MappedColumn, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


class TimestampMixin:
    """Adds created_at / updated_at to any model."""

    created_at: MappedColumn[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: MappedColumn[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

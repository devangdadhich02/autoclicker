from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, MappedColumn, mapped_column
from sqlalchemy import Integer, DateTime, func
from datetime import datetime


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
        onupdate=func.now(),
        nullable=False,
    )

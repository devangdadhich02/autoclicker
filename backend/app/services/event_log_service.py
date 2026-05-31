from __future__ import annotations

from sqlalchemy import delete, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event_log import EventLog, EventSeverity


class EventLogService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        event_type: str,
        message: str,
        severity: EventSeverity = EventSeverity.info,
        job_id: str | None = None,
        details: str | None = None,
        screenshot_path: str | None = None,
        keyword_matched: str | None = None,
    ) -> EventLog:
        log = EventLog(
            job_id=job_id,
            severity=severity,
            event_type=event_type,
            message=message,
            details=details,
            screenshot_path=screenshot_path,
            keyword_matched=keyword_matched,
        )
        self._db.add(log)
        await self._db.flush()
        return log

    async def list_logs(
        self,
        job_id: str | None = None,
        severity: EventSeverity | None = None,
        event_type: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[EventLog]:
        query = select(EventLog)
        if job_id:
            query = query.where(EventLog.job_id == job_id)
        if severity:
            query = query.where(EventLog.severity == severity)
        if event_type:
            query = query.where(EventLog.event_type == event_type)
        query = query.order_by(desc(EventLog.created_at)).offset(skip).limit(limit)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def count_by_severity(self, job_id: str | None = None) -> dict[str, int]:
        from sqlalchemy import func
        query = select(EventLog.severity, func.count(EventLog.id).label("cnt"))
        if job_id:
            query = query.where(EventLog.job_id == job_id)
        query = query.group_by(EventLog.severity)
        result = await self._db.execute(query)
        return {row.severity: row.cnt for row in result}

    async def delete_all(self, job_id: str | None = None) -> int:
        stmt = delete(EventLog)
        if job_id:
            stmt = stmt.where(EventLog.job_id == job_id)
        result = await self._db.execute(stmt)
        return result.rowcount or 0

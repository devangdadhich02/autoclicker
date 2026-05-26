from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.keyword import Keyword, MatchType


class KeywordService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_id(self, keyword_id: str) -> Keyword:
        result = await self._db.execute(select(Keyword).where(Keyword.id == keyword_id))
        kw = result.scalar_one_or_none()
        if kw is None:
            raise NotFoundError("Keyword", keyword_id)
        return kw

    async def list_for_job(self, job_id: str, active_only: bool = False) -> list[Keyword]:
        query = select(Keyword).where(Keyword.job_id == job_id)
        if active_only:
            query = query.where(Keyword.is_active.is_(True))
        query = query.order_by(Keyword.priority.desc(), Keyword.created_at)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        job_id: str,
        value: str,
        match_type: MatchType = MatchType.contains,
        case_sensitive: bool = False,
        priority: int = 5,
        score: float = 1.0,
        category: str | None = None,
        location_filter: str | None = None,
        cooldown_seconds: int = 300,
    ) -> Keyword:
        kw = Keyword(
            job_id=job_id,
            value=value,
            match_type=match_type,
            case_sensitive=case_sensitive,
            priority=priority,
            score=score,
            category=category,
            location_filter=location_filter,
            cooldown_seconds=cooldown_seconds,
        )
        self._db.add(kw)
        await self._db.flush()
        await self._db.refresh(kw)
        return kw

    async def update(self, keyword_id: str, **fields: object) -> Keyword:
        kw = await self.get_by_id(keyword_id)
        allowed = {
            "value", "match_type", "case_sensitive", "priority", "score",
            "category", "location_filter", "is_active", "cooldown_seconds",
        }
        for key, value in fields.items():
            if key in allowed:
                setattr(kw, key, value)
        await self._db.flush()
        await self._db.refresh(kw)
        return kw

    async def delete(self, keyword_id: str) -> None:
        kw = await self.get_by_id(keyword_id)
        await self._db.delete(kw)
        await self._db.flush()

    async def increment_match_count(self, keyword_id: str) -> None:
        kw = await self.get_by_id(keyword_id)
        kw.match_count += 1
        await self._db.flush()

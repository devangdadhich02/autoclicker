from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AuthorizationError, NotFoundError
from app.models.automation_job import AutomationJob, JobStatus
from app.models.user import User, UserRole


class JobService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_id(self, job_id: str, with_relations: bool = False) -> AutomationJob:
        query = select(AutomationJob).where(AutomationJob.id == job_id)
        if with_relations:
            query = query.options(
                selectinload(AutomationJob.keywords),
                selectinload(AutomationJob.action_rules),
                selectinload(AutomationJob.browser_sessions),
            )
        result = await self._db.execute(query)
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundError("AutomationJob", job_id)
        return job

    async def get_by_id_authorized(
        self, job_id: str, current_user: User, with_relations: bool = False
    ) -> AutomationJob:
        job = await self.get_by_id(job_id, with_relations)
        if current_user.role != UserRole.admin and job.owner_id != current_user.id:
            raise AuthorizationError()
        return job

    async def list_jobs(
        self,
        owner_id: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[AutomationJob]:
        query = select(AutomationJob)
        if owner_id:
            query = query.where(AutomationJob.owner_id == owner_id)
        query = query.offset(skip).limit(limit).order_by(AutomationJob.created_at.desc())
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        owner_id: str,
        name: str,
        target_url: str,
        description: str | None = None,
        poll_interval_seconds: int = 15,
        browser_profile_name: str | None = None,
        scheduler_cron: str | None = None,
    ) -> AutomationJob:
        job = AutomationJob(
            owner_id=owner_id,
            name=name,
            target_url=target_url,
            description=description,
            poll_interval_seconds=poll_interval_seconds,
            browser_profile_name=browser_profile_name,
            scheduler_cron=scheduler_cron,
        )
        self._db.add(job)
        await self._db.flush()
        return job

    async def update(self, job_id: str, current_user: User, **fields: object) -> AutomationJob:
        job = await self.get_by_id_authorized(job_id, current_user)
        allowed = {
            "name", "description", "target_url", "poll_interval_seconds",
            "browser_profile_name", "scheduler_cron", "is_active",
        }
        for key, value in fields.items():
            if key in allowed:
                setattr(job, key, value)
        await self._db.flush()
        return job

    async def set_status(self, job_id: str, status: JobStatus) -> AutomationJob:
        job = await self.get_by_id(job_id)
        job.status = status
        await self._db.flush()
        return job

    async def delete(self, job_id: str, current_user: User) -> None:
        job = await self.get_by_id_authorized(job_id, current_user)
        await self._db.delete(job)
        await self._db.flush()

    async def record_heartbeat(self, job_id: str) -> None:
        from datetime import UTC, datetime
        job = await self.get_by_id(job_id)
        job.last_heartbeat = datetime.now(UTC)
        await self._db.flush()

    async def increment_action_count(self, job_id: str) -> None:
        job = await self.get_by_id(job_id)
        job.total_actions_executed += 1
        await self._db.flush()

    async def increment_lead_count(self, job_id: str) -> None:
        job = await self.get_by_id(job_id)
        job.total_leads_detected += 1
        await self._db.flush()

    async def record_error(self, job_id: str, error_message: str) -> None:
        job = await self.get_by_id(job_id)
        job.last_error = error_message
        job.error_count += 1
        job.status = JobStatus.error
        await self._db.flush()

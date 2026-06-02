from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.models.automation_job import AutomationJob, JobStatus
from app.models.event_log import EventSeverity

logger = get_logger(__name__)


class WatchdogService:
    """
    Monitors running automation jobs for heartbeat timeouts and triggers
    auto-recovery by requesting restarts via the scheduler.
    """

    def __init__(self, scheduler: object) -> None:
        self._scheduler = scheduler  # Reference to AutomationScheduler
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("Watchdog started", interval=settings.WATCHDOG_CHECK_INTERVAL_SECONDS)
        while self._running:
            try:
                await self._check_all_jobs()
            except Exception as exc:
                logger.error("Watchdog check failed", error=str(exc))
            await asyncio.sleep(settings.WATCHDOG_CHECK_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self._running = False
        logger.info("Watchdog stopped")

    async def _check_all_jobs(self) -> None:
        factory = get_session_factory()
        async with factory() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(AutomationJob).where(
                    AutomationJob.is_active.is_(True),
                    AutomationJob.status == JobStatus.running,
                )
            )
            running_jobs = list(result.scalars().all())

        now = datetime.now(UTC)
        for job in running_jobs:
            if job.last_heartbeat is None:
                continue
            # Ignore stale heartbeat carried over from previous process/runtime.
            # If the job was just updated recently, runner may be booting and has
            # not recorded first heartbeat in this process yet.
            updated_at = job.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=UTC)
            if (now - updated_at).total_seconds() < max(
                90, int(settings.WATCHDOG_CHECK_INTERVAL_SECONDS * 2)
            ):
                continue
            elapsed = (now - job.last_heartbeat.replace(tzinfo=UTC)).total_seconds()
            if elapsed > settings.HEARTBEAT_TIMEOUT_SECONDS:
                logger.warning(
                    "Heartbeat timeout detected",
                    job_id=job.id,
                    elapsed_seconds=elapsed,
                )
                await self._trigger_recovery(job)

    async def _trigger_recovery(self, job: AutomationJob) -> None:
        from app.services.event_log_service import EventLogService
        factory = get_session_factory()
        async with factory() as db:
            log_svc = EventLogService(db)
            await log_svc.create(
                event_type="watchdog_recovery",
                message=f"Heartbeat timeout for job '{job.name}'. Triggering auto-recovery.",
                severity=EventSeverity.warning,
                job_id=job.id,
            )
            await db.commit()

        # Request scheduler to restart the job
        await self._scheduler.restart_job(job.id)  # type: ignore[attr-defined]

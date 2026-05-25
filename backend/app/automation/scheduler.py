from __future__ import annotations

import asyncio
from typing import Any

from app.automation.job_runner import JobRunner
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.models.automation_job import AutomationJob, JobStatus

logger = get_logger(__name__)


class AutomationScheduler:
    """
    Manages the lifecycle of all JobRunner instances.
    Provides start, stop, restart, and status APIs.
    Thread-safe using asyncio lock.
    """

    def __init__(self) -> None:
        self._runners: dict[str, JobRunner] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()

    async def start_job(self, job_id: str) -> None:
        async with self._lock:
            if job_id in self._runners and self._runners[job_id].is_running:
                logger.warning("Job already running", job_id=job_id)
                return

            runner = JobRunner(job_id)
            self._runners[job_id] = runner
            task = asyncio.create_task(runner.start(), name=f"job_{job_id}")
            self._tasks[job_id] = task
            task.add_done_callback(lambda t: self._on_task_done(job_id, t))

            logger.info("Job started", job_id=job_id)

    def _on_task_done(self, job_id: str, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            logger.info("Job task cancelled", job_id=job_id)
        elif task.exception() is not None:
            logger.error("Job task raised exception", job_id=job_id, error=str(task.exception()))
        self._runners.pop(job_id, None)
        self._tasks.pop(job_id, None)

    async def stop_job(self, job_id: str) -> None:
        async with self._lock:
            runner = self._runners.get(job_id)
            if runner is None:
                logger.warning("No runner found to stop", job_id=job_id)
                return
            await runner.stop()
            task = self._tasks.get(job_id)
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=10.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            logger.info("Job stopped", job_id=job_id)

    async def restart_job(self, job_id: str) -> None:
        logger.info("Restarting job", job_id=job_id)
        await self.stop_job(job_id)
        await asyncio.sleep(2)
        await self.start_job(job_id)

    def is_running(self, job_id: str) -> bool:
        runner = self._runners.get(job_id)
        return runner is not None and runner.is_running

    def list_running(self) -> list[str]:
        return [jid for jid, r in self._runners.items() if r.is_running]

    async def startup_active_jobs(self) -> None:
        """Auto-start all previously active jobs on application startup."""
        factory = get_session_factory()
        async with factory() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(AutomationJob).where(
                    AutomationJob.is_active.is_(True),
                    AutomationJob.status.in_([JobStatus.running, JobStatus.recovering]),
                )
            )
            jobs = list(result.scalars().all())

        for job in jobs:
            logger.info("Auto-starting job on boot", job_id=job.id, name=job.name)
            await self.start_job(job.id)

    async def shutdown_all(self) -> None:
        job_ids = list(self._runners.keys())
        for job_id in job_ids:
            await self.stop_job(job_id)
        logger.info("All jobs stopped")

    def get_status(self) -> dict[str, bool]:
        return {jid: r.is_running for jid, r in self._runners.items()}


# Singleton instance shared across the app
_scheduler: AutomationScheduler | None = None


def get_scheduler() -> AutomationScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AutomationScheduler()
    return _scheduler

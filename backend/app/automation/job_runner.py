from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime
from typing import Any

from app.automation.action_engine import ActionEngine
from app.automation.browser_manager import BrowserManager
from app.automation.detection_engine import DetectionEngine
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.models.automation_job import AutomationJob, JobStatus
from app.models.event_log import EventSeverity
from app.models.keyword import Keyword
from app.models.action_rule import ActionRule
from app.services.event_log_service import EventLogService
from app.services.job_service import JobService
from app.services.keyword_service import KeywordService

# URL patterns that indicate session has expired / login required
_LOGIN_URL_PATTERNS = [
    "login", "signin", "sign-in", "auth", "session", "logout",
    "account/login", "user/login", "sso", "oauth", "reauthenticate",
    # IndiaMART specific
    "seller.indiamart.com/login", "indiamart.com/login",
    "indiamart.com/signin",
]

# Page title / body text patterns that indicate login wall
_LOGIN_PAGE_TEXT_PATTERNS = [
    "please login", "please sign in", "session expired",
    "your session has expired", "log in to continue",
    "sign in to continue", "login to continue", "login required",
    "please log in",
]

logger = get_logger(__name__)


class JobRunner:
    """
    Orchestrates a single automation job:
    - Launches and manages the browser session
    - Polls for keyword/lead detection
    - Triggers action chains on detection
    - Handles graceful shutdown and crash recovery
    """

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self._browser: BrowserManager | None = None
        self._detection = DetectionEngine(job_id)
        self._shutdown_event = asyncio.Event()
        self._is_running = False
        self._last_heartbeat: datetime | None = None
        self._poll_interval = settings.DEFAULT_POLL_INTERVAL_SECONDS
        self._browser_created_at: datetime | None = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def start(self) -> None:
        if self._is_running:
            logger.warning("JobRunner already running", job_id=self.job_id)
            return

        self._is_running = True
        self._shutdown_event.clear()

        logger.info("JobRunner starting", job_id=self.job_id)
        await self._update_status(JobStatus.running)

        try:
            await self._run_loop()
        except asyncio.CancelledError:
            logger.info("JobRunner cancelled", job_id=self.job_id)
        except Exception as exc:
            logger.error("JobRunner fatal error", job_id=self.job_id, error=str(exc))
            await self._log_event("job_fatal_error", str(exc), EventSeverity.critical)
            await self._update_status(JobStatus.error)
        finally:
            await self._cleanup()

    async def stop(self) -> None:
        logger.info("JobRunner stop requested", job_id=self.job_id)
        self._shutdown_event.set()

    async def _run_loop(self) -> None:
        restart_delay = 5.0

        while not self._shutdown_event.is_set():
            try:
                job = await self._load_job()
                if not job.is_active:
                    logger.info("Job is inactive, stopping", job_id=self.job_id)
                    break

                self._poll_interval = job.poll_interval_seconds
                browser = await self._get_or_create_browser(job)
                keywords = await self._load_keywords()
                action_rules = await self._load_action_rules()

                await self._poll_cycle(browser, job, keywords, action_rules)
                await self._heartbeat()
                await self._maybe_recycle_browser()

                restart_delay = 5.0  # reset on success

                jitter = random.uniform(0, self._poll_interval * 0.2)
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._poll_interval + jitter,
                )
                break  # shutdown was set

            except asyncio.TimeoutError:
                # Normal: poll interval elapsed, continue loop
                continue
            except Exception as exc:
                logger.error(
                    "Poll cycle error, restarting",
                    job_id=self.job_id,
                    error=str(exc),
                    restart_delay=restart_delay,
                )
                await self._update_status(JobStatus.recovering)
                await self._log_event("job_cycle_error", str(exc), EventSeverity.error)
                await asyncio.sleep(restart_delay)
                restart_delay = min(restart_delay * 2, 120)

                if self._browser:
                    try:
                        await self._browser.restart()
                    except Exception:
                        self._browser = None

    async def _poll_cycle(
        self,
        browser: BrowserManager,
        job: AutomationJob,
        keywords: list[Keyword],
        action_rules: list[ActionRule],
    ) -> None:
        page = await browser.get_page()

        # Check if still on the right page, navigate if needed
        try:
            current_url = page.url
            if not current_url or current_url == "about:blank":
                await browser.navigate(job.target_url)
        except Exception as exc:
            logger.warning("URL check failed, navigating", job_id=self.job_id, error=str(exc))
            await browser.navigate(job.target_url)

        # ── Session Expiry Detection ─────────────────────────────────────────
        current_url = page.url.lower()
        if await self._is_session_expired(page, current_url):
            await self._handle_session_expired(current_url)
            return
        # ────────────────────────────────────────────────────────────────────

        if not keywords:
            return

        # Collect visible text from page
        try:
            page_text = await page.evaluate("() => document.body.innerText || ''")
        except Exception as exc:
            logger.warning("Failed to get page text", job_id=self.job_id, error=str(exc))
            return

        # Run detection
        results = self._detection.evaluate(page_text, keywords)

        if results:
            logger.info(
                "Keywords detected",
                job_id=self.job_id,
                count=len(results),
                top=results[0].keyword_value,
            )
            for result in results:
                await self._log_event(
                    "keyword_detected",
                    f"Keyword '{result.keyword_value}' matched: {result.context_snippet[:200]}",
                    EventSeverity.info,
                    keyword_matched=result.keyword_value,
                )
                await self._increment_lead()

            # Execute action chain
            if action_rules:
                action_engine = ActionEngine(self.job_id, browser)
                exec_results = await action_engine.execute_chain(action_rules)
                success_count = sum(exec_results)
                await self._increment_action(success_count)
                logger.info(
                    "Actions executed",
                    job_id=self.job_id,
                    success=success_count,
                    total=len(exec_results),
                )

    async def _is_session_expired(self, page: Any, current_url: str) -> bool:
        """Returns True if the browser has been redirected to a login page."""
        # Check URL patterns
        for pattern in _LOGIN_URL_PATTERNS:
            if pattern in current_url:
                return True
        # Check page text for login wall messages
        try:
            page_text = await page.evaluate("() => (document.body.innerText || '').toLowerCase()")
            for pattern in _LOGIN_PAGE_TEXT_PATTERNS:
                if pattern in page_text:
                    return True
        except Exception:
            pass
        return False

    async def _handle_session_expired(self, current_url: str) -> None:
        """Log critical alert and pause the job so seller knows to re-login."""
        msg = (
            f"Session expired — browser redirected to login page ({current_url}). "
            "Please re-run the login script: "
            "docker compose exec backend python scripts/login_browser.py "
            f"--profile <profile_name> --url <target_url>"
        )
        logger.critical(
            "SESSION EXPIRED — job paused, re-login required",
            job_id=self.job_id,
            redirect_url=current_url,
        )
        await self._log_event(
            event_type="session_expired",
            message=msg,
            severity=EventSeverity.critical,
        )
        # Pause job — set to error so dashboard shows it clearly
        await self._update_status(JobStatus.error)
        # Stop the runner so it doesn't keep looping uselessly
        self._shutdown_event.set()

    async def _get_or_create_browser(self, job: AutomationJob) -> BrowserManager:
        if self._browser is None or not self._browser.is_alive:
            self._browser = BrowserManager(
                job_id=self.job_id,
                profile_name=job.browser_profile_name,
            )
            await self._browser.launch()
            self._browser_created_at = datetime.now(UTC)

        return self._browser

    async def _maybe_recycle_browser(self) -> None:
        if self._browser_created_at is None:
            return
        elapsed_hours = (datetime.now(UTC) - self._browser_created_at).total_seconds() / 3600
        if elapsed_hours >= settings.BROWSER_RECYCLE_INTERVAL_HOURS:
            logger.info("Recycling browser (interval reached)", job_id=self.job_id)
            await self._log_event("browser_recycled", "Periodic browser recycle", EventSeverity.info)
            await self._browser.restart()  # type: ignore[union-attr]
            self._browser_created_at = datetime.now(UTC)

    async def _heartbeat(self) -> None:
        self._last_heartbeat = datetime.now(UTC)
        factory = get_session_factory()
        async with factory() as db:
            svc = JobService(db)
            await svc.record_heartbeat(self.job_id)
            await db.commit()

    async def _update_status(self, status: JobStatus) -> None:
        factory = get_session_factory()
        async with factory() as db:
            svc = JobService(db)
            await svc.set_status(self.job_id, status)
            await db.commit()

    async def _log_event(
        self,
        event_type: str,
        message: str,
        severity: EventSeverity,
        keyword_matched: str | None = None,
    ) -> None:
        factory = get_session_factory()
        async with factory() as db:
            svc = EventLogService(db)
            await svc.create(
                event_type=event_type,
                message=message,
                severity=severity,
                job_id=self.job_id,
                keyword_matched=keyword_matched,
            )
            await db.commit()

    async def _load_job(self) -> AutomationJob:
        factory = get_session_factory()
        async with factory() as db:
            svc = JobService(db)
            return await svc.get_by_id(self.job_id)

    async def _load_keywords(self) -> list[Keyword]:
        factory = get_session_factory()
        async with factory() as db:
            svc = KeywordService(db)
            return await svc.list_for_job(self.job_id, active_only=True)

    async def _load_action_rules(self) -> list[ActionRule]:
        from sqlalchemy import select
        factory = get_session_factory()
        async with factory() as db:
            from app.models.action_rule import ActionRule as AR
            result = await db.execute(
                select(AR).where(AR.job_id == self.job_id, AR.is_active.is_(True)).order_by(AR.order)
            )
            return list(result.scalars().all())

    async def _increment_lead(self) -> None:
        factory = get_session_factory()
        async with factory() as db:
            svc = JobService(db)
            await svc.increment_lead_count(self.job_id)
            await db.commit()

    async def _increment_action(self, count: int) -> None:
        if count <= 0:
            return
        factory = get_session_factory()
        async with factory() as db:
            svc = JobService(db)
            for _ in range(count):
                await svc.increment_action_count(self.job_id)
            await db.commit()

    async def _cleanup(self) -> None:
        self._is_running = False
        if self._browser:
            await self._browser.close()
            self._browser = None
        try:
            await self._update_status(JobStatus.stopped)
        except Exception:
            pass
        logger.info("JobRunner cleaned up", job_id=self.job_id)

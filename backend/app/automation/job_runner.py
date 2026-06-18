from __future__ import annotations

import asyncio
import contextlib
import json
import random
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.automation.action_engine import ActionEngine
from app.automation.browser_manager import BrowserManager
from app.automation.detection_engine import DetectionEngine
from app.automation.indiamart_leads import (
    BuyerLeadBlock,
    _read_detail_panel_text,
    click_buyer_lead_block,
    collect_buyer_lead_blocks,
    extract_buyer_details,
    is_weak_match_context,
    lead_identity_matches,
    lead_fingerprint,
    lead_has_buyer_contact,
    lead_match_text,
    lead_record_is_complete,
)
from app.automation.indiamart_page import (
    INDIAMART_LEADS_URL,
    collect_inquiry_text,
    ensure_bltxn_leads_page,
    is_indiamart_logged_out_body,
    is_indiamart_login_url,
    is_indiamart_marketing_landing,
    is_indiamart_seller_url,
    read_indiamart_page_text,
    scroll_lead_list,
    seller_session_is_authenticated,
    wait_for_page_ready,
)
from app.automation.profile_cookies import load_portable_cookies
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.models.action_rule import ActionRule
from app.models.automation_job import AutomationJob, JobStatus
from app.models.event_log import EventSeverity
from app.models.keyword import Keyword
from app.services.event_log_service import EventLogService
from app.services.job_service import JobService
from app.services.keyword_service import KeywordService

# Cap leads processed per poll so contact reveal + heartbeat stay within watchdog budget.
_MAX_LEADS_PER_SCAN = 10
_PARTIAL_CONTACT_RETRY_SECONDS = 10 * 60
_CLICK_FAILURE_RETRY_SECONDS = 45

# URL path patterns that indicate session has expired (avoid broad "auth" substring)
_LOGIN_URL_PATTERNS = [
    "/login", "/signin", "/sign-in", "/logout",
    "account/login", "user/login", "sso/login", "oauth",
    "reauthenticate", "session-expired",
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


@dataclass
class QueuedIndiaMartLead:
    block: BuyerLeadBlock
    keyword_id: str
    keyword_value: str
    priority: int
    score: float
    fingerprint: str
    queued_at: datetime


class PageScopedBrowser:
    """Tiny ActionEngine adapter so action rules run on the action page, not scanner page."""

    def __init__(self, base: BrowserManager, page: Any) -> None:
        self._base = base
        self._page = page

    async def get_page(self) -> Any:
        return self._page

    async def screenshot(self, label: str = "") -> Any:
        return await self._base.screenshot(label)

    async def navigate(self, url: str) -> None:
        await self._page.goto(url, wait_until="domcontentloaded")


def _indiamart_recent_leads_url(target_url: str | None = None) -> str:
    """Always scan the Recent Buy Leads feed, even if a saved job still says relevant."""
    target = (target_url or "").lower()
    if "seller.indiamart.com" not in target:
        return INDIAMART_LEADS_URL
    if "bltxn" in target and "pref=recent" in target:
        return target_url or INDIAMART_LEADS_URL
    return INDIAMART_LEADS_URL


def _is_non_recent_indiamart_feed(url: str | None) -> bool:
    u = (url or "").lower()
    return "seller.indiamart.com" in u and "bltxn" in u and any(
        marker in u
        for marker in (
            "pref=relevant",
            "pref=other_leads",
            "pref=all",
            "/buyersearch/",
            "screen=view_similar_leads",
            "view_similar_leads",
        )
    )


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
        self._seen_lead_fingerprints: set[str] = set()
        self._partial_contact_retry_until: dict[str, datetime] = {}
        self._layout_alert_keys: set[str] = set()
        self._last_deep_indiamart_scan_at: datetime | None = None
        self._indiamart_lead_queue: list[QueuedIndiaMartLead] = []
        self._queued_lead_fingerprints: set[str] = set()
        self._indiamart_action_task: asyncio.Task[Any] | None = None
        self._indiamart_action_warm_task: asyncio.Task[Any] | None = None
        self._indiamart_action_page: Any | None = None
        self._indiamart_action_page_ready = False
        self._indiamart_action_lock = asyncio.Lock()

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
            job = await self._load_job()
            from app.services.lead_store import load_seen_lead_fingerprints

            self._seen_lead_fingerprints = load_seen_lead_fingerprints(
                self.job_id, job.name
            )
            logger.info(
                "Loaded lead dedup keys",
                job_id=self.job_id,
                count=len(self._seen_lead_fingerprints),
            )
        except Exception:
            self._seen_lead_fingerprints = set()

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
                if is_indiamart_seller_url(job.target_url):
                    self._poll_interval = min(
                        float(job.poll_interval_seconds),
                        settings.INDIAMART_FAST_SCAN_INTERVAL_SECONDS,
                    )
                # Heartbeat before slow navigation so watchdog does not kill the job
                await self._heartbeat()

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

            except TimeoutError:
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
                        self._indiamart_action_page = None
                        self._indiamart_action_page_ready = False
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

        await self._ensure_on_target_page(browser, job, page)

        current_url = page.url.lower()
        if await self._is_session_expired(page, current_url):
            await self._handle_session_expired(current_url)
            return

        if not keywords:
            logger.warning(
                "No active keywords — job cannot detect leads. Add keywords in dashboard.",
                job_id=self.job_id,
            )
            return
        logger.info(
            "Active keywords loaded",
            job_id=self.job_id,
            count=len(keywords),
            keywords=[
                {
                    "value": (k.value or "")[:80],
                    "match_type": str(getattr(k, "match_type", "")),
                    "active": bool(getattr(k, "is_active", False)),
                    "case_sensitive": bool(getattr(k, "case_sensitive", False)),
                }
                for k in keywords[:20]
            ],
        )

        page_url = page.url
        if is_indiamart_seller_url(job.target_url):
            await self._process_indiamart_leads(
                page, job, keywords, action_rules, browser, page_url
            )
            return

        page_text = await self._collect_page_text(page, job.target_url)
        if not page_text.strip():
            logger.warning("Empty page text after load", job_id=self.job_id, url=page.url)
            return

        results = self._detection.evaluate(page_text, keywords)
        if not results:
            logger.info(
                "No keyword match this scan",
                job_id=self.job_id,
                text_chars=len(page_text),
                keyword_count=len(keywords),
                url=page.url,
            )
            return

        await self._handle_detection_results(
            results, job, browser, action_rules, page_url, page_text[:500]
        )

    async def _process_indiamart_leads(
        self,
        page: Any,
        job: AutomationJob,
        keywords: list[Keyword],
        action_rules: list[ActionRule],
        browser: BrowserManager,
        page_url: str,
    ) -> None:
        """Only real buyer inquiry rows — extract name/phone/message before counting a lead."""
        await self._heartbeat()
        if not await seller_session_is_authenticated(page):
            portable = load_portable_cookies(browser.profile_path)
            if portable:
                try:
                    await browser.restore_cookies(portable)
                    leads_url = _indiamart_recent_leads_url(job.target_url)
                    await ensure_bltxn_leads_page(
                        page, leads_url, heartbeat=self._heartbeat
                    )
                    if await seller_session_is_authenticated(page):
                        logger.info(
                            "Session restored from portable cookies",
                            job_id=self.job_id,
                        )
                    else:
                        portable = []
                except Exception:
                    portable = []
            if not portable or not await seller_session_is_authenticated(page):
                try:
                    full = await page.evaluate("() => document.body.innerText || ''")
                except Exception:
                    full = ""
                logger.warning(
                    "IndiaMART cookies not active in browser — public page shown",
                    job_id=self.job_id,
                    url=page.url,
                    preview=full[:220],
                )
                await self._handle_session_expired(page.url)
                return
        if _is_non_recent_indiamart_feed(page.url):
            leads_url = _indiamart_recent_leads_url(job.target_url)
            logger.warning(
                "IndiaMART non-recent feed detected before scan — forcing Recent",
                job_id=self.job_id,
                url=page.url,
            )
            await ensure_bltxn_leads_page(page, leads_url, heartbeat=self._heartbeat)
            if _is_non_recent_indiamart_feed(page.url):
                logger.warning(
                    "IndiaMART non-recent feed still open — skipping scan to avoid wrong leads",
                    job_id=self.job_id,
                    url=page.url,
                )
                return
        if _is_non_recent_indiamart_feed(page.url):
            leads_url = _indiamart_recent_leads_url(job.target_url)
            logger.info(
                "Continuing scan on visible IndiaMART feed after SPA recovery",
                job_id=self.job_id,
                target_url=leads_url,
                url=page.url,
            )
        now = datetime.now(UTC)
        deep_scan_due = (
            self._last_deep_indiamart_scan_at is None
            or (
                now - self._last_deep_indiamart_scan_at
            ).total_seconds() >= settings.INDIAMART_DEEP_SCAN_INTERVAL_SECONDS
        )
        blocks = await collect_buyer_lead_blocks(
            page,
            max_blocks=25 if deep_scan_due else 12,
            visible_only=not deep_scan_due,
        )
        if deep_scan_due:
            self._last_deep_indiamart_scan_at = now
        if not blocks:
            # Single consolidated re-navigation attempt
            leads_url = _indiamart_recent_leads_url(job.target_url)
            await ensure_bltxn_leads_page(page, leads_url, heartbeat=self._heartbeat)
            blocks = await collect_buyer_lead_blocks(page, max_blocks=25)
            self._last_deep_indiamart_scan_at = datetime.now(UTC)
        if not blocks:
            diag = ""
            snippet = ""
            has_ago = False
            try:
                snippet = await read_indiamart_page_text(page)
                has_ago = bool(
                    re.search(
                        r"(?:just\s+now|\d+\s*(?:min|mins|hr|hrs|hour|hours|day|days)\s*ago)",
                        snippet,
                        re.I,
                    )
                )
                diag = f" body_has_time_ago={has_ago} preview={snippet[:200]!r}"
            except Exception:
                diag = ""
            logger.info(
                "No buyer inquiry rows on page",
                job_id=self.job_id,
                url=page_url,
                diagnostic=diag,
            )
            try:
                full_body = await page.evaluate("() => document.body.innerText || ''")
            except Exception:
                full_body = snippet
            if is_indiamart_marketing_landing(full_body) or is_indiamart_logged_out_body(
                full_body
            ):
                await self._handle_session_expired(page_url)
                return
            diagnostic_details = await self._capture_indiamart_diagnostics(
                page,
                f"no_buyer_rows_time_{int(has_ago)}",
            )
            await self._log_event(
                "indiamart_layout_check_needed",
                (
                    "IndiaMART is logged in but recent buyer rows were not readable. "
                    "This can mean empty feed, slow SPA load, or IndiaMART layout changed. "
                    "Diagnostic screenshot/HTML saved for quick debug."
                    + diag
                ),
                EventSeverity.warning,
                details=diagnostic_details,
                job_name=job.name,
                page_url=page_url,
                screenshot_path=diagnostic_details.get("screenshot_path"),
            )
            return

        logger.info(
            "Buyer inquiry rows detected",
            job_id=self.job_id,
            row_count=len(blocks),
            url=page_url,
            preview=blocks[0].text[:180] if blocks else "",
        )

        matches: list[tuple[BuyerLeadBlock, Any]] = []
        for block in blocks:
            match_text = lead_match_text(block.text)
            # IndiaMART lead rows are already deduped by lead fingerprint. Do not
            # let keyword cooldown hide the next fresh buyer row for the same
            # product family.
            block_results = DetectionEngine(
                f"{self.job_id}:indiamart_scan"
            ).evaluate(match_text, keywords)
            if not block_results:
                continue
            result = block_results[0]
            if is_weak_match_context(result.context_snippet, result.keyword_value):
                logger.info(
                    "Keyword hit ignored (nav/catalog text)",
                    job_id=self.job_id,
                    keyword=result.keyword_value,
                    snippet=result.context_snippet[:120],
                )
                continue
            matches.append((block, result))

        if not matches:
            logger.info(
                "No keyword match in buyer rows",
                job_id=self.job_id,
                buyer_rows=len(blocks),
                keyword_count=len(keywords),
                row_previews=[b.text[:160] for b in blocks[:3]],
                keywords=[(k.value or "")[:80] for k in keywords[:20]],
                url=page_url,
            )
            self._ensure_indiamart_action_worker(browser, job, keywords, action_rules)
            return

        matches.sort(key=lambda m: (m[1].priority, m[1].score), reverse=True)
        queued = self._enqueue_indiamart_matches(matches, keywords)
        if queued:
            logger.info(
                "Matched IndiaMART leads queued",
                job_id=self.job_id,
                queued=queued,
                queue_size=len(self._indiamart_lead_queue),
                matched_previews=[m[0].text[:240] for m in matches[:3]],
            )
            if await self._try_drain_indiamart_queue_on_current_page(
                page, job, keywords, action_rules, browser
            ):
                return
        self._ensure_indiamart_action_worker(browser, job, keywords, action_rules)

    def _enqueue_indiamart_matches(
        self,
        matches: list[tuple[BuyerLeadBlock, Any]],
        keywords: list[Keyword],
    ) -> int:
        queued = 0
        for block, result in matches[:_MAX_LEADS_PER_SCAN]:
            pre_fp = lead_fingerprint(block.text, {})
            if pre_fp in self._seen_lead_fingerprints:
                continue
            if pre_fp in self._queued_lead_fingerprints:
                continue
            retry_until = self._partial_contact_retry_until.get(pre_fp)
            if retry_until and retry_until > datetime.now(UTC):
                continue
            if retry_until:
                self._partial_contact_retry_until.pop(pre_fp, None)

            click_match_text = lead_match_text(block.text)
            click_guard = DetectionEngine(f"{self.job_id}:queue_guard")
            click_results = click_guard.evaluate(click_match_text, keywords)
            click_result = next(
                (
                    r
                    for r in click_results
                    if r.keyword_id == result.keyword_id
                    and not is_weak_match_context(r.context_snippet, r.keyword_value)
                ),
                None,
            )
            if not click_result:
                logger.warning(
                    "Matched row skipped before queue — keyword no longer validates",
                    job_id=self.job_id,
                    keyword=result.keyword_value,
                    match_text=click_match_text[:300],
                    block_preview=block.text[:300],
                )
                continue

            self._indiamart_lead_queue.append(
                QueuedIndiaMartLead(
                    block=block,
                    keyword_id=click_result.keyword_id,
                    keyword_value=click_result.keyword_value,
                    priority=click_result.priority,
                    score=click_result.score,
                    fingerprint=pre_fp,
                    queued_at=datetime.now(UTC),
                )
            )
            self._queued_lead_fingerprints.add(pre_fp)
            queued += 1

        self._indiamart_lead_queue.sort(
            key=lambda item: (item.priority, item.score, item.queued_at.timestamp()),
            reverse=True,
        )
        return queued

    def _ensure_indiamart_action_worker(
        self,
        browser: BrowserManager,
        job: AutomationJob,
        keywords: list[Keyword],
        action_rules: list[ActionRule],
    ) -> None:
        if not self._indiamart_lead_queue:
            return
        if self._indiamart_action_task and not self._indiamart_action_task.done():
            return
        self._indiamart_action_task = asyncio.create_task(
            self._drain_indiamart_lead_queue(browser, job, keywords, action_rules),
            name=f"indiamart_action_{self.job_id}",
        )
        self._indiamart_action_task.add_done_callback(self._on_indiamart_action_done)

    def _ensure_indiamart_action_page_warm(
        self,
        browser: BrowserManager,
        job: AutomationJob,
    ) -> None:
        if self._indiamart_action_page_ready:
            return
        if self._indiamart_action_warm_task and not self._indiamart_action_warm_task.done():
            return
        self._indiamart_action_warm_task = asyncio.create_task(
            self._warm_indiamart_action_page(browser, job),
            name=f"indiamart_action_warm_{self.job_id}",
        )

    async def _warm_indiamart_action_page(
        self,
        browser: BrowserManager,
        job: AutomationJob,
    ) -> None:
        try:
            async with self._indiamart_action_lock:
                await self._get_indiamart_action_page(browser, job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._indiamart_action_page_ready = False
            logger.warning(
                "IndiaMART action page warm-up failed",
                job_id=self.job_id,
                error=str(exc),
            )

    async def _get_indiamart_action_page(
        self,
        browser: BrowserManager,
        job: AutomationJob,
    ) -> Any:
        page = self._indiamart_action_page
        try:
            closed = page is None or page.is_closed()
        except Exception:
            closed = True
        if closed:
            page = await browser.new_page()
            self._indiamart_action_page = page
            self._indiamart_action_page_ready = False

        leads_url = _indiamart_recent_leads_url(job.target_url)
        current_url = ""
        try:
            current_url = (page.url or "").lower()
        except Exception:
            current_url = ""
        already_on_recent = (
            "seller.indiamart.com" in current_url
            and "bltxn" in current_url
            and "pref=recent" in current_url
        )
        if not self._indiamart_action_page_ready or not already_on_recent:
            await ensure_bltxn_leads_page(page, leads_url, heartbeat=self._heartbeat)
            self._indiamart_action_page_ready = True
            logger.info(
                "IndiaMART action page ready",
                job_id=self.job_id,
                url=page.url,
            )
        return page

    def _on_indiamart_action_done(self, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            logger.info("IndiaMART action worker cancelled", job_id=self.job_id)
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "IndiaMART action worker failed",
                job_id=self.job_id,
                error=str(exc),
            )

    async def _drain_indiamart_lead_queue(
        self,
        browser: BrowserManager,
        job: AutomationJob,
        keywords: list[Keyword],
        action_rules: list[ActionRule],
    ) -> None:
        async with self._indiamart_action_lock:
            page = await self._get_indiamart_action_page(browser, job)
            leads_url = _indiamart_recent_leads_url(job.target_url)
            while self._indiamart_lead_queue and not self._shutdown_event.is_set():
                item = self._indiamart_lead_queue.pop(0)
                self._queued_lead_fingerprints.discard(item.fingerprint)
                await self._process_queued_indiamart_lead(
                    page, item, job, keywords, action_rules, browser, leads_url
                )
                await self._heartbeat()

    async def _try_drain_indiamart_queue_on_current_page(
        self,
        page: Any,
        job: AutomationJob,
        keywords: list[Keyword],
        action_rules: list[ActionRule],
        browser: BrowserManager,
    ) -> bool:
        """Hot path: click leads on the same freshly-scanned page to avoid feed races."""
        if not self._indiamart_lead_queue:
            return False
        if self._indiamart_action_lock.locked():
            return False
        if self._indiamart_action_task and not self._indiamart_action_task.done():
            return False

        async with self._indiamart_action_lock:
            leads_url = _indiamart_recent_leads_url(job.target_url)
            processed = 0
            while self._indiamart_lead_queue and not self._shutdown_event.is_set():
                item = self._indiamart_lead_queue.pop(0)
                self._queued_lead_fingerprints.discard(item.fingerprint)
                await self._process_queued_indiamart_lead(
                    page, item, job, keywords, action_rules, browser, leads_url
                )
                processed += 1
                await self._heartbeat()
            if processed:
                logger.info(
                    "IndiaMART queue drained on scanner page",
                    job_id=self.job_id,
                    processed=processed,
                )
            return processed > 0

    async def _process_queued_indiamart_lead(
        self,
        page: Any,
        item: QueuedIndiaMartLead,
        job: AutomationJob,
        keywords: list[Keyword],
        action_rules: list[ActionRule],
        browser: BrowserManager,
        leads_url: str,
    ) -> None:
        captured = 0
        partial_saved = 0
        block = item.block
        pre_fp = item.fingerprint
        if pre_fp in self._seen_lead_fingerprints:
            logger.info(
                "Duplicate queued lead skipped",
                job_id=self.job_id,
                keyword=item.keyword_value,
                fingerprint=pre_fp,
            )
            return

        retry_until = self._partial_contact_retry_until.get(pre_fp)
        if retry_until and retry_until > datetime.now(UTC):
            logger.info(
                "Queued partial lead contact retry cooling down",
                job_id=self.job_id,
                keyword=item.keyword_value,
                fingerprint=pre_fp,
                retry_at=retry_until.isoformat(),
            )
            return
        if retry_until:
            self._partial_contact_retry_until.pop(pre_fp, None)

        click_match_text = lead_match_text(block.text)
        click_guard = DetectionEngine(f"{self.job_id}:action_guard")
        click_results = click_guard.evaluate(click_match_text, keywords)
        click_result = next(
            (
                r
                for r in click_results
                if r.keyword_id == item.keyword_id
                and not is_weak_match_context(r.context_snippet, r.keyword_value)
            ),
            None,
        )
        if not click_result:
            logger.warning(
                "Queued row skipped before click — keyword no longer validates",
                job_id=self.job_id,
                keyword=item.keyword_value,
                match_text=click_match_text[:300],
                block_preview=block.text[:300],
            )
            return

        current_url = ""
        try:
            current_url = (page.url or "").lower()
        except Exception:
            current_url = ""
        if (
            "seller.indiamart.com" not in current_url
            or "bltxn" not in current_url
            or "pref=recent" not in current_url
        ):
            await ensure_bltxn_leads_page(page, leads_url, heartbeat=self._heartbeat)
            self._indiamart_action_page_ready = True

        fresh_block = await self._find_current_indiamart_block_for_queue_item(
            page, item, keywords
        )
        if not fresh_block:
            skip_details = {
                "keyword": item.keyword_value,
                "lead_fingerprint": pre_fp,
                "queued_age_seconds": (
                    datetime.now(UTC) - item.queued_at
                ).total_seconds(),
                "original_block_preview": block.text[:500],
                "reason": "same product/city/keyword was not visible on live Recent feed",
            }
            logger.warning(
                "Queued lead no longer visible on Recent feed — skipped before click",
                job_id=self.job_id,
                keyword=item.keyword_value,
                fingerprint=pre_fp,
                queued_age_seconds=skip_details["queued_age_seconds"],
                block_preview=block.text[:300],
            )
            await self._log_event(
                "lead_click_skipped",
                f"Skipped '{item.keyword_value}' before click: live Recent feed no longer had the same lead.",
                EventSeverity.warning,
                keyword_matched=item.keyword_value,
                details=skip_details,
                job_name=job.name,
                page_url=leads_url,
            )
            return
        block = fresh_block
        logger.info(
            "Verified current lead before click",
            job_id=self.job_id,
            keyword=item.keyword_value,
            queued_fingerprint=pre_fp,
            current_fingerprint=lead_fingerprint(block.text, {}),
            queue_wait_seconds=(datetime.now(UTC) - item.queued_at).total_seconds(),
            current_preview=block.text[:300],
        )
        await self._log_event(
            "lead_click_verified",
            f"Verified live lead before click: '{item.keyword_value}'.",
            EventSeverity.info,
            keyword_matched=item.keyword_value,
            details={
                "keyword": item.keyword_value,
                "queued_fingerprint": pre_fp,
                "current_fingerprint": lead_fingerprint(block.text, {}),
                "queue_wait_seconds": (
                    datetime.now(UTC) - item.queued_at
                ).total_seconds(),
                "current_block_preview": block.text[:500],
            },
            job_name=job.name,
            page_url=leads_url,
        )
        try:
            stale_panel_text = await _read_detail_panel_text(page)
        except Exception:
            stale_panel_text = ""

        clicked = await click_buyer_lead_block(page, block)
        if not clicked:
            logger.warning(
                "Could not open current verified buyer row — skipped before contact extract",
                job_id=self.job_id,
                keyword=item.keyword_value,
            )
            self._partial_contact_retry_until[pre_fp] = datetime.now(UTC) + timedelta(
                seconds=_CLICK_FAILURE_RETRY_SECONDS
            )
            await self._log_event(
                "lead_click_skipped",
                f"Skipped '{item.keyword_value}' because verified row could not be opened safely.",
                EventSeverity.warning,
                keyword_matched=item.keyword_value,
                details={
                    "keyword": item.keyword_value,
                    "lead_fingerprint": lead_fingerprint(block.text, {}),
                    "current_block_preview": block.text[:500],
                    "reason": "verified row click failed",
                },
                job_name=job.name,
                page_url=leads_url,
            )
            return

        await self._heartbeat()
        lead = await extract_buyer_details(
            page, block.text, stale_panel_text=stale_panel_text
        )
        await self._heartbeat()
        if not lead_has_buyer_contact(lead):
            contact_reason = lead.get(
                "contact_status_reason",
                "contact not revealed on IndiaMART",
            )
            if contact_reason == "detail panel did not match clicked lead":
                self._partial_contact_retry_until[pre_fp] = (
                    datetime.now(UTC)
                    + timedelta(seconds=_CLICK_FAILURE_RETRY_SECONDS)
                )
                await self._log_event(
                    "lead_click_skipped",
                    f"Skipped '{item.keyword_value}' because IndiaMART did not open the verified lead detail panel.",
                    EventSeverity.warning,
                    keyword_matched=item.keyword_value,
                    details={
                        "keyword": item.keyword_value,
                        "lead_fingerprint": pre_fp,
                        "current_block_preview": block.text[:500],
                        "extracted": lead,
                        "reason": contact_reason,
                    },
                    job_name=job.name,
                    page_url=leads_url,
                )
                return
            logger.warning(
                "Buyer phone/email not revealed — queued lead saved as partial",
                job_id=self.job_id,
                keyword=item.keyword_value,
                row_clicked=clicked,
            )
            partial_fp = f"partial:{pre_fp}"
            retry_at = datetime.now(UTC) + timedelta(
                seconds=_PARTIAL_CONTACT_RETRY_SECONDS
            )
            self._partial_contact_retry_until[pre_fp] = retry_at
            if partial_fp not in self._seen_lead_fingerprints:
                self._seen_lead_fingerprints.add(partial_fp)
                partial_details = {
                    **lead,
                    "keyword": item.keyword_value,
                    "context_snippet": block.text[:500],
                    "page_url": leads_url,
                    "lead_fingerprint": partial_fp,
                    "contact_revealed": False,
                    "next_contact_retry_at": retry_at.isoformat(),
                    "queue_wait_seconds": (
                        datetime.now(UTC) - item.queued_at
                    ).total_seconds(),
                }
                partial_msg = (
                    f"Partial buyer lead — {lead.get('product_title', item.keyword_value)} | "
                    f"{lead.get('buyer_address') or lead.get('buyer_location', '')} | "
                    f"Contact not revealed: {contact_reason}"
                )
                if not partial_details.get("message"):
                    partial_details["message"] = partial_msg
                await self._increment_lead()
                await self._log_event(
                    "lead_extracted",
                    partial_msg,
                    EventSeverity.warning,
                    keyword_matched=item.keyword_value,
                    details=partial_details,
                    job_name=job.name,
                    page_url=leads_url,
                )
                partial_saved += 1
            diagnostic_details = await self._capture_indiamart_diagnostics(
                page,
                f"contact_not_revealed_{pre_fp[:32]}",
            )
            await self._log_event(
                "contact_not_revealed",
                f"Matched '{item.keyword_value}' but could not reveal buyer contact. "
                "Open lead manually on IndiaMART or check Buy Lead credits. "
                f"Auto retry after {retry_at.isoformat()}.",
                EventSeverity.warning,
                keyword_matched=item.keyword_value,
                details={
                    "block_preview": block.text[:500],
                    "extracted": lead,
                    "row_clicked": clicked,
                    "contact_status_reason": contact_reason,
                    "next_contact_retry_at": retry_at.isoformat(),
                    "diagnostic": diagnostic_details,
                },
                job_name=job.name,
                page_url=leads_url,
                screenshot_path=diagnostic_details.get("screenshot_path"),
            )
            return
        if not lead_record_is_complete(block.text, lead):
            logger.warning(
                "Queued row rejected — not a complete buyer lead",
                job_id=self.job_id,
                keyword=item.keyword_value,
                block_preview=block.text[:200],
                has_phone=bool(lead.get("buyer_phone")),
                has_name=bool(lead.get("buyer_name")),
            )
            await self._log_event(
                "lead_rejected",
                f"Keyword '{item.keyword_value}' matched page text but buyer details missing.",
                EventSeverity.warning,
                keyword_matched=item.keyword_value,
                details={
                    "block_preview": block.text[:500],
                    "extracted": lead,
                },
                job_name=job.name,
                page_url=leads_url,
            )
            return

        fp = lead_fingerprint(block.text, lead)
        if fp in self._seen_lead_fingerprints:
            logger.info(
                "Duplicate queued lead skipped after contact extract",
                job_id=self.job_id,
                fingerprint=fp,
            )
            self._seen_lead_fingerprints.add(pre_fp)
            return
        self._seen_lead_fingerprints.add(pre_fp)
        self._seen_lead_fingerprints.add(fp)

        details = {
            **lead,
            "keyword": item.keyword_value,
            "context_snippet": block.text[:500],
            "page_url": leads_url,
            "lead_fingerprint": fp,
            "contact_revealed": True,
            "queue_wait_seconds": (datetime.now(UTC) - item.queued_at).total_seconds(),
        }
        msg = (
            f"Buyer lead — {lead.get('product_title', item.keyword_value)} | "
            f"{lead.get('buyer_address') or lead.get('buyer_location', '')} | "
            f"Phone: {lead.get('buyer_phone', 'N/A')} | "
            f"Name: {lead.get('buyer_name', 'N/A')}"
        )
        logger.info(
            "Real queued buyer lead captured",
            job_id=self.job_id,
            keyword=item.keyword_value,
            phone=lead.get("buyer_phone"),
            product=lead.get("product_title"),
            name=lead.get("buyer_name"),
        )
        await self._increment_lead()
        await self._log_event(
            "lead_extracted",
            msg,
            EventSeverity.info,
            keyword_matched=item.keyword_value,
            details=details,
            job_name=job.name,
            page_url=leads_url,
        )
        captured += 1

        if action_rules:
            action_engine = ActionEngine(
                self.job_id,
                PageScopedBrowser(browser, page),  # type: ignore[arg-type]
            )
            action_engine._last_lead_data = lead
            exec_results = await action_engine.execute_chain(action_rules)
            success_count = sum(exec_results)
            await self._increment_action(success_count)

        if captured == 0 and partial_saved == 0:
            logger.info(
                "No new leads saved from queued item",
                job_id=self.job_id,
                keyword=item.keyword_value,
            )
        elif captured == 0 and partial_saved > 0:
            logger.info(
                "Partial queued lead saved (contact not revealed)",
                job_id=self.job_id,
                partial_saved=partial_saved,
            )

    async def _find_current_indiamart_block_for_queue_item(
        self,
        page: Any,
        item: QueuedIndiaMartLead,
        keywords: list[Keyword],
    ) -> BuyerLeadBlock | None:
        """Re-find a queued lead on the live feed before clicking it."""
        scan_passes = (
            {"max_blocks": 18, "visible_only": True},
            {"max_blocks": 35, "visible_only": False},
        )
        for scan in scan_passes:
            blocks = await collect_buyer_lead_blocks(page, **scan)
            for block in blocks:
                if not lead_identity_matches(block.text, item.block.text):
                    continue
                match_text = lead_match_text(block.text)
                results = DetectionEngine(
                    f"{self.job_id}:fresh_click_guard"
                ).evaluate(match_text, keywords)
                result = next(
                    (
                        r
                        for r in results
                        if r.keyword_id == item.keyword_id
                        and not is_weak_match_context(
                            r.context_snippet, r.keyword_value
                        )
                    ),
                    None,
                )
                if result:
                    return block
            if blocks:
                logger.info(
                    "Queued lead not found in live scan pass",
                    job_id=self.job_id,
                    keyword=item.keyword_value,
                    visible_only=scan["visible_only"],
                    scanned=len(blocks),
                    fingerprint=item.fingerprint,
                )
        return None

    async def _handle_detection_results(
        self,
        results: list[Any],
        job: AutomationJob,
        browser: BrowserManager,
        action_rules: list[ActionRule],
        page_url: str,
        context_snippet: str,
    ) -> None:
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
                details={
                    "keyword": result.keyword_value,
                    "context_snippet": context_snippet,
                    "page_url": page_url,
                },
                job_name=job.name,
                page_url=page_url,
            )
            await self._increment_lead()

        if action_rules:
            action_engine = ActionEngine(self.job_id, browser)
            exec_results = await action_engine.execute_chain(action_rules)
            success_count = sum(exec_results)
            await self._increment_action(success_count)

    async def _ensure_on_target_page(
        self,
        browser: BrowserManager,
        job: AutomationJob,
        page: Any,
    ) -> None:
        """Navigate to target_url when blank, logged out, or off seller domain."""
        try:
            current_url = page.url or ""
        except Exception:
            current_url = ""

        current_lower = current_url.lower()
        target_lower = job.target_url.lower()

        if not current_url or current_url == "about:blank":
            start_url = job.target_url
            if is_indiamart_seller_url(start_url):
                start_url = _indiamart_recent_leads_url(start_url)
            await self._navigate_to_target(browser, start_url)
            return

        if is_indiamart_seller_url(target_lower):
            if is_indiamart_login_url(current_lower):
                return
            leads_url = _indiamart_recent_leads_url(job.target_url)
            # Skip re-navigation if already on the correct bltxn recent page
            already_on_leads = (
                "bltxn" in current_lower
                and "pref=recent" in current_lower
                and "seller.indiamart.com" in current_lower
            )
            if not already_on_leads:
                await ensure_bltxn_leads_page(page, leads_url, heartbeat=self._heartbeat)
                await self._heartbeat()
            logger.info(
                "IndiaMART page load",
                job_id=self.job_id,
                ready=True,
                already_on_leads=already_on_leads,
                url=page.url,
            )
            return

        if target_lower not in current_lower:
            await self._navigate_to_target(browser, job.target_url)

    async def _navigate_to_target(self, browser: BrowserManager, url: str) -> None:
        await browser.navigate(url)
        page = await browser.get_page()
        if is_indiamart_seller_url(url):
            ready = await wait_for_page_ready(page)
            logger.info(
                "IndiaMART page load",
                job_id=self.job_id,
                ready=ready,
                url=page.url,
            )

    async def _collect_page_text(self, page: Any, target_url: str) -> str:
        try:
            body_text = await page.evaluate("() => document.body.innerText || ''")
        except Exception as exc:
            logger.warning("Failed to get page text", job_id=self.job_id, error=str(exc))
            return ""

        if is_indiamart_seller_url(target_url):
            await scroll_lead_list(page)
            inquiry_text = await collect_inquiry_text(page)
            if inquiry_text:
                combined = f"{body_text}\n---\n{inquiry_text}"
                if len(combined) > len(body_text) + 50:
                    return combined
        return body_text

    async def _is_session_expired(self, page: Any, current_url: str) -> bool:
        """Returns True if the browser has been redirected to a login page."""
        if is_indiamart_login_url(current_url):
            return True
        on_seller = is_indiamart_seller_url(current_url)
        for pattern in _LOGIN_URL_PATTERNS:
            if pattern in current_url:
                if on_seller and ("bltxn" in current_url or "pref=recent" in current_url):
                    continue
                return True
        # Recent-leads SPA: decide logout only after lead scan (avoids false positives).
        if on_seller and ("bltxn" in current_url or "pref=recent" in current_url):
            return False
        if on_seller and "seller.indiamart.com" in current_url:
            try:
                snippet = await read_indiamart_page_text(page, 8000)
            except Exception:
                snippet = ""
            if is_indiamart_logged_out_body(snippet):
                return True
            return False
        try:
            page_text = await page.evaluate("() => (document.body.innerText || '').toLowerCase()")
            strict_patterns = (
                "session expired",
                "your session has expired",
                "log in to continue",
                "sign in to continue",
            )
            for pattern in strict_patterns:
                if pattern in page_text:
                    return True
        except Exception:
            pass
        return False

    async def _handle_session_expired(self, current_url: str) -> None:
        """Log critical alert and pause the job so seller knows to re-login."""
        msg = (
            "IndiaMART seller login not active in the server browser (public page or expired session). "
            "Stop the job → run login.ps1 on client PC (open Recent Buy Leads before ENTER) → "
            "confirm dashboard Seller Session = YES → Start job. Profile must be indiamart."
            f" (url={current_url})"
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
        profile = job.browser_profile_name
        if not profile and is_indiamart_seller_url(job.target_url):
            profile = "indiamart"
            logger.info(
                "IndiaMART job using default browser profile",
                job_id=self.job_id,
                profile=profile,
            )

        if self._browser is None or not self._browser.is_alive:
            self._browser = BrowserManager(
                job_id=self.job_id,
                profile_name=profile,
            )
            await self._browser.launch()
            self._browser_created_at = datetime.now(UTC)

        return self._browser

    async def _maybe_recycle_browser(self) -> None:
        if self._browser_created_at is None:
            return
        if self._indiamart_action_task and not self._indiamart_action_task.done():
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
        details: dict[str, Any] | None = None,
        job_name: str = "",
        page_url: str | None = None,
        screenshot_path: str | None = None,
    ) -> None:
        from app.services.lead_store import append_lead_row

        details_json = json.dumps(details) if details else None
        factory = get_session_factory()
        async with factory() as db:
            svc = EventLogService(db)
            await svc.create(
                event_type=event_type,
                message=message,
                severity=severity,
                job_id=self.job_id,
                keyword_matched=keyword_matched,
                details=details_json,
                screenshot_path=screenshot_path,
            )
            await db.commit()

        if event_type in ("keyword_detected", "lead_extracted"):
            append_lead_row(
                job_id=self.job_id,
                job_name=job_name or self.job_id[:8],
                event_type=event_type,
                keyword_matched=keyword_matched,
                message=message,
                page_url=page_url,
                details=details,
                context_snippet=(details or {}).get("context_snippet"),
            )

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

    async def _capture_indiamart_diagnostics(
        self,
        page: Any,
        reason: str,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """Save screenshot + HTML when IndiaMART layout/feed/contact extraction looks broken."""
        safe_reason = re.sub(r"[^a-zA-Z0-9_-]+", "_", reason)[:50].strip("_") or "diagnostic"
        alert_key = safe_reason
        if not force and alert_key in self._layout_alert_keys:
            return {"diagnostic_already_captured": True, "reason": reason}
        self._layout_alert_keys.add(alert_key)

        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        base = settings.SCREENSHOT_DIR / "indiamart_diagnostics"
        base.mkdir(parents=True, exist_ok=True)
        stem = f"{self.job_id}_{safe_reason}_{ts}"
        details: dict[str, Any] = {
            "reason": reason,
            "url": getattr(page, "url", ""),
        }

        try:
            png_path = base / f"{stem}.png"
            await page.screenshot(path=str(png_path), full_page=False)
            details["screenshot_path"] = str(png_path)
        except Exception as exc:
            details["screenshot_error"] = str(exc)[:300]

        try:
            html = await page.content()
            html_path = base / f"{stem}.html"
            html_path.write_text(html, encoding="utf-8", errors="ignore")
            details["html_snapshot_path"] = str(html_path)
            details["html_chars"] = len(html)
        except Exception as exc:
            details["html_snapshot_error"] = str(exc)[:300]

        try:
            body = await read_indiamart_page_text(page, 1000)
            details["body_preview"] = body[:1000]
            details["body_chars"] = len(body)
        except Exception:
            pass

        logger.warning(
            "IndiaMART diagnostics captured",
            job_id=self.job_id,
            reason=reason,
            screenshot_path=details.get("screenshot_path"),
            html_snapshot_path=details.get("html_snapshot_path"),
        )
        return details

    async def _cleanup(self) -> None:
        self._is_running = False
        if self._indiamart_action_warm_task and not self._indiamart_action_warm_task.done():
            self._indiamart_action_warm_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._indiamart_action_warm_task
        if self._indiamart_action_task and not self._indiamart_action_task.done():
            self._indiamart_action_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._indiamart_action_task
        if self._browser:
            await self._browser.close()
            self._browser = None
        try:
            await self._update_status(JobStatus.stopped)
        except Exception:
            pass
        logger.info("JobRunner cleaned up", job_id=self.job_id)

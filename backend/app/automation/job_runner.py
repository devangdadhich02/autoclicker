from __future__ import annotations

import asyncio
import json
import random
import re
from datetime import UTC, datetime
from typing import Any

from app.automation.action_engine import ActionEngine
from app.automation.browser_manager import BrowserManager
from app.automation.detection_engine import DetectionEngine
from app.automation.indiamart_leads import (
    BuyerLeadBlock,
    click_buyer_lead_block,
    lead_has_buyer_contact,
    collect_buyer_lead_blocks,
    extract_buyer_details,
    is_weak_match_context,
    lead_fingerprint,
    lead_record_is_complete,
)
from app.automation.profile_cookies import load_portable_cookies
from app.automation.indiamart_page import (
    INDIAMART_LEADS_URL,
    collect_inquiry_text,
    ensure_bltxn_leads_page,
    is_indiamart_logged_out_body,
    is_indiamart_login_url,
    is_indiamart_marketing_landing,
    is_indiamart_seller_url,
    open_first_lead_card,
    read_indiamart_page_text,
    scroll_lead_list,
    seller_session_is_authenticated,
    wait_for_page_ready,
)

# Cap leads processed per poll so contact reveal + heartbeat stay within watchdog budget.
_MAX_LEADS_PER_SCAN = 10
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.models.automation_job import AutomationJob, JobStatus
from app.models.event_log import EventSeverity
from app.models.keyword import Keyword
from app.models.action_rule import ActionRule, ActionType
from app.services.event_log_service import EventLogService
from app.services.job_service import JobService
from app.services.keyword_service import KeywordService

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
                    leads_url = job.target_url
                    if "bltxn" not in (leads_url or "").lower():
                        leads_url = INDIAMART_LEADS_URL
                    await ensure_bltxn_leads_page(page, leads_url)
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
        blocks = await collect_buyer_lead_blocks(page)
        if not blocks:
            try:
                snippet = await page.evaluate(
                    "() => (document.body.innerText || '').slice(0, 600)"
                )
                if re.search(
                    r"(?:just\s+now|\d+\s*(?:min|mins|hr|hrs|hour|hours|day|days)\s*ago)",
                    snippet or "",
                    re.I,
                ):
                    leads_url = job.target_url
                    if "bltxn" not in (leads_url or "").lower():
                        leads_url = INDIAMART_LEADS_URL
                    await ensure_bltxn_leads_page(page, leads_url)
                    blocks = await collect_buyer_lead_blocks(page)
            except Exception:
                pass
        if not blocks:
            leads_url = job.target_url
            if "bltxn" not in (leads_url or "").lower():
                leads_url = INDIAMART_LEADS_URL
            await ensure_bltxn_leads_page(page, leads_url)
            await open_first_lead_card(page)
            await scroll_lead_list(page)
            blocks = await collect_buyer_lead_blocks(page)
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
            await self._log_event(
                "scan_no_inquiry_rows",
                "IndiaMART recent leads list empty or layout changed. Open bltxn manually to verify."
                + diag,
                EventSeverity.warning,
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
            block_results = self._detection.evaluate(block.text, keywords)
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
            return

        matches.sort(key=lambda m: (m[1].priority, m[1].score), reverse=True)
        leads_url = job.target_url
        if "bltxn" not in (leads_url or "").lower():
            leads_url = INDIAMART_LEADS_URL

        captured = 0
        partial_saved = 0
        for block, result in matches[:_MAX_LEADS_PER_SCAN]:
            await self._heartbeat()
            pre_fp = lead_fingerprint(block.text, {})
            if pre_fp in self._seen_lead_fingerprints:
                logger.info(
                    "Duplicate lead skipped (already captured)",
                    job_id=self.job_id,
                    keyword=result.keyword_value,
                    fingerprint=pre_fp,
                )
                continue

            if captured > 0:
                await ensure_bltxn_leads_page(page, leads_url)
                await scroll_lead_list(page)

            clicked = await click_buyer_lead_block(page, block)
            if not clicked:
                logger.warning(
                    "Could not open matched buyer row — using feed text only",
                    job_id=self.job_id,
                    keyword=result.keyword_value,
                )

            await self._heartbeat()
            lead = await extract_buyer_details(page, block.text)
            await self._heartbeat()
            if not lead_has_buyer_contact(lead):
                logger.warning(
                    "Buyer phone/email not revealed — lead saved as partial",
                    job_id=self.job_id,
                    keyword=result.keyword_value,
                    row_clicked=clicked,
                )
                # Persist partial lead so matched inquiries are not completely lost.
                partial_fp = f"partial:{pre_fp}"
                if partial_fp not in self._seen_lead_fingerprints:
                    self._seen_lead_fingerprints.add(partial_fp)
                    partial_details = {
                        **lead,
                        "keyword": result.keyword_value,
                        "context_snippet": block.text[:500],
                        "page_url": page_url,
                        "lead_fingerprint": partial_fp,
                        "contact_revealed": False,
                    }
                    partial_msg = (
                        f"Partial buyer lead — {lead.get('product_title', result.keyword_value)} | "
                        f"{lead.get('buyer_address') or lead.get('buyer_location', '')} | "
                        "Contact not revealed on IndiaMART"
                    )
                    await self._increment_lead()
                    await self._log_event(
                        "lead_extracted",
                        partial_msg,
                        EventSeverity.warning,
                        keyword_matched=result.keyword_value,
                        details=partial_details,
                        job_name=job.name,
                        page_url=page_url,
                    )
                    partial_saved += 1
                await self._log_event(
                    "contact_not_revealed",
                    f"Matched '{result.keyword_value}' but could not reveal buyer contact. "
                    "Open lead manually on IndiaMART or check Buy Lead credits.",
                    EventSeverity.warning,
                    keyword_matched=result.keyword_value,
                    details={
                        "block_preview": block.text[:500],
                        "extracted": lead,
                        "row_clicked": clicked,
                    },
                    job_name=job.name,
                    page_url=page_url,
                )
                continue
            if not lead_record_is_complete(block.text, lead):
                logger.warning(
                    "Matched row rejected — not a complete buyer lead",
                    job_id=self.job_id,
                    keyword=result.keyword_value,
                    block_preview=block.text[:200],
                    has_phone=bool(lead.get("buyer_phone")),
                    has_name=bool(lead.get("buyer_name")),
                )
                await self._log_event(
                    "lead_rejected",
                    f"Keyword '{result.keyword_value}' matched page text but buyer details missing.",
                    EventSeverity.warning,
                    keyword_matched=result.keyword_value,
                    details={
                        "block_preview": block.text[:500],
                        "extracted": lead,
                    },
                    job_name=job.name,
                    page_url=page_url,
                )
                continue

            fp = lead_fingerprint(block.text, lead)
            if fp in self._seen_lead_fingerprints:
                logger.info(
                    "Duplicate lead skipped after contact extract",
                    job_id=self.job_id,
                    fingerprint=fp,
                )
                continue
            self._seen_lead_fingerprints.add(fp)

            details = {
                **lead,
                "keyword": result.keyword_value,
                "context_snippet": block.text[:500],
                "page_url": page_url,
                "lead_fingerprint": fp,
            }
            msg = (
                f"Buyer lead — {lead.get('product_title', result.keyword_value)} | "
                f"{lead.get('buyer_address') or lead.get('buyer_location', '')} | "
                f"Phone: {lead.get('buyer_phone', 'N/A')} | "
                f"Name: {lead.get('buyer_name', 'N/A')}"
            )
            logger.info(
                "Real buyer lead captured",
                job_id=self.job_id,
                keyword=result.keyword_value,
                phone=lead.get("buyer_phone"),
                product=lead.get("product_title"),
                name=lead.get("buyer_name"),
            )
            await self._increment_lead()
            await self._log_event(
                "lead_extracted",
                msg,
                EventSeverity.info,
                keyword_matched=result.keyword_value,
                details=details,
                job_name=job.name,
                page_url=page_url,
            )
            captured += 1

            if action_rules:
                action_engine = ActionEngine(self.job_id, browser)
                action_engine._last_lead_data = lead
                exec_results = await action_engine.execute_chain(action_rules)
                success_count = sum(exec_results)
                await self._increment_action(success_count)

        if captured == 0 and partial_saved == 0:
            logger.info(
                "No new leads saved this scan (duplicates or contact not revealed)",
                job_id=self.job_id,
                matched_rows=len(matches),
            )
        elif captured == 0 and partial_saved > 0:
            logger.info(
                "Partial leads saved this scan (contact not revealed)",
                job_id=self.job_id,
                matched_rows=len(matches),
                partial_saved=partial_saved,
            )

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
            if is_indiamart_seller_url(start_url) and "bltxn" not in start_url.lower():
                start_url = INDIAMART_LEADS_URL
            await self._navigate_to_target(browser, start_url)
            return

        if is_indiamart_seller_url(target_lower):
            if is_indiamart_login_url(current_lower):
                return
            leads_url = INDIAMART_LEADS_URL
            if "bltxn" in target_lower or "pref=recent" in target_lower:
                leads_url = job.target_url
            await ensure_bltxn_leads_page(page, leads_url)
            await self._heartbeat()
            logger.info(
                "IndiaMART page load",
                job_id=self.job_id,
                ready=True,
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

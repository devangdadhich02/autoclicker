from __future__ import annotations

import asyncio
import json
import random
from typing import Any

import httpx
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from app.automation.browser_manager import BrowserManager
from app.core.config import settings
from app.core.logging import get_logger
from app.models.action_rule import ActionRule, ActionType
from app.models.event_log import EventSeverity

# IndiaMART inquiry panel selectors (tried in order, first match wins)
_IM_INQUIRY_ROW_SELECTORS = [
    ".byr-inqry-list .byr-inqry-item:first-child",
    ".inquiry-list-item:first-child",
    ".msg-list-item:first-child",
    "[data-testid='inquiry-item']:first-child",
    ".inqBox:first-child",
]
_IM_DETAIL_PANEL_SELECTORS = [
    ".inqry-detail-panel",
    ".inquiry-detail",
    ".msg-detail-panel",
    "[data-testid='inquiry-detail']",
    ".byr-detail",
]
_IM_BUYER_NAME_SELECTORS = [
    ".buyer-name", ".byr-name", ".contact-name",
    "[data-testid='buyer-name']", ".inq-sender-name",
]
_IM_BUYER_PHONE_SELECTORS = [
    ".buyer-phone", ".byr-phone", ".contact-phone",
    "[data-testid='buyer-phone']", ".inq-phone", ".phone-no",
]
_IM_BUYER_EMAIL_SELECTORS = [
    ".buyer-email", ".byr-email", ".contact-email",
    "[data-testid='buyer-email']", ".inq-email",
]
_IM_MESSAGE_SELECTORS = [
    ".inquiry-message", ".inq-msg", ".msg-content",
    ".byr-msg", "[data-testid='inquiry-message']", ".inqDesc",
]

logger = get_logger(__name__)


class ActionEngine:
    """
    Executes configured action rules against a live browser page.
    Implements retry, timeout, fallback selectors, and human-like delays.
    """

    def __init__(self, job_id: str, browser: BrowserManager) -> None:
        self.job_id = job_id
        self._browser = browser
        self._last_lead_data: dict[str, Any] = {}

    async def execute_rule(self, rule: ActionRule) -> bool:
        """Execute a single action rule with full retry and fallback logic."""
        attempts = 0
        last_error: Exception | None = None

        while attempts < rule.retry_count:
            attempts += 1
            try:
                success = await self._dispatch(rule)
                if success:
                    logger.info(
                        "Action executed",
                        job_id=self.job_id,
                        rule=rule.name,
                        action=rule.action_type,
                        attempt=attempts,
                    )
                    await asyncio.sleep(rule.delay_after_ms / 1000)
                    return True
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Action attempt failed",
                    job_id=self.job_id,
                    rule=rule.name,
                    attempt=attempts,
                    error=str(exc),
                )
                delay = settings.ACTION_RETRY_DELAY_SECONDS * (1.5 ** (attempts - 1))
                await asyncio.sleep(delay + random.uniform(0.1, 0.5))

        logger.error(
            "Action failed after all retries",
            job_id=self.job_id,
            rule=rule.name,
            error=str(last_error),
        )
        return False

    async def execute_chain(self, rules: list[ActionRule]) -> list[bool]:
        """Execute a sequence of action rules in order."""
        active_rules = sorted(
            [r for r in rules if r.is_active], key=lambda r: r.order
        )
        results: list[bool] = []
        for rule in active_rules:
            result = await self.execute_rule(rule)
            results.append(result)
            if not result:
                # Capture screenshot on action failure for diagnostics
                await self._browser.screenshot(label=f"action_fail_{rule.name[:20]}")
        return results

    async def _dispatch(self, rule: ActionRule) -> bool:
        handlers = {
            ActionType.click: self._handle_click,
            ActionType.navigate: self._handle_navigate,
            ActionType.fill_form: self._handle_fill_form,
            ActionType.extract_text: self._handle_extract_text,
            ActionType.screenshot: self._handle_screenshot,
            ActionType.wait: self._handle_wait,
            ActionType.scroll: self._handle_scroll,
            ActionType.webhook: self._handle_webhook,
            ActionType.notify: self._handle_notify,
            ActionType.mark_important: self._handle_mark_important,
            ActionType.open_inquiry: self._handle_open_inquiry,
            ActionType.copy_lead: self._handle_copy_lead,
        }
        handler = handlers.get(rule.action_type)
        if handler is None:
            logger.error("Unknown action type", action=rule.action_type)
            return False
        return await handler(rule)

    async def _handle_click(self, rule: ActionRule) -> bool:
        page = await self._browser.get_page()
        selector = await self._resolve_selector(page, rule)
        if not selector:
            return False
        await page.wait_for_selector(selector, timeout=rule.timeout_ms)
        await asyncio.sleep(random.uniform(0.1, 0.4))
        await page.click(selector)
        return True

    async def _handle_navigate(self, rule: ActionRule) -> bool:
        if not rule.target_url:
            return False
        await self._browser.navigate(rule.target_url)
        return True

    async def _handle_fill_form(self, rule: ActionRule) -> bool:
        if not rule.selector or not rule.payload:
            return False
        page = await self._browser.get_page()
        data: dict[str, str] = json.loads(rule.payload)
        for selector, value in data.items():
            await page.wait_for_selector(selector, timeout=rule.timeout_ms)
            await asyncio.sleep(random.uniform(0.05, 0.15))
            await page.fill(selector, value)
            await asyncio.sleep(random.uniform(0.1, 0.3))
        return True

    async def _handle_extract_text(self, rule: ActionRule) -> bool:
        if not rule.selector:
            return False
        page = await self._browser.get_page()
        selector = await self._resolve_selector(page, rule)
        if not selector:
            return False
        text = await page.inner_text(selector)
        text = text.strip()
        logger.info("Text extracted", job_id=self.job_id, selector=selector, text=text[:300])
        # Save extracted text to DB as a lead_data event
        await self._save_lead_event(
            event_type="lead_data_extracted",
            message=f"Extracted: {text[:500]}",
            details=json.dumps({"selector": selector, "text": text, "rule": rule.name}),
        )
        return True

    async def _handle_screenshot(self, rule: ActionRule) -> bool:
        path = await self._browser.screenshot(label=rule.name[:20])
        return path is not None

    async def _handle_wait(self, rule: ActionRule) -> bool:
        delay = rule.timeout_ms / 1000 if rule.timeout_ms else 2.0
        await asyncio.sleep(delay)
        return True

    async def _handle_scroll(self, rule: ActionRule) -> bool:
        page = await self._browser.get_page()
        payload = json.loads(rule.payload) if rule.payload else {}
        x = payload.get("x", 0)
        y = payload.get("y", 500)
        await page.evaluate(f"window.scrollBy({x}, {y})")
        return True

    async def _handle_webhook(self, rule: ActionRule) -> bool:
        if not rule.target_url:
            return False
        payload = json.loads(rule.payload) if rule.payload else {}
        # Auto-inject extracted lead data if available (from open_inquiry action before this)
        if self._last_lead_data:
            payload["lead"] = self._last_lead_data
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(rule.target_url, json=payload)
            response.raise_for_status()
        logger.info("Webhook triggered", url=rule.target_url, status=response.status_code)
        return True

    async def _handle_notify(self, rule: ActionRule) -> bool:
        logger.info(
            "NOTIFICATION",
            job_id=self.job_id,
            rule=rule.name,
            payload=rule.payload,
        )
        return True

    async def _handle_mark_important(self, rule: ActionRule) -> bool:
        return await self._handle_click(rule)

    async def extract_latest_inquiry(
        self,
        click_selector: str | None = None,
        timeout_ms: int = 10_000,
    ) -> dict[str, str]:
        """Open first inquiry row and extract buyer fields (IndiaMART)."""
        page = await self._browser.get_page()

        # Step 1: Click the first inquiry row
        clicked = False
        if click_selector:
            try:
                await page.wait_for_selector(click_selector, timeout=timeout_ms)
                await asyncio.sleep(random.uniform(0.2, 0.5))
                await page.click(click_selector)
                clicked = True
            except PlaywrightTimeoutError:
                pass

        if not clicked:
            for sel in _IM_INQUIRY_ROW_SELECTORS:
                try:
                    await page.wait_for_selector(sel, timeout=3000)
                    await asyncio.sleep(random.uniform(0.2, 0.5))
                    await page.click(sel)
                    clicked = True
                    break
                except PlaywrightTimeoutError:
                    continue

        if not clicked:
            logger.warning("open_inquiry: no inquiry row found", job_id=self.job_id)
            return {}

        # Step 2: Wait for detail panel to load
        await asyncio.sleep(1.5)
        detail_loaded = False
        for sel in _IM_DETAIL_PANEL_SELECTORS:
            try:
                await page.wait_for_selector(sel, timeout=5000)
                detail_loaded = True
                break
            except PlaywrightTimeoutError:
                continue

        # Step 3: Extract all available buyer fields
        lead: dict[str, str] = {}

        async def _try_extract(selectors: list[str], field: str) -> None:
            for sel in selectors:
                try:
                    el = page.locator(sel).first
                    val = await el.inner_text(timeout=2000)
                    val = val.strip()
                    if val:
                        lead[field] = val
                        return
                except Exception:
                    continue

        await _try_extract(_IM_BUYER_NAME_SELECTORS, "buyer_name")
        await _try_extract(_IM_BUYER_PHONE_SELECTORS, "buyer_phone")
        await _try_extract(_IM_BUYER_EMAIL_SELECTORS, "buyer_email")
        await _try_extract(_IM_MESSAGE_SELECTORS, "message")

        # Fallback: if detail loaded, grab full panel text
        if detail_loaded and not lead:
            for sel in _IM_DETAIL_PANEL_SELECTORS:
                try:
                    panel_text = await page.inner_text(sel)
                    lead["full_detail"] = panel_text.strip()[:1000]
                    break
                except Exception:
                    continue

        self._last_lead_data = lead
        return lead

    async def _handle_open_inquiry(self, rule: ActionRule) -> bool:
        lead = await self.extract_latest_inquiry(
            click_selector=rule.selector,
            timeout_ms=rule.timeout_ms,
        )
        if lead:
            msg = (
                f"Lead extracted — "
                f"Name: {lead.get('buyer_name', 'N/A')} | "
                f"Phone: {lead.get('buyer_phone', 'N/A')} | "
                f"Email: {lead.get('buyer_email', 'N/A')} | "
                f"Msg: {lead.get('message', lead.get('full_detail', 'N/A'))[:200]}"
            )
            logger.info("Lead extracted", job_id=self.job_id, lead=lead)
            await self._save_lead_event(
                event_type="lead_extracted",
                message=msg,
                details=json.dumps(lead),
            )
            return True

        logger.warning("open_inquiry: no inquiry or fields extracted", job_id=self.job_id)
        await self._save_lead_event(
            event_type="lead_extracted",
            message="Inquiry opened but buyer details not found — check CSS selectors",
            details=json.dumps({}),
        )
        return False

    async def _handle_copy_lead(self, rule: ActionRule) -> bool:
        return await self._handle_extract_text(rule)

    async def _save_lead_event(
        self,
        event_type: str,
        message: str,
        details: str | None = None,
        keyword_matched: str | None = None,
        job_name: str = "",
        page_url: str | None = None,
    ) -> None:
        """Persist extracted lead data to EventLog + per-job CSV on disk."""
        try:
            from app.db.session import get_session_factory
            from app.services.event_log_service import EventLogService
            from app.services.lead_store import append_lead_row, parse_details_json

            factory = get_session_factory()
            async with factory() as db:
                svc = EventLogService(db)
                await svc.create(
                    event_type=event_type,
                    message=message,
                    severity=EventSeverity.info,
                    job_id=self.job_id,
                    details=details,
                    keyword_matched=keyword_matched,
                )
                await db.commit()

            parsed = parse_details_json(details)
            append_lead_row(
                job_id=self.job_id,
                job_name=job_name or self.job_id[:8],
                event_type=event_type,
                keyword_matched=keyword_matched,
                message=message,
                page_url=page_url,
                details=parsed,
            )
        except Exception as exc:
            logger.error("Failed to save lead event", job_id=self.job_id, error=str(exc))

    async def _resolve_selector(self, page: Page, rule: ActionRule) -> str | None:
        """Try primary selector then fallback selector."""
        for selector in filter(None, [rule.selector, rule.fallback_selector]):
            try:
                await page.wait_for_selector(selector, timeout=min(rule.timeout_ms, 5000))
                return selector
            except PlaywrightTimeoutError:
                continue
        logger.warning(
            "No selector resolved",
            job_id=self.job_id,
            rule=rule.name,
            primary=rule.selector,
            fallback=rule.fallback_selector,
        )
        return None

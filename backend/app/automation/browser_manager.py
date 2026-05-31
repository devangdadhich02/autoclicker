from __future__ import annotations

import asyncio
import random
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)

from app.automation.profile_cookies import load_portable_cookies
from app.core.config import settings
from app.core.exceptions import BrowserError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Stable fingerprint — rotating UA breaks persisted login sessions
_DEFAULT_VIEWPORT = {"width": 1366, "height": 768}
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class BrowserManager:
    """
    Manages Playwright browser instances with stealth, profile persistence,
    session recovery, and crash auto-restart.
    """

    def __init__(self, job_id: str, profile_name: str | None = None) -> None:
        self.job_id = job_id
        self.profile_name = profile_name or f"job_{job_id[:8]}"
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._launch_count = 0
        self._session_id = str(uuid.uuid4())

    @property
    def profile_path(self) -> Path:
        return settings.BROWSER_PROFILE_DIR / self.profile_name

    @property
    def is_alive(self) -> bool:
        """Persistent context uses _context, not _browser."""
        if self._context is None or self._page is None:
            return False
        try:
            return not self._page.is_closed()
        except Exception:
            return False

    async def launch(self) -> Page:
        """Launch browser with stealth settings and persistent profile."""
        if self.is_alive:
            return self._page  # type: ignore[return-value]

        # Close stale context before relaunch (prevents profile lock / EPIPE)
        if self._context is not None or self._playwright is not None:
            await self.close()

        self.profile_path.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        viewport = _DEFAULT_VIEWPORT
        user_agent = _DEFAULT_USER_AGENT

        browser_type: BrowserType = getattr(self._playwright, settings.BROWSER_TYPE)

        try:
            self._context = await browser_type.launch_persistent_context(
                user_data_dir=str(self.profile_path),
                headless=settings.BROWSER_HEADLESS,
                viewport=viewport,
                user_agent=user_agent,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--disable-extensions",
                    "--lang=en-US",
                ],
                ignore_default_args=["--enable-automation"],
                locale="en-US",
                timezone_id="Asia/Kolkata",
            )
        except Exception as exc:
            logger.error("Browser launch failed", job_id=self.job_id, error=str(exc))
            raise BrowserError(f"Failed to launch browser: {exc}") from exc

        await self._apply_stealth(self._context)
        await self._inject_portable_cookies()

        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        self._launch_count += 1

        logger.info(
            "Browser launched",
            job_id=self.job_id,
            profile=self.profile_name,
            launch_count=self._launch_count,
            headless=settings.BROWSER_HEADLESS,
        )
        return self._page

    async def _inject_portable_cookies(self) -> None:
        """Apply cookies exported from login.ps1 (Windows → Linux)."""
        cookies = load_portable_cookies(self.profile_path)
        if not cookies or self._context is None:
            return
        try:
            await self._context.add_cookies(cookies)
            logger.info(
                "Portable IndiaMART cookies loaded",
                job_id=self.job_id,
                profile=self.profile_name,
                count=len(cookies),
            )
        except Exception as exc:
            logger.warning(
                "Portable cookie load failed",
                job_id=self.job_id,
                error=str(exc),
            )

    async def _apply_stealth(self, context: BrowserContext) -> None:
        """Inject stealth scripts to avoid bot detection."""
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
            delete navigator.__proto__.webdriver;
        """)

    async def get_page(self) -> Page:
        if not self.is_alive:
            await self.launch()
        return self._page  # type: ignore[return-value]

    async def navigate(
        self,
        url: str,
        wait_until: str = "domcontentloaded",
        timeout_ms: int | None = None,
    ) -> None:
        page = await self.get_page()
        await self._human_delay(500, 1200)
        timeout = timeout_ms or settings.BROWSER_NAVIGATION_TIMEOUT_MS
        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout)
        except Exception as exc:
            logger.warning("Navigation error", job_id=self.job_id, url=url, error=str(exc))
            raise

    async def screenshot(self, label: str = "") -> Path | None:
        try:
            page = await self.get_page()
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            filename = f"{self.job_id}_{label}_{ts}.png" if label else f"{self.job_id}_{ts}.png"
            path = settings.SCREENSHOT_DIR / filename
            await page.screenshot(path=str(path), full_page=False)
            return path
        except Exception as exc:
            logger.warning("Screenshot failed", job_id=self.job_id, error=str(exc))
            return None

    async def save_cookies(self) -> list[dict[str, Any]]:
        if self._context is None:
            return []
        return await self._context.cookies()

    async def restore_cookies(self, cookies: list[dict[str, Any]]) -> None:
        if self._context and cookies:
            await self._context.add_cookies(cookies)

    async def is_logged_out(self, logout_indicators: list[str]) -> bool:
        """Check if the current page indicates a logged-out state."""
        try:
            page = await self.get_page()
            content = await page.content()
            return any(indicator.lower() in content.lower() for indicator in logout_indicators)
        except Exception:
            return True

    async def close(self) -> None:
        try:
            if self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as exc:
            logger.warning("Error closing browser", job_id=self.job_id, error=str(exc))
        finally:
            self._context = None
            self._page = None
            self._playwright = None
            logger.info("Browser closed", job_id=self.job_id)

    async def restart(self) -> Page:
        """Gracefully close and relaunch the browser."""
        logger.info("Restarting browser", job_id=self.job_id)
        await self.close()
        await asyncio.sleep(2)
        return await self.launch()

    @staticmethod
    async def _human_delay(min_ms: int = 300, max_ms: int = 1000) -> None:
        delay = random.uniform(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)

    async def human_click(self, selector: str, timeout: int = 10_000) -> None:
        page = await self.get_page()
        await page.wait_for_selector(selector, timeout=timeout)
        await self._human_delay(100, 400)
        await page.click(selector)
        await self._human_delay(200, 600)

    async def wait_for_element(
        self, selector: str, timeout: int = 15_000
    ) -> bool:
        try:
            page = await self.get_page()
            await page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            return False

from __future__ import annotations

from typing import Any

from playwright.async_api import Page

# Selectors for IndiaMART seller lead / inquiry UI (tried in order)
INQUIRY_ROW_SELECTORS = [
    ".byr-inqry-list .byr-inqry-item",
    ".byr-inqry-item",
    ".inquiry-list-item",
    ".msg-list-item",
    "[data-testid='inquiry-item']",
    ".inqBox",
    "#leadList .lead-item",
    ".lead-card",
]

PAGE_READY_SELECTORS = [
    ".byr-inqry-list",
    ".inquiry-list-item",
    "#leadList",
    ".msg-list-item",
    ".seller-dashboard",
    "[class*='inqry']",
    "[class*='lead']",
]


def is_indiamart_seller_url(url: str) -> bool:
    u = (url or "").lower()
    return "seller.indiamart.com" in u


def is_indiamart_login_url(url: str) -> bool:
    u = (url or "").lower()
    return any(
        p in u
        for p in (
            "seller.indiamart.com/login",
            "indiamart.com/login",
            "indiamart.com/signin",
            "/sign-in",
            "/signin",
        )
    )


async def wait_for_page_ready(page: Page, timeout_ms: int = 45_000) -> bool:
    """Wait until inquiry/list UI or a generous timeout elapses."""
    per_selector = max(3_000, timeout_ms // len(PAGE_READY_SELECTORS))
    for selector in PAGE_READY_SELECTORS:
        try:
            await page.wait_for_selector(selector, timeout=per_selector, state="attached")
            return True
        except Exception:
            continue
    return False


async def collect_inquiry_text(page: Page) -> str:
    """Extract visible text from inquiry rows for keyword matching."""
    script = """
    (selectors) => {
      const parts = [];
      const seen = new Set();
      for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
          const t = (el.innerText || '').trim();
          if (t && t.length > 8 && !seen.has(t)) {
            seen.add(t);
            parts.push(t);
          }
        }
      }
      return parts.join('\\n---\\n');
    }
    """
    try:
        return await page.evaluate(script, INQUIRY_ROW_SELECTORS)
    except Exception:
        return ""

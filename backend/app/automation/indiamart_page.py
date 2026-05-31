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
    "[class*='Inquiry']",
    "[class*='inquiry']",
    "[class*='lead']",
    "[class*='bltxn']",
    "table tbody tr",
    ".list-group-item",
]

INDIAMART_LEADS_URL = "https://seller.indiamart.com/bltxn/?pref=recent"

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


async def scroll_lead_list(page: Page) -> None:
    """Load lazy-rendered IndiaMART lead rows."""
    try:
        await page.evaluate(
            """async () => {
              for (let i = 0; i < 4; i++) {
                window.scrollBy(0, Math.max(400, window.innerHeight * 0.6));
                await new Promise(r => setTimeout(r, 600));
              }
              window.scrollTo(0, 0);
            }"""
        )
    except Exception:
        pass


async def collect_inquiry_text(page: Page) -> str:
    """Extract visible text from inquiry rows for keyword matching."""
    await scroll_lead_list(page)
    script = """
    (selectors) => {
      const parts = [];
      const seen = new Set();
      const push = (t) => {
        const s = (t || '').trim().replace(/\\s+/g, ' ');
        if (s.length > 12 && !seen.has(s)) {
          seen.add(s);
          parts.push(s);
        }
      };
      for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
          push(el.innerText);
        }
      }
      if (parts.length < 3) {
        document.querySelectorAll('div, li, tr, article').forEach((el) => {
          const t = el.innerText || '';
          if (t.length > 20 && t.length < 1200) push(t);
        });
      }
      return parts.slice(0, 80).join('\\n---\\n');
    }
    """
    try:
        return await page.evaluate(script, INQUIRY_ROW_SELECTORS)
    except Exception:
        return ""

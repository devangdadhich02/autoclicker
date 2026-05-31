from __future__ import annotations

import json
import re
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

LEAD_CARD_CLICK_SELECTORS = [
    ".byr-inqry-item",
    ".byr-inqry-list .byr-inqry-item",
    ".inquiry-list-item",
    ".lead-card",
    "#leadList .lead-item",
    ".msg-list-item",
    "[class*='inqry']",
    "table tbody tr",
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


_TIME_AGO_RE = re.compile(
    r"\d+\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days)\s*ago",
    re.IGNORECASE,
)
_LOGGED_OUT_MARKERS = (
    "how to register",
    "success stories",
    "what can you sell",
    "sell for free on india",
    "indiamart advantage",
)
# Nav chrome on many pages includes "sign in" / "sell on indiamart" — not proof of logout.
_LOGGED_IN_MARKERS = (
    "lead manager",
    "seller dashboard",
    "my dashboard",
    "recent buy",
    "lms",
    "manage product",
    "catalog quality",
    "i am interested",
    "buyer also viewed",
    "enquiry",
    "inqry",
    "bltxn",
    "gst",
    "subscription",
    "credits left",
    "welcome",
    "logout",
    "sign out",
)


def is_indiamart_logged_out_body(text: str) -> bool:
    """
    True only for the public marketing landing — not seller nav chrome before SPA loads.
    Logged-in seller UI often still contains header links like Sign In.
    """
    snippet = (text or "").lower()
    if len(snippet) < 120:
        return False
    if _TIME_AGO_RE.search(snippet):
        return False
    if sum(1 for m in _LOGGED_IN_MARKERS if m in snippet) >= 2:
        return False
    strong_public = (
        "how to register" in snippet
        and "success stories" in snippet
        and ("what can you sell" in snippet or "sell for free" in snippet)
    )
    if strong_public:
        return True
    return sum(1 for m in _LOGGED_OUT_MARKERS if m in snippet) >= 3


def is_indiamart_marketing_landing(text: str) -> bool:
    """Public seller homepage — cookies not applied (not the logged-in LMS)."""
    t = (text or "").lower()
    if len(t) < 80:
        return False
    if _TIME_AGO_RE.search(t):
        return False
    return (
        "sign in" in t
        and "how to register" in t
        and "success stories" in t
    )


async def read_indiamart_page_text(page: Page, max_chars: int = 12_000) -> str:
    """Prefer lead-list/main content over site-wide header/footer chrome."""
    script = """
    (maxChars) => {
      const roots = [
        '#leadList', '.byr-inqry-list', '[class*="bltxn"]',
        '.seller-dashboard', 'main', '[role="main"]'
      ];
      for (const sel of roots) {
        const el = document.querySelector(sel);
        if (el) {
          const t = (el.innerText || '').trim();
          if (t.length > 80) return t.slice(0, maxChars);
        }
      }
      return (document.body.innerText || '').slice(0, maxChars);
    }
    """
    try:
        return await page.evaluate(script, max_chars)
    except Exception:
        try:
            return await page.evaluate(
                "(max) => (document.body.innerText || '').slice(0, max)",
                max_chars,
            )
        except Exception:
            return ""


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


async def click_recent_buy_leads_tab(page: Page) -> bool:
    """Ensure the Recent (not Missed/All) buy-leads tab is active."""
    patterns = (
        re.compile(r"^recent\s*buy\s*leads?$", re.I),
        re.compile(r"^recent$", re.I),
        re.compile(r"buy\s*leads", re.I),
    )
    for pattern in patterns:
        try:
            loc = page.get_by_text(pattern)
            n = await loc.count()
            for i in range(min(n, 5)):
                try:
                    await loc.nth(i).click(timeout=5000)
                    await page.wait_for_timeout(2000)
                    return True
                except Exception:
                    continue
        except Exception:
            continue
    try:
        clicked = await page.evaluate(
            """() => {
              const want = ['recent buy leads', 'recent', 'buy leads'];
              const nodes = [...document.querySelectorAll('a, button, span, div, li')];
              for (const el of nodes) {
                const t = (el.innerText || '').trim().toLowerCase();
                if (!t || t.length > 40) continue;
                if (want.some(w => t === w || t.startsWith(w))) {
                  el.click();
                  return true;
                }
              }
              return false;
            }"""
        )
        if clicked:
            await page.wait_for_timeout(2000)
            return True
    except Exception:
        pass
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


async def ensure_bltxn_leads_page(page: Page, fallback_url: str = INDIAMART_LEADS_URL) -> None:
    """Open recent buy leads with full URL + reload so persisted cookies apply."""
    target = INDIAMART_LEADS_URL
    if "bltxn" in (fallback_url or "").lower():
        target = fallback_url
    for attempt in range(2):
        try:
            await page.goto(target, wait_until="domcontentloaded", timeout=90_000)
        except Exception:
            pass
        if attempt == 1:
            try:
                await page.goto(
                    "https://seller.indiamart.com/",
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                await page.wait_for_timeout(2000)
                await page.goto(target, wait_until="domcontentloaded", timeout=90_000)
            except Exception:
                pass
        try:
            await page.wait_for_timeout(3000)
            if "#" not in (page.url or ""):
                await page.evaluate(
                    f"() => {{ window.location.assign({json.dumps(target)}); }}"
                )
                await page.wait_for_timeout(4000)
            try:
                await page.wait_for_load_state("networkidle", timeout=25_000)
            except Exception:
                pass
        except Exception:
            pass
        await wait_for_page_ready(page)
        await click_recent_buy_leads_tab(page)
        try:
            await page.wait_for_function(
                """() => {
                  const t = document.body.innerText || '';
                  return /\\d+\\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days)\\s*ago/i.test(t);
                }""",
                timeout=25_000,
            )
        except Exception:
            pass
        body = await read_indiamart_page_text(page, 8000)
        if _TIME_AGO_RE.search(body) or not is_indiamart_marketing_landing(body):
            break
        if attempt == 0:
            try:
                await page.reload(wait_until="domcontentloaded", timeout=60_000)
                await page.wait_for_timeout(4000)
            except Exception:
                pass
    await scroll_lead_list(page)


async def seller_session_is_authenticated(page: Page) -> bool:
    """True when page shows logged-in seller feed, not the public marketing landing."""
    body = await read_indiamart_page_text(page, 10_000)
    if _TIME_AGO_RE.search(body):
        return True
    return not is_indiamart_marketing_landing(body)


async def open_first_lead_card(page: Page) -> bool:
    """Open first visible lead so product title/location appear in DOM (like seller UI)."""
    await scroll_lead_list(page)
    for selector in LEAD_CARD_CLICK_SELECTORS:
        try:
            loc = page.locator(selector)
            if await loc.count() == 0:
                continue
            await loc.first.click(timeout=8000)
            await page.wait_for_timeout(3000)
            return True
        except Exception:
            continue
    try:
        clicked = await page.evaluate(
            """() => {
              const hints = ['i am interested', 'buyer', 'requirement', 'mins ago', 'hrs ago'];
              const nodes = [...document.querySelectorAll('div, li, tr, article, a, button')];
              for (const el of nodes) {
                const t = (el.innerText || '').trim().toLowerCase();
                if (t.length < 8 || t.length > 400) continue;
                if (hints.some(h => t.includes(h))) {
                  el.click();
                  return true;
                }
              }
              return false;
            }"""
        )
        if clicked:
            await page.wait_for_timeout(3000)
            return True
    except Exception:
        pass
    return False


async def collect_indiamart_scan_text(page: Page, open_first_lead: bool = True) -> str:
    """List page text + optional first-lead detail (matches what sellers see when clicking a lead)."""
    parts: list[str] = []
    list_text = await collect_inquiry_text(page)
    if list_text:
        parts.append(list_text)
    if open_first_lead:
        clicked = await open_first_lead_card(page)
        if clicked:
            try:
                detail = await page.evaluate("() => document.body.innerText || ''")
                if detail and len(detail) > 100:
                    parts.append(detail)
            except Exception:
                pass
    return "\n---\n".join(parts) if parts else ""


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

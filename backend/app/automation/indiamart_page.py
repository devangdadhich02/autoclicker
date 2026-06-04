from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from playwright.async_api import Page

logger = logging.getLogger(__name__)

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
    r"(?:just\s+now|\d+\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days)\s*ago)",
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
              const list = document.querySelector('#leadList, .byr-inqry-list, [class*="bltxn"]');
              if (list && list.scrollHeight > list.clientHeight + 40) {
                for (let i = 0; i < 6; i++) {
                  list.scrollTop = list.scrollHeight;
                  await new Promise(r => setTimeout(r, 500));
                }
                list.scrollTop = 0;
              }
              for (let i = 0; i < 8; i++) {
                window.scrollBy(0, Math.max(400, window.innerHeight * 0.55));
                await new Promise(r => setTimeout(r, 550));
              }
              window.scrollTo(0, 0);
            }"""
        )
    except Exception:
        pass


async def open_buy_leads_main_panel(page: Page) -> bool:
    """Click sidebar/main Buy Leads so SPA loads the recent feed (not nav-only chrome)."""
    try:
        # Most reliable path: links that explicitly route to bltxn.
        href_hit = await page.evaluate(
            """() => {
              const all = [...document.querySelectorAll('a[href*="bltxn"], a[href*="pref=recent"]')];
              const groups = [
                all.filter(a => (a.getAttribute('href') || '').toLowerCase().includes('pref=recent')),
                all.filter(a => !(a.getAttribute('href') || '').toLowerCase().includes('pref=relevant')),
                all,
              ];
              for (const links of groups) {
                for (const a of links) {
                  const r = a.getBoundingClientRect();
                  if (r.width < 6 || r.height < 6) continue;
                  try { a.click(); return true; } catch (e) {}
                }
              }
              return false;
            }"""
        )
        if href_hit:
            await page.wait_for_timeout(3000)
            return True
    except Exception:
        pass
    try:
        clicked = await page.evaluate(
            """() => {
              const skip = /sign in|help|logout|products|photos|invoice|settings|tally/i;
              const want = /buy\\s*leads?/i;
              const nodes = [...document.querySelectorAll('a, button, span, div, li')];
              for (const el of nodes) {
                const t = (el.innerText || '').trim();
                if (!t || t.length > 36 || skip.test(t)) continue;
                const compact = t.replace(/\\s+/g, '').toLowerCase();
                if (!want.test(t) && !compact.startsWith('buyleads')) continue;
                const r = el.getBoundingClientRect();
                if (r.width < 8 || r.height < 8) continue;
                // React-friendly click sequence
                el.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
                el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }));
                el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0 }));
                el.click();
                return true;
              }
              return false;
            }"""
        )
        if clicked:
            await page.wait_for_timeout(3500)
            return True
    except Exception:
        pass
    
    # Fallback to aggressive strategy
    return await _aggressive_open_buy_leads(page)


async def _aggressive_open_buy_leads(page: Page) -> bool:
    """
    Aggressive click simulation for React-based IndiaMART SPA.
    Uses full event sequence (mouseenter, mousedown, mouseup, click) 
    and tries multiple selector strategies.
    """
    
    # Strategy 0: Try new IndiaMART layout selectors first (2024-2025)
    try:
        new_selectors = [
            "[data-testid='buy-leads-link']",
            "[data-testid='recent-buy-leads']",
            "a[href*='pref=recent']",
            "a[href*='bltxn']",
            "a[href*='/bltxn/']",
            "[class*='BuyLeads']",
            "[class*='buy-leads']",
            "nav a:has-text('Buy Leads')",
            "aside a:has-text('Buy Leads')",
            "sidebar a:has-text('Buy Leads')",
            "li:has-text('Buy Leads') a",
        ]
        for sel in new_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.scroll_into_view_if_needed(timeout=2000)
                    await loc.click(timeout=5000)
                    logger.info(f"Strategy 0 success with selector: {sel}")
                    await page.wait_for_timeout(5000)  # Wait longer for SPA
                    return True
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"Strategy 0 failed: {e}")
    
    # Strategy 1: Direct href navigation via JS evaluation
    try:
        clicked = await page.evaluate(
            """() => {
              // Find Buy Leads links with specific patterns
              const links = [...document.querySelectorAll('a')];
              for (const a of links) {
                const href = (a.getAttribute('href') || '').toLowerCase();
                const text = (a.innerText || '').toLowerCase().trim();
                
                // Check for bltxn pattern in href or buy leads in text
                if (href.includes('bltxn') || href.includes('pref=recent') ||
                    text === 'buy leads' || text === 'recent buy leads' ||
                    text.includes('buyleads')) {
                  
                  // Full click simulation for React
                  const rect = a.getBoundingClientRect();
                  if (rect.width < 6 || rect.height < 6) continue;
                  
                  // Dispatch full event sequence
                  a.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
                  a.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                  a.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }));
                  a.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0 }));
                  a.click();
                  a.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                  
                  return { success: true, method: 'full_event_sequence', text: a.innerText.slice(0, 50) };
                }
              }
              return { success: false, method: 'none' };
            }"""
        )
        if clicked and clicked.get('success'):
            logger.info(f"Strategy 1 success: {clicked.get('text', 'unknown')}")
            await page.wait_for_timeout(5000)  # Increased wait
            return True
    except Exception as e:
        logger.warning(f"Strategy 1 failed: {e}")
    
    # Strategy 2: Look for Buy Leads in sidebar navigation with specific class patterns
    try:
        clicked = await page.evaluate(
            r"""() => {
              const skipTerms = /sign\s*in|login|logout|help|settings|tally|products|photos|invoices/i;
              const wantTerms = /buy\s*leads|recent\s*buy|buyleads|buy\s*lead/i;
              
              const candidates = [...document.querySelectorAll('a, button, [role="button"], [role="link"], li')];
              
              for (const el of candidates) {
                const text = (el.innerText || el.textContent || '').trim();
                if (!text || text.length > 40 || skipTerms.test(text)) continue;
                
                const cleanText = text.toLowerCase().replace(/\s+/g, ' ');
                if (wantTerms.test(cleanText)) {
                  const rect = el.getBoundingClientRect();
                  if (rect.width < 8 || rect.height < 8 || rect.top < 0 || rect.left < 0) continue;
                  
                  // Try React-friendly click
                  el.focus();
                  el.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
                  el.dispatchEvent(new Event('focus', { bubbles: true }));
                  el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }));
                  el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0 }));
                  el.click();
                  
                  return { success: true, text: text.slice(0, 50) };
                }
              }
              return { success: false };
            }"""
        )
        if clicked and clicked.get('success'):
            logger.info(f"Strategy 2 success: {clicked.get('text', 'unknown')}")
            await page.wait_for_timeout(4000)
            return True
    except Exception as e:
        logger.warning(f"Strategy 2 failed: {e}")
    
    # Strategy 3: Use Playwright's native click with force option
    try:
        patterns = [
            'a:has-text("Buy Leads")',
            'a:has-text("Recent Buy Leads")',
            '[class*="buy-lead"]',
            '[class*="buyleads"]',
            '[href*="bltxn"]',
        ]
        for pattern in patterns:
            try:
                loc = page.locator(pattern).first
                if await loc.count() > 0:
                    await loc.click(force=True, timeout=5000)
                    logger.info(f"Strategy 3 success with pattern: {pattern}")
                    await page.wait_for_timeout(4000)
                    return True
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Strategy 3 failed: {e}")
    
    # Strategy 4: Navigate directly via React Router if hash routing detected
    try:
        current_url = page.url or ""
        if 'seller.indiamart.com' in current_url:
            await page.evaluate(
                """() => {
                  // Try to use React Router navigation
                  if (window.ReactRouter && window.ReactRouter.history) {
                    window.ReactRouter.history.push('/bltxn?pref=recent');
                  } else if (window.history && window.history.pushState) {
                    window.history.pushState({}, '', '/bltxn/?pref=recent');
                    // Dispatch popstate to trigger any listeners
                    window.dispatchEvent(new PopStateEvent('popstate'));
                  }
                }"""
            )
            logger.info("Strategy 4: React Router navigation attempted")
            await page.wait_for_timeout(4000)
            return True
    except Exception as e:
        logger.warning(f"Strategy 4 failed: {e}")
    
    logger.warning("All aggressive strategies failed")
    return False


async def ensure_bltxn_leads_page(
    page: Page,
    fallback_url: str = INDIAMART_LEADS_URL,
    heartbeat: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Open recent buy leads with full URL + reload so persisted cookies apply."""

    async def beat() -> None:
        if heartbeat is None:
            return
        try:
            await heartbeat()
        except Exception:
            pass

    target = INDIAMART_LEADS_URL
    if "bltxn" in (fallback_url or "").lower():
        target = fallback_url

    for attempt in range(3):  # 3 attempts with increasing delays
        await beat()
        logger.info(f"ensure_bltxn_leads_page attempt {attempt + 1}/3, target={target}")

        # Primary: domcontentloaded (faster, more reliable for IndiaMART SPA)
        # Fallback: networkidle only if DOM looks incomplete
        try:
            await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
            # Increased wait for React to hydrate - new IndiaMART is slower
            await page.wait_for_timeout(4000)
            await beat()
        except Exception as e:
            logger.warning(f"domcontentloaded navigation failed: {e}, trying networkidle")
            try:
                await page.goto(target, wait_until="networkidle", timeout=45_000)
                await page.wait_for_timeout(3000)
                await beat()
            except Exception as e2:
                logger.error(f"Navigation failed: {e2}")

        # If still no time markers, try dashboard home first then navigate
        if attempt >= 1:
            try:
                logger.info("Trying dashboard-first navigation strategy")
                # Load dashboard with shorter timeout
                await page.goto(
                    "https://seller.indiamart.com/",
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                await page.wait_for_timeout(2000)
                await beat()
                # Use React Router hash navigation
                await page.evaluate(
                    """() => {
                        window.location.hash = '#/bltxn?pref=recent';
                        // Trigger hashchange for React Router
                        window.dispatchEvent(new HashChangeEvent('hashchange'));
                    }"""
                )
                await page.wait_for_timeout(3000)
                # Final load with domcontentloaded
                await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(1500)
                await beat()
            except Exception as e:
                logger.warning(f"Dashboard-first navigation failed: {e}")

        # Ensure proper URL with hash routing if needed
        try:
            await page.wait_for_timeout(2000)
            current_url = page.url or ""
            logger.info(f"Current URL after navigation: {current_url}")

            if "bltxn" not in current_url.lower() or "pref=relevant" in current_url.lower():
                logger.info("Forcing bltxn URL via window.location")
                await page.evaluate(
                    f"""() => {{
                        window.location.href = '{target}';
                    }}"""
                )
                await page.wait_for_timeout(4000)
                await beat()

            # Wait for network to be idle (API calls complete)
            try:
                await page.wait_for_load_state("networkidle", timeout=20_000)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"URL manipulation error: {e}")
        
        # Wait for page to be ready
        await wait_for_page_ready(page)
        
        # Try to open Buy Leads panel with enhanced click simulation
        panel_opened = await open_buy_leads_main_panel(page)
        logger.info(f"Buy Leads panel opened: {panel_opened}")
        await beat()

        if "pref=relevant" in (page.url or "").lower():
            logger.info("Buy Leads click landed on relevant feed, forcing recent feed")
            await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(2500)
            await beat()

        # Try to click Recent tab
        recent_clicked = await click_recent_buy_leads_tab(page)
        logger.info(f"Recent tab clicked: {recent_clicked}")
        await beat()

        if "pref=relevant" in (page.url or "").lower():
            logger.info("Recent tab click left relevant feed active, forcing recent feed")
            await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(2500)
            await beat()

        # Wait for time markers to appear
        time_markers_found = False
        try:
            await page.wait_for_function(
                """() => {
                  const t = document.body.innerText || '';
                  return /just\\s+now|\\d+\\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days)\\s*ago/i.test(t);
                }""",
                timeout=20_000,
            )
            time_markers_found = True
            logger.info("Time markers found in DOM")
        except Exception:
            logger.warning("Time markers not found within timeout")
        await beat()

        await scroll_lead_list(page)

        # Check current state
        body = await read_indiamart_page_text(page, 12_000)
        has_time_ago = bool(_TIME_AGO_RE.search(body))
        logger.info(f"Page check - has_time_ago: {has_time_ago}, body_length: {len(body)}")
        
        nav_only = (
            "buy leads" in body.lower()
            and "dashboard" in body.lower()
            and not has_time_ago
        )
        
        if nav_only:
            logger.warning("SPA stuck on nav-only view, forcing hard reload")
            # SPA sometimes lands on shell-only view (menu chrome). Force real route.
            try:
                # Hard reload with cache clear
                await page.evaluate("() => { location.reload(true); }")
                await page.wait_for_timeout(3000)
                await beat()

                # Re-navigate with domcontentloaded (faster)
                await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(2000)
                await beat()

                # Try aggressive panel opening
                await _aggressive_open_buy_leads(page)
                if "pref=relevant" in (page.url or "").lower():
                    await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
                    await page.wait_for_timeout(2500)
                await beat()
                await scroll_lead_list(page)

                body = await read_indiamart_page_text(page, 12_000)
                has_time_ago = bool(_TIME_AGO_RE.search(body))
                logger.info(f"After hard reload - has_time_ago: {has_time_ago}")
            except Exception as e:
                logger.error(f"Hard reload failed: {e}")
        
        # If we have time markers or we're not on marketing landing, we're good
        if has_time_ago:
            logger.info("Success: Time markers found, breaking out of retry loop")
            break

        if not is_indiamart_marketing_landing(body):
            logger.info("Not on marketing landing, assuming logged in")
            # Still try to get time markers one more time
            if attempt < 2:
                continue
            break
        
        # Marketing landing detected, need to retry
        logger.warning(f"Marketing landing detected on attempt {attempt + 1}")
        
        if attempt < 2:
            logger.info(f"Retrying navigation (attempt {attempt + 2}/3)")
            await asyncio.sleep(3)

    if "pref=relevant" in (page.url or "").lower():
        logger.info("Final URL still relevant, forcing recent before returning")
        try:
            await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(2500)
            await beat()
        except Exception:
            pass

    await scroll_lead_list(page)

    # Final check
    final_body = await read_indiamart_page_text(page, 8_000)
    final_has_time = bool(_TIME_AGO_RE.search(final_body))
    logger.info(f"ensure_bltxn_leads_page complete - final_has_time: {final_has_time}")


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

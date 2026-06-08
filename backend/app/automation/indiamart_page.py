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

_NON_RECENT_BUY_LEAD_URL_MARKERS = (
    "pref=relevant",
    "pref=other_leads",
    "pref=all",
    "/buyersearch/",
    "screen=view_similar_leads",
    "view_similar_leads",
)

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


def _is_non_recent_buy_leads_url(url: str) -> bool:
    u = (url or "").lower()
    return "seller.indiamart.com" in u and "bltxn" in u and any(
        marker in u for marker in _NON_RECENT_BUY_LEAD_URL_MARKERS
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
    """Ensure the Recent (not Missed/All) buy-leads tab is active.
    Only clicks tab elements — not the sidebar nav link (which causes re-navigation)."""
    # Only click tab-like elements (role=tab, or button/span with exact "Recent" text)
    tab_selectors = [
        "[role='tab']:has-text('Recent')",
        "button:has-text('Recent Buy Leads')",
        "button:has-text('Recent')",
        "a:has-text('Recent')",
        "[data-testid='recent-tab']",
        "[data-testid='recent-buy-leads-tab']",
    ]
    for sel in tab_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                await loc.click(timeout=3000)
                await page.wait_for_timeout(1000)
                return True
        except Exception:
            continue
    try:
        clicked = await page.evaluate(
            """() => {
              const clickLikeUser = (el) => {
                el.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
                el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }));
                el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0 }));
                el.click();
              };

              // First try tab-role elements or buttons.
              const tabNodes = [...document.querySelectorAll(
                '[role="tab"], button, [class*="tab"]'
              )];
              for (const el of tabNodes) {
                const t = (el.innerText || '').trim().toLowerCase();
                if (t === 'recent' || t === 'recent buy leads') {
                  const r = el.getBoundingClientRect();
                  if (r.width < 4 || r.height < 4) continue;
                  clickLikeUser(el);
                  return true;
                }
              }

              // IndiaMART sometimes renders these as plain visible text nodes inside
              // div/span/li/a elements after the shell loads.
              const broadNodes = [...document.querySelectorAll('a, button, div, span, li')];
              for (const el of broadNodes) {
                const t = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').toLowerCase();
                if (t !== 'recent' && t !== 'recent buy leads') continue;
                const href = (el.getAttribute('href') || '').toLowerCase();
                if (href && !href.includes('bltxn')) continue;
                const r = el.getBoundingClientRect();
                if (r.width < 4 || r.height < 4) continue;
                if (r.top < 0 || r.bottom > window.innerHeight + 400) continue;
                clickLikeUser(el);
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
    return False


async def click_buy_leads_tab_by_label(page: Page, label: str) -> bool:
    """Click visible BuyLeads tab labels like Recent, Relevant, or More Leads."""
    label_norm = label.strip().lower()
    if not label_norm:
        return False
    try:
        clicked = await page.evaluate(
            """(label) => {
              const clickLikeUser = (el) => {
                el.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
                el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }));
                el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0 }));
                el.click();
              };
              const nodes = [...document.querySelectorAll('[role="tab"], a, button, div, span, li')];
              for (const el of nodes) {
                const t = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').toLowerCase();
                if (t !== label) continue;
                const r = el.getBoundingClientRect();
                if (r.width < 4 || r.height < 4) continue;
                if (r.top < 0 || r.bottom > window.innerHeight + 500) continue;
                clickLikeUser(el);
                return true;
              }
              return false;
            }""",
            label_norm,
        )
        if clicked:
            await page.wait_for_timeout(3500)
            return True
    except Exception:
        pass
    return False


async def scroll_lead_list(page: Page, aggressive: bool = False) -> None:
    """Load lazy-rendered IndiaMART lead rows.
    
    Args:
        aggressive: If True, scroll more extensively to load all possible leads.
    """
    scroll_iterations = 25 if aggressive else 12
    container_iterations = 20 if aggressive else 10
    
    try:
        await page.evaluate(
            """async (config) => {
              const { containerIter, scrollIter } = config;
              
              // Try multiple container selectors for lead list
              const listSelectors = [
                '#leadList', '.byr-inqry-list', '[class*="bltxn"]',
                '[class*="lead-list"]', '[class*="inquiry-list"]',
                '.msg-list', 'main', '[role="main"]'
              ];
              
              let list = null;
              for (const sel of listSelectors) {
                const el = document.querySelector(sel);
                if (el && el.scrollHeight > el.clientHeight + 40) {
                  list = el;
                  break;
                }
              }
              
              // Scroll the container if found - keep scrolling until no new content
              if (list) {
                let prevHeight = 0;
                let sameHeightCount = 0;
                for (let i = 0; i < containerIter; i++) {
                  list.scrollTop = list.scrollHeight;
                  await new Promise(r => setTimeout(r, 700));
                  
                  // Check if new content loaded
                  if (list.scrollHeight === prevHeight) {
                    sameHeightCount++;
                    if (sameHeightCount >= 3) break; // No more content loading
                  } else {
                    sameHeightCount = 0;
                    prevHeight = list.scrollHeight;
                  }
                }
                list.scrollTop = 0;
                await new Promise(r => setTimeout(r, 300));
              }
              
              // Also scroll the window (for different layouts) - stop only when it no longer moves.
              let stuckWindowCount = 0;
              for (let i = 0; i < scrollIter; i++) {
                const beforeY = window.scrollY || window.pageYOffset || 0;
                window.scrollBy(0, Math.max(600, window.innerHeight * 0.7));
                await new Promise(r => setTimeout(r, 600));

                const afterY = window.scrollY || window.pageYOffset || 0;
                if (afterY <= beforeY + 4) {
                  stuckWindowCount++;
                  if (stuckWindowCount >= 3) break;
                } else {
                  stuckWindowCount = 0;
                }
              }
              
              // Click "Load More" or "Show More" buttons multiple times
              const loadMoreSelectors = [
                '[class*="load-more"]', '[class*="show-more"]',
                '[class*="loadmore"]', '[class*="showmore"]'
              ];
              
              // Also find buttons by text content
              const allButtons = [...document.querySelectorAll('button, a, div[role="button"], span[role="button"]')];
              const loadMoreBtns = allButtons.filter(el => {
                const txt = (el.innerText || el.textContent || '').toLowerCase();
                return txt.includes('load more') || txt.includes('show more') || 
                       txt.includes('view more') || txt.includes('see more');
              });
              
              // Click load more buttons repeatedly until they disappear
              for (let attempt = 0; attempt < 5; attempt++) {
                let clicked = false;
                
                for (const sel of loadMoreSelectors) {
                  try {
                    const btn = document.querySelector(sel);
                    if (btn && btn.offsetParent !== null) {
                      btn.click();
                      await new Promise(r => setTimeout(r, 1500));
                      clicked = true;
                    }
                  } catch(e) {}
                }
                
                for (const btn of loadMoreBtns) {
                  try {
                    if (btn.offsetParent !== null) {
                      btn.click();
                      await new Promise(r => setTimeout(r, 1500));
                      clicked = true;
                    }
                  } catch(e) {}
                }
                
                if (!clicked) break;
                
                // Scroll down after loading more
                window.scrollBy(0, 500);
                await new Promise(r => setTimeout(r, 500));
              }
              
              // Scroll back to top
              window.scrollTo(0, 0);
              if (list) list.scrollTop = 0;
            }""",
            {"containerIter": container_iterations, "scrollIter": scroll_iterations}
        )
    except Exception:
        pass
    
    # Also try Playwright-based load more click - multiple attempts
    for _ in range(3):
        clicked = False
        try:
            for sel in [
                "button:has-text('Load More')", "button:has-text('Show More')",
                "button:has-text('View More')", "button:has-text('See More')",
                "a:has-text('Load More')", "a:has-text('Show More')",
                "[class*='load-more']", "[class*='show-more']"
            ]:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=3000)
                    await page.wait_for_timeout(1500)
                    clicked = True
                    break
        except Exception:
            pass
        if not clicked:
            break


async def open_buy_leads_main_panel(page: Page) -> bool:
    """Click sidebar/main Buy Leads so SPA loads the recent feed (not nav-only chrome)."""
    try:
        # Most reliable path: links that explicitly route to bltxn/recent.
        # Score candidates so the real "BuyLeads" child wins before a generic
        # "Lead Manager" parent that can leave the SPA in a nav-only shell.
        href_hit = await page.evaluate(
            """() => {
              const candidates = [];
              const links = [...document.querySelectorAll('a, button, [role="link"], [role="button"]')];
              for (const el of links) {
                const href = (el.getAttribute('href') || '').toLowerCase();
                const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                const compact = text.replace(/\\s+/g, '');
                if (!href.includes('bltxn') && !href.includes('pref=recent') && !/^buyleads?$/.test(compact)) {
                  continue;
                }
                if (href.includes('pref=relevant')) continue;
                const r = el.getBoundingClientRect();
                if (r.width < 6 || r.height < 6) continue;
                let score = 0;
                if (href.includes('pref=recent')) score += 50;
                if (href.includes('bltxn')) score += 35;
                if (/^buyleads?$/.test(compact)) score += 45;
                if (text.includes('lead manager')) score -= 20;
                score -= Math.min(text.length, 80) / 10;
                candidates.push({ el, score });
              }
              candidates.sort((a, b) => b.score - a.score);
              for (const item of candidates) {
                try {
                  const el = item.el;
                  el.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
                  el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }));
                  el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0 }));
                  el.click();
                  return true;
                } catch (e) {}
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
              const want = /buy\\s*leads?|lead\\s*manager|buyleads/i;
              const nodes = [...document.querySelectorAll('a, button, span, div, li')];
              const candidates = [];
              for (const el of nodes) {
                const t = (el.innerText || '').trim();
                if (!t || t.length > 36 || skip.test(t)) continue;
                const compact = t.replace(/\\s+/g, '').toLowerCase();
                if (!want.test(t) && !compact.startsWith('buyleads') && !compact.startsWith('leadmanager')) continue;
                const r = el.getBoundingClientRect();
                if (r.width < 8 || r.height < 8) continue;
                let score = 0;
                if (/^buyleads?$/.test(compact)) score += 60;
                if (/^buy\\s*leads?$/.test(t.toLowerCase())) score += 55;
                if (compact.startsWith('leadmanager')) score += 10;
                score -= Math.min(t.length, 60) / 10;
                candidates.push({ el, score });
              }
              candidates.sort((a, b) => b.score - a.score);
              for (const item of candidates) {
                const el = item.el;
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
            # Lead Manager (visible in logs)
            "a:has-text('Lead Manager')",
            "[class*='LeadManager']",
            "li:has-text('Lead Manager') a",
            # BuyLeads links
            "a:has-text('BuyLeads')",
            "a:has-text('Buy Leads')",
            "[data-testid='buy-leads-link']",
            "[data-testid='recent-buy-leads']",
            "a[href*='pref=recent']",
            "a[href*='bltxn']",
            "a[href*='/bltxn/']",
            "[class*='BuyLeads']",
            "[class*='buy-leads']",
            "nav a:has-text('Buy Leads')",
            "aside a:has-text('Buy Leads')",
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


async def _page_has_time_marker(page: Page) -> bool:
    try:
        body = await page.evaluate("() => document.body.innerText || ''")
    except Exception:
        body = ""
    return bool(_TIME_AGO_RE.search(body))


async def _log_nav_shell_diagnostics(page: Page, label: str) -> None:
    """Log what the nav-only shell exposes so route changes are debuggable remotely."""
    try:
        data = await page.evaluate(
            """() => {
              const items = [...document.querySelectorAll('a, button, [role="link"], [role="button"]')]
                .map((el) => {
                  const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
                  const href = el.getAttribute('href') || '';
                  const r = el.getBoundingClientRect();
                  return { text: text.slice(0, 80), href: href.slice(0, 140), visible: r.width > 4 && r.height > 4 };
                })
                .filter((x) => x.visible && (x.text || x.href))
                .slice(0, 35);
              return {
                url: location.href,
                title: document.title,
                body_length: (document.body.innerText || '').length,
                items,
              };
            }"""
        )
        logger.info(
            "IndiaMART nav-shell diagnostics label=%s diagnostic=%s",
            label,
            json.dumps(data, ensure_ascii=False)[:4_000],
        )
    except Exception as exc:
        logger.info(
            "IndiaMART nav-shell diagnostics failed label=%s error=%s",
            label,
            exc,
        )


async def _try_bltxn_route_variants(
    page: Page,
    target: str,
    heartbeat: Callable[[], Awaitable[None]],
) -> bool:
    """Try direct seller route variants when the SPA renders only the sidebar shell."""
    await _log_nav_shell_diagnostics(page, "before_route_variants")
    candidates: list[str] = []

    try:
        discovered = await page.evaluate(
            """() => [...document.querySelectorAll('a[href]')]
              .map((a) => a.href)
              .filter((href) => /bltxn|buy-?leads?|leadmanager|lead-manager/i.test(href))
              .slice(0, 20)"""
        )
        if isinstance(discovered, list):
            candidates.extend(str(url) for url in discovered)
    except Exception:
        pass

    candidates.extend(
        [
            target,
            "https://seller.indiamart.com/bltxn/",
            "https://seller.indiamart.com/bltxn",
            "https://seller.indiamart.com/bltxn/?pref=recent",
            "https://seller.indiamart.com/bltxn/?pref=recent#recent",
            "https://seller.indiamart.com/bltxn/#recent",
            "https://seller.indiamart.com/bltxn/?pref=all",
        ]
    )

    seen: set[str] = set()
    unique_candidates = []
    for url in candidates:
        if not url or url in seen:
            continue
        lowered = url.lower()
        if _is_non_recent_buy_leads_url(lowered):
            continue
        seen.add(url)
        unique_candidates.append(url)

    for idx, url in enumerate(unique_candidates[:12], start=1):
        try:
            logger.info("Trying IndiaMART route variant attempt=%s url=%s", idx, url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(3500)
            await heartbeat()
            try:
                await page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass
            if await _page_has_time_marker(page):
                logger.info("IndiaMART route variant loaded buyer rows url=%s", url)
                return True
            clicked = await click_recent_buy_leads_tab(page)
            logger.info(
                "IndiaMART tab click attempt label=%s clicked=%s url=%s",
                "Recent",
                clicked,
                url,
            )
            if clicked:
                await page.wait_for_timeout(3000)
                if await _page_has_time_marker(page):
                    logger.info(
                        "IndiaMART tab loaded buyer rows label=%s url=%s",
                        "Recent",
                        url,
                    )
                    return True
            body_after_recent = await read_indiamart_page_text(page, 2_000)
            if bool(_TIME_AGO_RE.search(body_after_recent)):
                logger.info(
                    "IndiaMART Recent feed loaded buyer rows url=%s",
                    url,
                )
                return True
            body = await read_indiamart_page_text(page, 2_000)
            logger.info(
                "IndiaMART route variant still has no buyer rows url=%s body_length=%s has_time=%s",
                url,
                len(body),
                bool(_TIME_AGO_RE.search(body)),
            )
        except Exception as exc:
            logger.warning("IndiaMART route variant failed url=%s error=%s", url, exc)

    await _log_nav_shell_diagnostics(page, "after_route_variants")
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
    fallback_lower = (fallback_url or "").lower()
    if "bltxn" in fallback_lower and not _is_non_recent_buy_leads_url(fallback_lower):
        target = fallback_url

    for attempt in range(3):
        await beat()
        logger.info(f"ensure_bltxn_leads_page attempt {attempt + 1}/3, target={target}")

        # Navigate directly to recent leads URL
        try:
            await page.goto(target, wait_until="domcontentloaded", timeout=35_000)
            await page.wait_for_timeout(2000)
            await beat()
        except Exception as e:
            logger.warning(f"Navigation failed: {e}")

        current_url = page.url or ""
        logger.info(f"Current URL after navigation: {current_url}")

        # Fix: if landed on relevant/suggested feed, force Recent.
        if _is_non_recent_buy_leads_url(current_url):
            try:
                await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(1500)
                await beat()
            except Exception:
                pass

        # Wait for network calls to settle (SPA data fetch)
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        await beat()

        # Try clicking Recent tab to ensure the feed is visible
        recent_clicked = await click_recent_buy_leads_tab(page)
        logger.info(f"Recent tab clicked: {recent_clicked}")
        await beat()

        # Wait for time markers (real leads) to appear - short timeout
        try:
            await page.wait_for_function(
                """() => {
                  const t = document.body.innerText || '';
                  return /just\\s+now|\\d+\\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days)\\s*ago/i.test(t);
                }""",
                timeout=12_000,
            )
            logger.info("Time markers found in DOM")
            await beat()
            await scroll_lead_list(page)
            break  # success — leads are visible
        except Exception:
            logger.warning("Time markers not found within timeout")

        await beat()
        await scroll_lead_list(page)

        # Check if page has real lead content (even without time markers)
        body = await read_indiamart_page_text(page, 4_000)
        has_time_ago = bool(_TIME_AGO_RE.search(body))
        logger.info(f"Page check - has_time_ago: {has_time_ago}, body_length: {len(body)}")

        # Nav-only shell: body is small and only has menu items, no lead data
        nav_only = (
            not has_time_ago
            and len(body) < 1500
            and "buy leads" in body.lower()
            and "dashboard" in body.lower()
        )

        if nav_only and attempt < 2:
            logger.warning("SPA stuck on nav-only view, trying sidebar click first")
            await _log_nav_shell_diagnostics(page, f"nav_only_attempt_{attempt + 1}")
            
            # First try: Click sidebar "Buy Leads" / "Lead Manager" link to trigger SPA
            sidebar_clicked = await open_buy_leads_main_panel(page)
            logger.info(f"Sidebar Buy Leads click result: {sidebar_clicked}")
            await beat()
            
            if sidebar_clicked:
                # Wait for SPA content to load after sidebar click
                try:
                    await page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:
                    pass
                await page.wait_for_timeout(3000)
                
                # Check if leads are now visible
                body = await read_indiamart_page_text(page, 4_000)
                has_time_ago = bool(_TIME_AGO_RE.search(body))
                logger.info(f"After sidebar click - has_time_ago: {has_time_ago}, body_length: {len(body)}")
                
                if has_time_ago or len(body) > 2000:
                    # SPA loaded successfully
                    await scroll_lead_list(page)
                    break

            route_loaded = await _try_bltxn_route_variants(page, target, beat)
            if route_loaded:
                await scroll_lead_list(page)
                break
            
            # Fallback: Hard reload if sidebar click didn't work
            logger.warning("Sidebar click didn't load content, forcing hard reload")
            try:
                await page.evaluate("() => { location.reload(true); }")
                await page.wait_for_timeout(4000)
                await beat()
            except Exception as e:
                logger.error(f"Hard reload failed: {e}")
            
            body = await read_indiamart_page_text(page, 4_000)
            has_time_ago = bool(_TIME_AGO_RE.search(body))
            logger.info(f"After hard reload - has_time_ago: {has_time_ago}")

            if not is_indiamart_marketing_landing(body):
                logger.info("Not on marketing landing, assuming logged in")
                continue

        # If we have time markers, we're done
        if has_time_ago:
            logger.info("Success: Time markers found, breaking out of retry loop")
            break

        if not is_indiamart_marketing_landing(body):
            logger.info("Not on marketing landing, assuming logged in")
            if attempt < 2:
                continue
            break

        logger.warning(f"Marketing landing detected on attempt {attempt + 1}")
        if attempt < 2:
            await asyncio.sleep(3)

    final_url = (page.url or "").lower()
    if _is_non_recent_buy_leads_url(final_url):
        logger.info("Final URL is not Recent, forcing recent before returning")
        try:
            await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(1500)
            await beat()
        except Exception:
            pass

    await scroll_lead_list(page)

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

from __future__ import annotations

import re
from dataclasses import dataclass

from playwright.async_api import Page

from app.automation.indiamart_page import (
    INQUIRY_ROW_SELECTORS,
    scroll_lead_list,
)

# Navigation / catalog text that must never count as a buyer lead
_NON_LEAD_PHRASES = (
    "parts & spares",
    "parts and spares",
    "seller dashboard",
    "my dashboard",
    "help center",
    "subscription",
    "buy leads",
    "add product",
    "manage products",
    "lead manager",
    "view all",
    "see all",
    "catalog",
    "my products",
    "business loan",
    "buying interests",
    "selling items",
    "buyer viewed",
    "you sell",
    "you viewed",
    "member since",
    "requirements ·",
    "calls ·",
    "replies",
)

# Real IndiaMART buyer rows usually include time, interest, or verification cues
_BUYER_ROW_HINTS = (
    "min ago",
    "mins ago",
    "hr ago",
    "hrs ago",
    "hour ago",
    "day ago",
    "days ago",
    "i am interested",
    "requirement",
    "buyer",
    "gst",
    "whatsapp",
    "phone",
    "verified",
    "requirement type",
    "business use",
)

_TIME_RE = re.compile(
    r"\b\d+\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days)\s*ago\b",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"(?:\+91[\s-]?)?[6-9]\d{9}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", re.IGNORECASE)
_LOCATION_RE = re.compile(
    r"\b(?:new\s+delhi|delhi|mumbai|bangalore|bengaluru|punjab|haryana|gujarat|"
    r"kolkata|chennai|hyderabad|noida|gurgaon|gurugram|uttar\s+pradesh|"
    r"maharashtra|rajasthan|kheda|ahmedabad|surat|pune|jaipur|lucknow|"
    r"indore|bhopal|kanpur|nagpur|thane|vadodara|coimbatore|kochi|"
    r"kerala|tamil\s+nadu|karnataka|west\s+bengal|madhya\s+pradesh)\b",
    re.IGNORECASE,
)
# "Kheda, Gujarat" / "Mumbai, Maharashtra" style lines
_CITY_STATE_RE = re.compile(
    r"[A-Za-z][A-Za-z\s]{1,40},\s*[A-Za-z][A-Za-z\s]{2,30}",
)

_GENERIC_MATCH_WORDS = frozenset(
    {
        "metal",
        "machine",
        "steel",
        "pipe",
        "parts",
        "spares",
        "product",
        "products",
        "industrial",
        "equipment",
    }
)


@dataclass
class BuyerLeadBlock:
    text: str
    row_index: int
    selector: str


def is_buyer_inquiry_block(text: str) -> bool:
    """True when text looks like a BuyLead / recent inquiry row, not site chrome."""
    return is_seller_incoming_buy_lead(text)


def is_seller_incoming_buy_lead(text: str) -> bool:
    """
    Incoming buyer on this seller's Recent Buy Leads feed — not nav, not buyer profile sidebar.
    """
    t = (text or "").strip()
    if len(t) < 35 or len(t) > 3000:
        return False
    lower = t.lower()
    if any(p in lower for p in _NON_LEAD_PHRASES):
        return False
    if not _TIME_RE.search(t):
        return False
    has_product_line = False
    for line in t.splitlines():
        line = line.strip()
        if not line or _TIME_RE.fullmatch(line):
            continue
        if re.search(r"[a-zA-Z]{4,}", line) and len(line) > 5:
            has_product_line = True
            break
    has_interest = (
        "interested" in lower
        or "requirement" in lower
        or "category" in lower
        or "sold out" in lower
        or "business use" in lower
    )
    has_loc = bool(_LOCATION_RE.search(t)) or bool(_CITY_STATE_RE.search(t))
    return has_product_line and (has_interest or has_loc)


def is_weak_match_context(snippet: str, keyword: str) -> bool:
    """Reject matches that only hit generic catalog/nav words."""
    s = (snippet or "").lower()
    if any(p in s for p in _NON_LEAD_PHRASES):
        return True
    kw_words = [w for w in re.findall(r"[a-z0-9]+", keyword.lower()) if len(w) >= 3]
    specific = [w for w in kw_words if w not in _GENERIC_MATCH_WORDS]
    if not specific:
        return False
    return not any(w in s for w in specific)


def _parse_address_from_text(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if not line or _TIME_RE.search(line):
            continue
        if _LOCATION_RE.search(line) or ("," in line and len(line) < 120):
            return line[:300]
    loc = _LOCATION_RE.search(text)
    return loc.group(0) if loc else ""


def lead_record_is_complete(block_text: str, lead: dict[str, str]) -> bool:
    """Real captured lead: contact info or full buyer row (product + address + time)."""
    if lead.get("buyer_phone") or lead.get("buyer_email"):
        return True
    if lead.get("buyer_name") and lead.get("product_title"):
        return True
    has_time = bool(_TIME_RE.search(block_text))
    has_addr = bool(lead.get("buyer_address") or lead.get("buyer_location"))
    has_product = bool(lead.get("product_title")) and len(lead.get("product_title", "")) > 8
    return has_time and has_addr and has_product


async def _wait_for_lead_feed(page: Page, timeout_ms: int = 25_000) -> bool:
    """Wait until recent-leads feed shows at least one time marker."""
    try:
        await page.wait_for_function(
            """() => {
              const t = document.body.innerText || '';
              return /\\d+\\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days)\\s*ago/i.test(t);
            }""",
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


_TIME_LINE_RE = re.compile(
    r"^\d+\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days)\s*ago$",
    re.IGNORECASE,
)


def _blocks_from_body_text(body: str, max_blocks: int = 40) -> list[BuyerLeadBlock]:
    """Split full page text into lead chunks when DOM selectors miss cards."""
    if not body or len(body) < 50:
        return []
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    blocks: list[BuyerLeadBlock] = []
    i = 0
    while i < len(lines):
        if not _TIME_LINE_RE.match(lines[i]):
            i += 1
            continue
        start = max(0, i - 3)
        while start < i and (
            _TIME_LINE_RE.match(lines[start])
            or len(lines[start]) < 3
            or lines[start].lower() in ("recent", "buy leads", "all")
        ):
            start += 1
        end = i + 1
        while end < len(lines) and not _TIME_LINE_RE.match(lines[end]) and end - i < 14:
            end += 1
        text = "\n".join(lines[start:end])
        if (
            len(text) >= 30
            and _TIME_RE.search(text)
            and is_seller_incoming_buy_lead(text)
        ):
            blocks.append(
                BuyerLeadBlock(text=text, row_index=len(blocks), selector="body-split")
            )
        i = end if end > i + 1 else i + 1
        if len(blocks) >= max_blocks:
            break
    return blocks


async def collect_buyer_lead_blocks(page: Page, max_blocks: int = 40) -> list[BuyerLeadBlock]:
    await scroll_lead_list(page)
    await _wait_for_lead_feed(page)
    await scroll_lead_list(page)

    script = """
    (selectors) => {
      const timeRe = /\\b\\d+\\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days)\\s*ago\\b/i;
      const out = [];
      const seen = new Set();
      const push = (text, selector, rowIndex) => {
        const t = (text || '').replace(/\\s+/g, ' ').trim();
        if (t.length < 25 || t.length > 2500) return;
        const key = t.slice(0, 140);
        if (seen.has(key)) return;
        seen.add(key);
        out.push({ text: t, row_index: rowIndex, selector: selector || 'heuristic' });
      };
      const roots = [
        '#leadList', '.byr-inqry-list', '.bltxn-list', '[class*="bltxn"]',
        '[class*="inqry-list"]', 'main', 'body'
      ];
      const scopes = [];
      for (const r of roots) {
        const root = document.querySelector(r);
        if (root) scopes.push(root);
      }
      if (!scopes.length) scopes.push(document.body);
      for (const scope of scopes) {
        for (const sel of selectors) {
          const nodes = scope.querySelectorAll(sel);
          nodes.forEach((el, idx) => {
            const raw = (el.innerText || el.textContent || '').trim();
            if (!timeRe.test(raw)) return;
            push(raw, sel, idx);
          });
        }
      }
      const cardSel = 'div, li, article, section, a, [class*="lead"], [class*="inqry"], [class*="bltxn"]';
      document.querySelectorAll(cardSel).forEach((el, idx) => {
        const raw = (el.innerText || '').trim();
        if (!timeRe.test(raw)) return;
        const lines = raw.split('\\n').map(l => l.trim()).filter(Boolean);
        if (lines.length < 2 || lines.length > 16) return;
        if (raw.length < 30 || raw.length > 1400) return;
        push(raw, 'card-heuristic', idx);
      });
      return out;
    }
    """
    raw: list = []
    try:
        raw = await page.evaluate(script, INQUIRY_ROW_SELECTORS)
    except Exception:
        raw = []

    blocks: list[BuyerLeadBlock] = []
    for item in raw or []:
        text = (item.get("text") or "").strip()
        if not is_seller_incoming_buy_lead(text):
            continue
        blocks.append(
            BuyerLeadBlock(
                text=text,
                row_index=int(item.get("row_index", 0)),
                selector=item.get("selector") or INQUIRY_ROW_SELECTORS[0],
            )
        )
        if len(blocks) >= max_blocks:
            break

    if not blocks:
        try:
            body = await page.evaluate("() => document.body.innerText || ''")
        except Exception:
            body = ""
        blocks = _blocks_from_body_text(body, max_blocks)

    return blocks


def _lead_title_for_click(block_text: str) -> str:
    for line in block_text.splitlines():
        line = line.strip()
        if not line or _TIME_RE.search(line):
            continue
        lower = line.lower()
        if lower in ("sold out!", "i am interested", "business use"):
            continue
        if len(line) >= 8 and re.search(r"[a-zA-Z]{3,}", line):
            return line[:120]
    # Feed preview is often one line: "Product City, State 2 hrs ago Category > ..."
    one = " ".join(block_text.split())
    if not one or len(one) < 20:
        return ""
    m = _TIME_RE.search(one)
    if m:
        head = one[: m.start()].strip(" ,-|")
        if len(head) >= 8:
            loc = _CITY_STATE_RE.search(head)
            if loc:
                head = head[: loc.start()].strip(" ,-|")
            if len(head) >= 8 and re.search(r"[a-zA-Z]{3,}", head):
                return head[:120]
    cat = re.search(r">\s*([^>]+?)(?:\s+Power\s*:|\s+Probable|\s*$)", one, re.I)
    if cat and len(cat.group(1).strip()) >= 8:
        return cat.group(1).strip()[:120]
    return ""


async def click_buyer_lead_block(page: Page, block: BuyerLeadBlock) -> bool:
    title = _lead_title_for_click(block.text)
    if title:
        try:
            clicked = await page.evaluate(
                """(title) => {
                  const t = title.toLowerCase().slice(0, 80);
                  const nodes = [...document.querySelectorAll('div, li, article, a, tr, section')];
                  for (const el of nodes) {
                    const raw = (el.innerText || '').trim();
                    if (raw.length < 15 || raw.length > 1200) continue;
                    if (!raw.toLowerCase().includes(t)) continue;
                    if (!/\\d+\\s*(?:min|mins|hr|hrs|hour|hours|day|days)\\s*ago/i.test(raw)) continue;
                    el.click();
                    return true;
                }
                  return false;
                }""",
                title,
            )
            if clicked:
                await page.wait_for_timeout(3000)
                return True
        except Exception:
            pass
    if block.selector in ("body-split", "card-heuristic", "heuristic") and title:
        try:
            await page.get_by_text(title, exact=False).first.click(timeout=8000)
            await page.wait_for_timeout(3000)
            return True
        except Exception:
            pass
    try:
        loc = page.locator(block.selector)
        count = await loc.count()
        if count <= block.row_index:
            await loc.first.click(timeout=8000)
        else:
            await loc.nth(block.row_index).click(timeout=8000)
        await page.wait_for_timeout(3000)
        return True
    except Exception:
        if title:
            try:
                await page.get_by_text(title, exact=False).first.click(timeout=8000)
                await page.wait_for_timeout(3000)
                return True
            except Exception:
                return False
        return False


async def extract_buyer_details(page: Page, block_text: str = "") -> dict[str, str]:
    """Read open inquiry detail panel; regex fallback on visible text."""
    lead: dict[str, str] = {}
    if block_text:
        title = _lead_title_for_click(block_text)
        if title:
            lead["product_title"] = title[:200]
        lead["buyer_address"] = _parse_address_from_text(block_text)
        loc = _LOCATION_RE.search(block_text)
        if loc:
            lead["buyer_location"] = loc.group(0)
        if not lead.get("buyer_address"):
            lead["buyer_address"] = lead.get("buyer_location", "")

    panel_text = ""
    for sel in (
        ".inqry-detail-panel",
        ".inquiry-detail",
        ".byr-detail",
        ".msg-detail-panel",
        "[class*='detail']",
        "main",
    ):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                panel_text = await loc.inner_text(timeout=3000)
                if len(panel_text) > 80:
                    break
        except Exception:
            continue
    if len(panel_text) < 80:
        try:
            panel_text = await page.evaluate("() => document.body.innerText || ''")
        except Exception:
            panel_text = ""

    combined = f"{block_text}\n{panel_text}"
    phones = _PHONE_RE.findall(combined)
    if phones:
        lead["buyer_phone"] = phones[0].replace(" ", "").replace("-", "")
    emails = _EMAIL_RE.findall(combined)
    if emails:
        lead["buyer_email"] = emails[0]

    for sel, field in (
        (".buyer-name, .byr-name, .contact-name, [class*='buyer'] [class*='name']", "buyer_name"),
        (".inqDesc, .inquiry-message, .msg-content, [class*='message']", "message"),
    ):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                val = (await loc.inner_text(timeout=2000)).strip()
                if val and len(val) < 500:
                    lead[field] = val
        except Exception:
            continue

    if not lead.get("message") and panel_text:
        for line in panel_text.splitlines():
            line = line.strip()
            if len(line) > 25 and "interested" not in line.lower():
                lead["message"] = line[:500]
                break

    if not lead.get("buyer_location"):
        loc = _LOCATION_RE.search(combined)
        if loc:
            lead["buyer_location"] = loc.group(0)
    if not lead.get("buyer_address"):
        lead["buyer_address"] = _parse_address_from_text(combined) or lead.get("buyer_location", "")

    return lead

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
    r"maharashtra|rajasthan)\b",
    re.IGNORECASE,
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
    t = (text or "").strip()
    if len(t) < 30 or len(t) > 3000:
        return False
    lower = t.lower()
    if any(p in lower for p in _NON_LEAD_PHRASES):
        return False
    if _TIME_RE.search(t):
        return True
    if any(h in lower for h in _BUYER_ROW_HINTS):
        return True
    if _LOCATION_RE.search(t) and len(t) > 50:
        return True
    return False


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


def lead_record_is_complete(block_text: str, lead: dict[str, str]) -> bool:
    """Need buyer contact OR strong row text (product + place + time)."""
    if lead.get("buyer_phone") or lead.get("buyer_email"):
        return True
    if lead.get("buyer_name") and (lead.get("message") or lead.get("product_title")):
        return True
    t = block_text.lower()
    has_time = bool(_TIME_RE.search(block_text))
    has_loc = bool(_LOCATION_RE.search(block_text))
    has_interest = "interested" in t or "requirement" in t
    has_product = len(t) > 40 and not any(p in t for p in _NON_LEAD_PHRASES)
    return has_product and has_time and (has_loc or has_interest)


async def collect_buyer_lead_blocks(page: Page) -> list[BuyerLeadBlock]:
    await scroll_lead_list(page)
    script = """
    (selectors) => {
      const out = [];
      const seen = new Set();
      for (const sel of selectors) {
        const nodes = document.querySelectorAll(sel);
        nodes.forEach((el, idx) => {
          const text = (el.innerText || '').trim().replace(/\\s+/g, ' ');
          const key = text.slice(0, 120);
          if (text.length < 30 || seen.has(key)) return;
          seen.add(key);
          out.push({ text, row_index: idx, selector: sel });
        });
        if (out.length >= 40) break;
      }
      return out;
    }
    """
    try:
        raw = await page.evaluate(script, INQUIRY_ROW_SELECTORS)
    except Exception:
        return []
    blocks: list[BuyerLeadBlock] = []
    for item in raw or []:
        text = (item.get("text") or "").strip()
        if not is_buyer_inquiry_block(text):
            continue
        blocks.append(
            BuyerLeadBlock(
                text=text,
                row_index=int(item.get("row_index", 0)),
                selector=item.get("selector") or INQUIRY_ROW_SELECTORS[0],
            )
        )
    return blocks


async def click_buyer_lead_block(page: Page, block: BuyerLeadBlock) -> bool:
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
        return False


async def extract_buyer_details(page: Page, block_text: str = "") -> dict[str, str]:
    """Read open inquiry detail panel; regex fallback on visible text."""
    lead: dict[str, str] = {}
    if block_text:
        lines = [ln.strip() for ln in block_text.splitlines() if ln.strip()]
        if lines:
            lead["product_title"] = lines[0][:200]
        loc = _LOCATION_RE.search(block_text)
        if loc:
            lead["buyer_location"] = loc.group(0)

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

    return lead

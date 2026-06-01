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
    r"(?:\bjust\s+now\b|\b\d+\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days)\s*ago\b)",
    re.IGNORECASE,
)
# Known IndiaMART header/support numbers scraped from seller nav (not buyers).
_KNOWN_NAV_PHONES = frozenset({"9716054356", "9696969696", "18002008300"})
_NAV_NAME_MARKERS = frozenset(
    {
        "tools",
        "settings",
        "tally",
        "dashboard",
        "profile",
        "buy leads",
        "lead manager",
        "photos & docs",
        "invoices",
        "buyer tools",
        "sign in",
        "logout",
        "help",
    }
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


def lead_fingerprint(block_text: str, lead: dict[str, str] | None = None) -> str:
    """Stable key for dedup — phone/email best; else product + city (ignores 'X hrs ago')."""
    lead = lead or {}
    digits = re.sub(r"\D", "", lead.get("buyer_phone") or "")
    if len(digits) >= 10:
        return f"ph:{digits[-10:]}"
    email = (lead.get("buyer_email") or "").strip().lower()
    if email:
        return f"em:{email}"
    one = _TIME_RE.sub("", " ".join(block_text.split())).lower()
    loc = _CITY_STATE_RE.search(block_text) or _LOCATION_RE.search(block_text)
    city = (loc.group(0) if loc else "").lower().strip()
    cat = re.search(r">\s*([^>]+?)(?:\s+power\s*:|\s+probable)", one, re.I)
    product = cat.group(1).strip().lower()[:80] if cat else ""
    if not product:
        product = _lead_title_for_click(block_text).lower()[:80]
    product = re.sub(r"\s+", " ", product).strip()
    return f"pk:{product}|{city}"


def sanitize_buyer_name(name: str) -> str:
    """Drop sidebar/nav lines accidentally scraped as buyer name."""
    if not name:
        return ""
    kept: list[str] = []
    for line in name.splitlines():
        line = line.strip()
        if not line or len(line) > 80:
            continue
        low = line.lower()
        if any(m in low for m in _NAV_NAME_MARKERS):
            continue
        if low in ("business use", "probable requirement type", "sold out!"):
            continue
        kept.append(line)
    return " ".join(kept)[:120].strip()


def normalize_phone_digits(phone: str) -> str:
    d = re.sub(r"\D", "", phone or "")
    if len(d) >= 10:
        return d[-10:]
    return ""


def is_plausible_buyer_phone(
    phone: str, block_text: str = "", panel_text: str = ""
) -> bool:
    """Reject seller nav / support numbers that appear on every page."""
    d = normalize_phone_digits(phone)
    if len(d) < 10:
        return False
    if d in _KNOWN_NAV_PHONES:
        return False
    panel = panel_text or ""
    block = block_text or ""
    panel_digits = re.sub(r"\D", "", panel)
    block_digits = re.sub(r"\D", "", block)
    if d in panel_digits and len(panel) > 40:
        pl = panel.lower()
        if any(
            x in pl
            for x in (
                "buyer",
                "contact",
                "mobile",
                "phone",
                "member",
                "view number",
                "call buyer",
            )
        ):
            return True
    if d in block_digits and _TIME_RE.search(block):
        bl = block.lower()
        if any(
            x in bl
            for x in (
                "interested",
                "requirement",
                "sold out",
                "business use",
                "category",
                "laser",
                "machine",
            )
        ):
            return True
    return False


def sanitize_lead_contacts(
    lead: dict[str, str], block_text: str = "", panel_text: str = ""
) -> dict[str, str]:
    """Clean name/phone fields before dedup and CSV export."""
    out = dict(lead)
    if out.get("buyer_name"):
        out["buyer_name"] = sanitize_buyer_name(str(out["buyer_name"]))
    phone = normalize_phone_digits(str(out.get("buyer_phone") or ""))
    if phone and is_plausible_buyer_phone(phone, block_text, panel_text):
        out["buyer_phone"] = phone
    else:
        out.pop("buyer_phone", None)
    return out


def lead_has_buyer_contact(lead: dict[str, str]) -> bool:
    """Phone (or email) after opening lead / clicking reveal — required for actionable leads."""
    phone = normalize_phone_digits(lead.get("buyer_phone") or "")
    if phone and len(phone) >= 10:
        return True
    return bool((lead.get("buyer_email") or "").strip())


def lead_record_is_complete(block_text: str, lead: dict[str, str]) -> bool:
    """Real captured lead: contact info or full buyer row (product + address + time)."""
    if lead_has_buyer_contact(lead):
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
              return /just\\s+now|\\d+\\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days)\\s*ago/i.test(t);
            }""",
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


_TIME_LINE_RE = re.compile(
    r"^(?:just\s+now|\d+\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days)\s*ago)$",
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
        while end < len(lines) and not _TIME_LINE_RE.match(lines[end]) and end - i < 22:
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
      const timeRe = /(?:\\bjust\\s+now\\b|\\b\\d+\\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days)\\s*ago\\b)/i;
      const out = [];
      const seen = new Set();
      const push = (text, selector, rowIndex) => {
        const t = (text || '').trim().replace(/\\n{3,}/g, '\\n');
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


_INTEREST_BUTTON_LABELS = (
    "I am Interested",
    "I'm Interested",
    "I Am Interested",
)

_CONTACT_REVEAL_LABELS = (
    "View Contact",
    "View Mobile Number",
    "View Mobile",
    "Show Mobile Number",
    "Show Number",
    "Contact Buyer Now",
    "Contact Buyer",
    "View Number",
    "Get Contact Details",
    "Get Contact",
    "Call Buyer",
    "View Buyer Details",
    "Contact Now",
    "View Phone",
)


async def reveal_indiamart_buyer_contact(page: Page) -> bool:
    """Click any detail-panel control that likely reveals buyer phone/name."""
    clicked_any = False
    for label in _INTEREST_BUTTON_LABELS:
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=re.compile(re.escape(label), re.I))
                n = await loc.count()
                for i in range(min(n, 2)):
                    try:
                        el = loc.nth(i)
                        await el.scroll_into_view_if_needed(timeout=3000)
                        await el.click(timeout=5000)
                        await page.wait_for_timeout(2200)
                        clicked_any = True
                    except Exception:
                        continue
            except Exception:
                pass
    for label in _CONTACT_REVEAL_LABELS:
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=re.compile(re.escape(label), re.I))
                n = await loc.count()
                for i in range(min(n, 2)):
                    try:
                        el = loc.nth(i)
                        await el.scroll_into_view_if_needed(timeout=3000)
                        await el.click(timeout=4000)
                        await page.wait_for_timeout(1800)
                        clicked_any = True
                    except Exception:
                        continue
            except Exception:
                pass
    try:
        broad = page.locator("button, a, [role='button']").filter(
            has_text=re.compile(
                r"contact|mobile|phone|number|call|whatsapp|buyer|detail",
                re.I,
            )
        )
        n = await broad.count()
        for i in range(min(n, 8)):
            try:
                el = broad.nth(i)
                txt = (await el.inner_text(timeout=1500) or "").strip().lower()
                if not txt or len(txt) > 55:
                    continue
                if re.search(
                    r"interested|sold out|share|close|back|cancel|search|filter|login|sign in",
                    txt,
                ):
                    continue
                await el.scroll_into_view_if_needed(timeout=2000)
                await el.click(timeout=4000)
                await page.wait_for_timeout(1500)
                clicked_any = True
            except Exception:
                continue
    except Exception:
        pass
    try:
        count = await page.evaluate(
            """() => {
              const skip = /interested|sold out|share|close|back|cancel|submit|search|filter|login|sign in|recent/i;
              const want = /contact|mobile|phone|number|call|whatsapp|buyer|detail|view/i;
              const roots = [
                document.querySelector('[class*="detail"]'),
                document.querySelector('[class*="Detail"]'),
                document.querySelector('main'),
                document.body,
              ].filter(Boolean);
              let clicked = 0;
              for (const root of roots) {
                for (const el of root.querySelectorAll('button, a, [role="button"], span, div')) {
                  const t = (el.innerText || el.textContent || '').trim();
                  if (t.length < 3 || t.length > 56 || skip.test(t)) continue;
                  if (!want.test(t)) continue;
                  const r = el.getBoundingClientRect();
                  if (r.width < 2 || r.height < 2) continue;
                  try {
                    el.scrollIntoView({ block: 'center' });
                    el.click();
                    clicked++;
                  } catch (e) {}
                  if (clicked >= 6) return clicked;
                }
              }
              return clicked;
            }"""
        )
        if count and int(count) > 0:
            clicked_any = True
            await page.wait_for_timeout(2500)
    except Exception:
        pass
    return clicked_any


async def _scrape_contact_from_dom(page: Page) -> dict[str, str]:
    """Pull phone/name from tel: links, inputs, and visible detail text."""
    out: dict[str, str] = {}
    try:
        data = await page.evaluate(
            """() => {
              const phones = [];
              const addPhone = (raw) => {
                const d = (raw || '').replace(/\\D/g, '');
                if (d.length >= 10) phones.push(d.slice(-10));
              };
              document.querySelectorAll('a[href^="tel:"]').forEach(a => addPhone(a.href));
              document.querySelectorAll('input, textarea').forEach(inp => {
                const v = (inp.value || '').trim();
                if (/^\\+?\\d[\\d\\s-]{8,}$/.test(v)) addPhone(v);
              });
              const body = document.body.innerText || '';
              const nameRe = /(?:buyer\\s*name|contact\\s*person|name)\\s*[:\\-]\\s*([A-Za-z][A-Za-z\\s.]{2,60})/i;
              const nm = body.match(nameRe);
              return { phones: [...new Set(phones)], name: nm ? nm[1].trim() : '' };
            }"""
        )
        if data.get("phones"):
            out["buyer_phone"] = str(data["phones"][0])
        if data.get("name"):
            out["buyer_name"] = str(data["name"])[:120]
    except Exception:
        pass
    return out


async def click_buyer_lead_block(page: Page, block: BuyerLeadBlock) -> bool:
    title = _lead_title_for_click(block.text)
    if title:
        try:
            clicked = await page.evaluate(
                """(title) => {
                  const t = title.toLowerCase().slice(0, 80);
                  const timeRe = /just\\s+now|\\d+\\s*(?:min|mins|hr|hrs|hour|hours|day|days)\\s*ago/i;
                  const nodes = [...document.querySelectorAll('div, li, article, a, tr, section')];
                  let best = null;
                  let bestArea = Infinity;
                  for (const el of nodes) {
                    const raw = (el.innerText || '').trim();
                    if (raw.length < 15 || raw.length > 900) continue;
                    if (!raw.toLowerCase().includes(t)) continue;
                    if (!timeRe.test(raw)) continue;
                    const r = el.getBoundingClientRect();
                    const area = r.width * r.height;
                    if (area > 0 && area < bestArea) {
                      bestArea = area;
                      best = el;
                    }
                  }
                  if (best) {
                    best.scrollIntoView({ block: 'center' });
                    best.click();
                    return true;
                  }
                  return false;
                }""",
                title,
            )
            if clicked:
                await page.wait_for_timeout(3500)
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


async def _read_detail_panel_text(page: Page) -> str:
    panel_text = ""
    for sel in (
        ".inqry-detail-panel",
        ".inquiry-detail",
        ".byr-detail",
        ".msg-detail-panel",
        "[class*='detail-panel']",
        "[class*='Detail']",
        "[class*='detail']",
        "main",
    ):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                panel_text = await loc.inner_text(timeout=4000)
                if len(panel_text) > 80:
                    return panel_text
        except Exception:
            continue
    try:
        return await page.evaluate("() => document.body.innerText || ''")
    except Exception:
        return panel_text


def _parse_name_from_panel(text: str) -> str:
    for pat in (
        r"(?:buyer\s*name|contact\s*person|name)\s*[:\-]\s*([A-Za-z][A-Za-z\s.]{2,60})",
        r"(?:member\s*since|buyer)\s*[:\-]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})",
    ):
        m = re.search(pat, text, re.I)
        if m:
            name = m.group(1).strip()
            if name.lower() not in ("business use", "probable requirement"):
                return name[:120]
    return ""


def _apply_panel_text_to_lead(lead: dict[str, str], panel_text: str, block_text: str) -> None:
    combined = f"{block_text}\n{panel_text}"
    phones = _PHONE_RE.findall(combined)
    if phones:
        lead["buyer_phone"] = phones[0].replace(" ", "").replace("-", "")
    emails = _EMAIL_RE.findall(combined)
    if emails:
        lead["buyer_email"] = emails[0]

    if not lead.get("buyer_name"):
        lead["buyer_name"] = _parse_name_from_panel(panel_text)


async def extract_buyer_details(
    page: Page, block_text: str = "", *, try_reveal_contact: bool = True
) -> dict[str, str]:
    """Open inquiry detail panel, click contact reveal, extract name/phone."""
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

    panel_text = await _read_detail_panel_text(page)
    _apply_panel_text_to_lead(lead, panel_text, block_text)

    for sel, field in (
        (".buyer-name, .byr-name, .contact-name, [class*='buyer'] [class*='name']", "buyer_name"),
        (
            ".buyer-phone, .byr-phone, .contact-phone, [class*='phone'], .phone-no",
            "buyer_phone",
        ),
        (".inqDesc, .inquiry-message, .msg-content, [class*='message']", "message"),
    ):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                val = (await loc.inner_text(timeout=2000)).strip()
                if val and len(val) < 500:
                    if field == "buyer_phone":
                        digits = re.sub(r"\D", "", val)
                        if len(digits) >= 10:
                            lead[field] = digits[-10:] if len(digits) > 10 else digits
                    else:
                        lead[field] = val
        except Exception:
            continue

    dom_contact = await _scrape_contact_from_dom(page)
    if dom_contact.get("buyer_phone") and not lead.get("buyer_phone"):
        lead["buyer_phone"] = dom_contact["buyer_phone"]
    if dom_contact.get("buyer_name") and not lead.get("buyer_name"):
        lead["buyer_name"] = dom_contact["buyer_name"]

    if try_reveal_contact and not lead_has_buyer_contact(lead):
        for _ in range(3):
            if await reveal_indiamart_buyer_contact(page):
                panel_text = await _read_detail_panel_text(page)
                _apply_panel_text_to_lead(lead, panel_text, block_text)
                dom_contact = await _scrape_contact_from_dom(page)
                if dom_contact.get("buyer_phone"):
                    lead["buyer_phone"] = dom_contact["buyer_phone"]
                if dom_contact.get("buyer_name") and not lead.get("buyer_name"):
                    lead["buyer_name"] = dom_contact["buyer_name"]
                for sel, field in (
                    (".buyer-name, .byr-name, .contact-name", "buyer_name"),
                    (".buyer-phone, .byr-phone, .contact-phone, .phone-no", "buyer_phone"),
                ):
                    try:
                        loc = page.locator(sel).first
                        if await loc.count() > 0:
                            val = (await loc.inner_text(timeout=2000)).strip()
                            if field == "buyer_phone":
                                digits = re.sub(r"\D", "", val)
                                if len(digits) >= 10:
                                    lead[field] = digits[-10:] if len(digits) > 10 else digits
                            elif val and len(val) < 120:
                                lead[field] = val
                    except Exception:
                        continue
            if lead_has_buyer_contact(lead):
                break

    if not lead.get("message") and panel_text:
        for line in panel_text.splitlines():
            line = line.strip()
            if len(line) > 25 and "interested" not in line.lower():
                lead["message"] = line[:500]
                break

    combined = f"{block_text}\n{panel_text}"
    if not lead.get("buyer_location"):
        loc = _LOCATION_RE.search(combined)
        if loc:
            lead["buyer_location"] = loc.group(0)
    if not lead.get("buyer_address"):
        lead["buyer_address"] = _parse_address_from_text(combined) or lead.get("buyer_location", "")

    return sanitize_lead_contacts(lead, block_text, panel_text)

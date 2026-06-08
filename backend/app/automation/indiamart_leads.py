from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from playwright.async_api import Page

logger = logging.getLogger(__name__)

from app.automation.indiamart_page import (
    INQUIRY_ROW_SELECTORS,
    scroll_lead_list,
)

# Hard navigation / catalog text that should never count as a buyer lead.
_HARD_NON_LEAD_PHRASES = (
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
    "member since",
)

# Common UI labels seen inside real lead cards (do NOT hard-reject on these).
_SOFT_LEAD_UI_PHRASES = (
    "buyer viewed",
    "you viewed",
    "you sell",
    "requirements",
    "calls",
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
# Internal address recognizer only. This is not a user keyword/location filter;
# it recognizes "City, State" style text without hardcoding any city/state names.
_CITY_STATE_RE = re.compile(
    r"\b[A-Za-z][A-Za-z\s.'-]{1,60},\s*[A-Za-z][A-Za-z\s.'-]{1,60}\b",
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

_PRODUCT_LINE_RE = re.compile(
    r"\b(?:laser|machine|machines|cleaning|cleaner|welding|welder|marking|marker|"
    r"cutting|cutter|engraving|engraver|rust|removal|equipment|plant|system|"
    r"compressor|motor|pump|tool|tools|industrial|metal|steel)\b",
    re.IGNORECASE,
)

_LOW_VALUE_LEAD_LINES = frozenset(
    {
        ",",
        ">",
        "recent",
        "buy leads",
        "all",
        "sold out!",
        "i am interested",
        "business use",
        "probable requirement type",
        "requirement type",
        "category",
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


def _is_location_line(line: str) -> bool:
    line = line.strip(" ,")
    if not line:
        return False
    return bool(_CITY_STATE_RE.fullmatch(line))


def _clean_address_line(line: str) -> str:
    line = _TIME_RE.sub("", line or "")
    line = re.sub(r"\b(?:just\s+now)\b", "", line, flags=re.IGNORECASE)
    return line.strip(" ,-|·•")


def _looks_like_product_line(line: str) -> bool:
    line = line.strip()
    if not line or _TIME_RE.fullmatch(line):
        return False
    lower = line.lower().strip(" :")
    if lower in _LOW_VALUE_LEAD_LINES or _is_location_line(line):
        return False
    if len(line) < 8 or not re.search(r"[a-zA-Z]{4,}", line):
        return False
    if _PRODUCT_LINE_RE.search(line):
        return True
    # Keep support for non-laser categories, but only when it is clearly not a city/state/UI line.
    return len(line.split()) >= 2 and not any(p in lower for p in _HARD_NON_LEAD_PHRASES)


def _is_location_time_only_block(text: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines or not any(_TIME_RE.search(ln) for ln in lines):
        return False
    meaningful = [
        ln
        for ln in lines
        if not _TIME_RE.fullmatch(ln)
        and ln.strip(" ,")
        and ln.lower().strip(" :") not in _LOW_VALUE_LEAD_LINES
    ]
    if not meaningful:
        return False
    joined = ", ".join(ln.strip(" ,") for ln in meaningful)
    if len(meaningful) <= 3 and _CITY_STATE_RE.fullmatch(joined):
        return True
    return all(_is_location_line(ln) for ln in meaningful)


def _lead_candidate_score(text: str) -> int:
    """Rank DOM snippets so full lead cards beat tiny location/time fragments."""
    t = (text or "").strip()
    if not t:
        return -1000
    lower = t.lower()
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    score = min(len(t), 1800) // 20
    score += min(len(lines), 28)
    if _TIME_RE.search(t):
        score += 80
    if _PRODUCT_LINE_RE.search(t):
        score += 80
    if ">" in t:
        score += 25
    if any(
        p in lower
        for p in (
            "i am interested",
            "requirement",
            "sold out",
            "business use",
            "probable requirement",
            "category",
        )
    ):
        score += 45
    if _is_location_time_only_block(t):
        score -= 180
    score -= 35 * sum(1 for p in _HARD_NON_LEAD_PHRASES if p in lower)
    return score


def is_seller_incoming_buy_lead(text: str) -> bool:
    """
    Incoming buyer on this seller's Recent Buy Leads feed — not nav, not buyer profile sidebar.
    """
    t = (text or "").strip()
    if len(t) < 35 or len(t) > 3000:
        return False
    lower = t.lower()
    has_time = bool(_TIME_RE.search(t))
    hard_hits = sum(1 for p in _HARD_NON_LEAD_PHRASES if p in lower)
    # Navigation chunks often include many hard nav markers and no lead time marker.
    if hard_hits >= 2 and not has_time:
        return False
    if not has_time:
        return False
    if _is_location_time_only_block(t):
        return False
    has_product_line = any(_looks_like_product_line(line) for line in t.splitlines())
    has_interest = (
        "interested" in lower
        or "requirement" in lower
        or "category" in lower
        or "sold out" in lower
        or "business use" in lower
        or any(p in lower for p in _SOFT_LEAD_UI_PHRASES)
    )
    has_loc = bool(_CITY_STATE_RE.search(t))
    return has_product_line and (has_interest or has_loc)


def is_weak_match_context(snippet: str, keyword: str) -> bool:
    """Reject matches that only hit generic catalog/nav words."""
    s = (snippet or "").lower()
    if sum(1 for p in _HARD_NON_LEAD_PHRASES if p in s) >= 2 and not _TIME_RE.search(snippet or ""):
        return True
    kw_words = [w for w in re.findall(r"[a-z0-9]+", keyword.lower()) if len(w) >= 3]
    specific = [w for w in kw_words if w not in _GENERIC_MATCH_WORDS]
    if not specific:
        return False
    return not any(w in s for w in specific)


def _parse_address_from_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if line == "," and 0 < idx < len(lines) - 1:
            city = _clean_address_line(lines[idx - 1])
            state = _clean_address_line(lines[idx + 1])
            joined = f"{city}, {state}"
            if _CITY_STATE_RE.fullmatch(joined):
                return joined[:300]
    for idx, line in enumerate(lines):
        line = _clean_address_line(line)
        if not line:
            continue
        if idx + 1 < len(lines):
            joined = f"{line.strip(' ,')}, {_clean_address_line(lines[idx + 1])}"
            if _CITY_STATE_RE.fullmatch(joined):
                return joined[:300]
        loc = _CITY_STATE_RE.search(line)
        if loc:
            return loc.group(0)[:300]
    loc = _CITY_STATE_RE.search(_clean_address_line(text))
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
    loc = _CITY_STATE_RE.search(block_text)
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
    # Phone found in panel text (contact reveal popup) — accept it.
    # IndiaMART popup shows number directly; context words may not appear in scraped text.
    if d in panel_digits and len(panel) > 20:
        return True
    # Phone found in lead card text alongside a time marker — accept it.
    if d in block_digits and _TIME_RE.search(block):
        return True
    return False


def sanitize_lead_contacts(
    lead: dict[str, str], block_text: str = "", panel_text: str = ""
) -> dict[str, str]:
    """Clean name/phone fields before dedup and CSV export."""
    out = dict(lead)
    if out.get("buyer_name"):
        out["buyer_name"] = sanitize_buyer_name(str(out["buyer_name"]))
    
    phone_raw = str(out.get("buyer_phone") or "").strip()
    if phone_raw:
        # Check if it's an international number (starts with +)
        if phone_raw.startswith("+"):
            digits = re.sub(r"\D", "", phone_raw)
            if 8 <= len(digits) <= 15 and digits not in _KNOWN_NAV_PHONES:
                out["buyer_phone"] = phone_raw  # Keep the + format
            else:
                out.pop("buyer_phone", None)
        else:
            # Normalize to digits only
            phone = normalize_phone_digits(phone_raw)
            if phone in _KNOWN_NAV_PHONES:
                out.pop("buyer_phone", None)
            elif re.match(r"^[6-9]\d{9}$", phone):
                # Valid Indian mobile (10 digits, starts with 6-9)
                out["buyer_phone"] = phone
            elif re.match(r"^0[1-9]\d{9,11}$", phone):
                # Valid Indian landline (11-12 digits, starts with 0 + STD code)
                out["buyer_phone"] = phone
            elif len(phone) >= 8 and len(phone) <= 15:
                # Other valid phone (international without +, or other format)
                out["buyer_phone"] = phone
            else:
                out.pop("buyer_phone", None)
    return out


def lead_has_buyer_contact(lead: dict[str, str]) -> bool:
    """Phone (or email) after opening lead / clicking reveal — required for actionable leads."""
    phone_raw = (lead.get("buyer_phone") or "").strip()
    if phone_raw:
        # International number with + prefix
        if phone_raw.startswith("+"):
            digits = re.sub(r"\D", "", phone_raw)
            if len(digits) >= 8:
                return True
        else:
            # Indian mobile/landline or other
            phone = normalize_phone_digits(phone_raw)
            if len(phone) >= 8:
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


async def collect_buyer_lead_blocks(page: Page, max_blocks: int = 100) -> list[BuyerLeadBlock]:
    await _wait_for_lead_feed(page)
    await scroll_lead_list(page, aggressive=True)

    script = """
    async (config) => {
      const { selectors, maxBlocks } = config;
      const timeRe = /(?:\\bjust\\s+now\\b|\\b\\d+\\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days)\\s*ago\\b)/i;
      const out = [];
      const seen = new Set();
      const sleep = (ms) => new Promise(r => setTimeout(r, ms));
      const clean = (text) => (text || '').trim().replace(/\\n{3,}/g, '\\n');
      const push = (text, selector, rowIndex) => {
        const t = clean(text);
        if (t.length < 25 || t.length > 2500) return;
        const key = t.replace(/\\s+/g, ' ').slice(0, 650);
        if (seen.has(key)) return;
        seen.add(key);
        out.push({ text: t, row_index: rowIndex, selector: selector || 'heuristic' });
      };
      const textOf = (el) => clean(el && (el.innerText || el.textContent || ''));
      const pushElementContext = (el, selector, rowIndex, sampleLabel) => {
        if (!el) return;
        const base = textOf(el);
        if (!timeRe.test(base)) return;
        const label = sampleLabel ? `${sampleLabel}:${selector || 'time'}` : selector;
        push(base, label, rowIndex);

        let cur = el;
        for (let depth = 0; depth < 6 && cur && cur !== document.body; depth += 1) {
          cur = cur.parentElement;
          const txt = textOf(cur);
          if (timeRe.test(txt)) push(txt, `${label || 'time'}:parent-${depth + 1}`, rowIndex);
        }

        const card = el.closest('li, article, section, tr, a, div[class*="lead"], div[class*="inq"], div[class*="bltxn"], div');
        const cardTxt = textOf(card);
        if (timeRe.test(cardTxt)) push(cardTxt, `${label || 'time'}:closest-card`, rowIndex);

        const parent = el.parentElement;
        if (!parent) return;
        const siblings = Array.from(parent.children || []);
        const idx = siblings.indexOf(el);
        if (idx < 0) return;
        for (const radius of [1, 2, 3]) {
          const slice = siblings
            .slice(Math.max(0, idx - radius), Math.min(siblings.length, idx + radius + 1))
            .map(textOf)
            .filter(Boolean)
            .join('\\n');
          if (timeRe.test(slice)) push(slice, `${label || 'time'}:sibling-window-${radius}`, rowIndex);
        }
      };

      const sampleVisibleRows = (sampleLabel) => {
        const roots = [
          '#leadList', '.byr-inqry-list', '.bltxn-list', '[class*="bltxn"]',
          '[class*="inqry-list"]', '[class*="lead-list"]', '[class*="inquiry-list"]',
          '.msg-list', 'main', '[role="main"]', 'body'
        ];
        const scopes = [];
        for (const r of roots) {
          const root = document.querySelector(r);
          if (root && !scopes.includes(root)) scopes.push(root);
        }
        if (!scopes.length) scopes.push(document.body);
        for (const scope of scopes) {
          for (const sel of selectors) {
            const nodes = scope.querySelectorAll(sel);
            nodes.forEach((el, idx) => {
              pushElementContext(el, sel, idx, sampleLabel);
            });
          }
        }
        const cardSel = 'div, li, article, section, a, [class*="lead"], [class*="inqry"], [class*="bltxn"]';
        document.querySelectorAll(cardSel).forEach((el, idx) => {
          const raw = textOf(el);
          if (!timeRe.test(raw)) return;
          const lines = raw.split('\\n').map(l => l.trim()).filter(Boolean);
          if (lines.length < 2 || lines.length > 32) return;
          if (raw.length < 30 || raw.length > 2200) return;
          push(raw, `${sampleLabel}:card-heuristic`, idx);
        });
      };

      const scrollRootSelectors = [
        '#leadList', '.byr-inqry-list', '.bltxn-list', '[class*="bltxn"]',
        '[class*="inqry-list"]', '[class*="lead-list"]', '[class*="inquiry-list"]',
        '.msg-list', 'main', '[role="main"]'
      ];
      const scrollRoots = [];
      const addRoot = (el) => {
        if (!el || scrollRoots.includes(el)) return;
        const maxScroll = Math.max(0, el.scrollHeight - el.clientHeight);
        if (maxScroll > 80) scrollRoots.push(el);
      };
      for (const r of scrollRootSelectors) {
        const root = document.querySelector(r);
        addRoot(root);
      }
      const overflowNodes = [...document.querySelectorAll('div, main, section, aside, ul, table, tbody')];
      overflowNodes.forEach((el) => {
        const style = window.getComputedStyle(el);
        const overflow = `${style.overflowY} ${style.overflow}`;
        if (!/(auto|scroll)/i.test(overflow)) return;
        addRoot(el);
      });
      scrollRoots.sort((a, b) => {
        const aMax = Math.max(0, a.scrollHeight - a.clientHeight);
        const bMax = Math.max(0, b.scrollHeight - b.clientHeight);
        return bMax - aMax;
      });

      const pageRoot = document.scrollingElement || document.documentElement || document.body;
      if (!scrollRoots.includes(pageRoot)) scrollRoots.push(pageRoot);

      const clickLoadMore = async () => {
        const nodes = [...document.querySelectorAll('button, a, [role="button"]')];
        for (const el of nodes) {
          const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
          if (!/(load more|show more|view more|see more)/.test(txt)) continue;
          const r = el.getBoundingClientRect();
          if (r.width < 4 || r.height < 4) continue;
          try {
            el.click();
            await sleep(1200);
            return true;
          } catch (e) {}
        }
        return false;
      };

      scrollRoots.forEach(root => { try { root.scrollTop = 0; } catch (e) {} });
      window.scrollTo(0, 0);
      await sleep(500);

      let stagnant = 0;
      const maxSteps = 36;
      for (let step = 0; step < maxSteps && out.length < maxBlocks * 4; step += 1) {
        sampleVisibleRows(`scan-${step}`);
        if (step > 0 && step % 8 === 0) await clickLoadMore();

        let moved = false;
        for (const root of scrollRoots.slice(0, 6)) {
          try {
            const before = root.scrollTop || 0;
            const delta = Math.max(360, Math.floor((root.clientHeight || window.innerHeight) * 0.72));
            root.scrollTop = Math.min(root.scrollHeight, before + delta);
            if ((root.scrollTop || 0) > before + 4) moved = true;
          } catch (e) {}
        }
        const beforeWindow = window.scrollY || pageYOffset || 0;
        window.scrollBy(0, Math.max(420, Math.floor(window.innerHeight * 0.72)));
        if ((window.scrollY || pageYOffset || 0) > beforeWindow + 4) moved = true;

        await sleep(650);
        stagnant = moved ? 0 : stagnant + 1;
        if (stagnant >= 3) break;
      }

      sampleVisibleRows('scan-final');
      scrollRoots.forEach(root => { try { root.scrollTop = 0; } catch (e) {} });
      window.scrollTo(0, 0);
      return out;
    }
    """
    raw: list = []
    try:
        raw = await page.evaluate(
            script,
            {"selectors": INQUIRY_ROW_SELECTORS, "maxBlocks": max_blocks},
        )
    except Exception:
        raw = []

    sorted_raw = sorted(
        raw or [],
        key=lambda item: _lead_candidate_score(item.get("text") or ""),
        reverse=True,
    )
    blocks: list[BuyerLeadBlock] = []
    seen_texts: list[str] = []
    for item in sorted_raw:
        text = (item.get("text") or "").strip()
        if not is_seller_incoming_buy_lead(text):
            continue
        compact = re.sub(r"\s+", " ", text).strip().lower()
        if any(compact == prev or compact in prev for prev in seen_texts):
            continue
        seen_texts.append(compact)
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
    one = " ".join(block_text.split())
    cat = re.search(
        r">\s*([^>]+?)(?:\s+(?:working\s+area|laser\s+power|power|"
        r"probable(?:\s+requirement\s+type)?|price|quantity)\s*:"
        r"|\s+probable\s+requirement\s+type\b|\s*$)",
        one,
        re.I,
    )
    if cat and len(cat.group(1).strip()) >= 8:
        return cat.group(1).strip(" ,-|")[:120]

    lines = [line.strip() for line in block_text.splitlines() if line.strip()]
    after_time = False
    productish_after_time: list[str] = []
    productish_anywhere: list[str] = []
    for line in lines:
        if _TIME_RE.search(line):
            after_time = True
            continue
        lower = line.lower().strip(" :")
        if (
            lower in ("sold out!", "i am interested", "business use", "probable requirement type")
            or line in (",", ">")
            or _CITY_STATE_RE.fullmatch(line)
        ):
            continue
        if len(line) < 8 or not re.search(r"[a-zA-Z]{3,}", line):
            continue
        looks_product = bool(
            re.search(
                r"\b(?:laser|machine|cleaning|welding|marking|cutting|engraving|rust|removal|cleaner|equipment)\b",
                line,
                re.I,
            )
        )
        if looks_product:
            productish_anywhere.append(line)
            if after_time:
                productish_after_time.append(line)

    if productish_after_time:
        return productish_after_time[-1][:120]
    if productish_anywhere:
        return productish_anywhere[0][:120]

    # Feed preview is often one line: "Product City, State 2 hrs ago Category > ..."
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
    cat = re.search(
        r">\s*([^>]+?)(?:\s+Power\s*:|\s+Probable(?:\s+Requirement\s+Type)?\b|\s*$)",
        one,
        re.I,
    )
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

    # Strategy 1: CSS selectors + Playwright has-text (most reliable, fastest)
    contact_selectors = [
        # data-testid selectors
        "[data-testid='view-contact-btn']",
        "[data-testid='contact-button']",
        "[data-testid='view-number']",
        "[data-testid='show-mobile']",
        "[data-testid='reveal-contact']",
        # Playwright has-text: matches visible text content
        "button:has-text('View Mobile No.')",
        "button:has-text('View Contact Details')",
        "button:has-text('View Contact')",
        "button:has-text('View Number')",
        "button:has-text('Show Number')",
        "button:has-text('Contact Buyer')",
        "a:has-text('View Mobile No.')",
        "a:has-text('View Contact')",
        "a:has-text('View Number')",
        # class-based
        "button[class*='contact']",
        "button[class*='view-number']",
        "button[class*='show-mobile']",
        ".view-contact-btn",
        ".contact-reveal-btn",
        ".show-number-btn",
        "[class*='view-contact']",
        "[class*='show-contact']",
        "[class*='contact-details'] button",
    ]

    for sel in contact_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                await loc.scroll_into_view_if_needed(timeout=2000)
                await loc.click(timeout=4000)
                await page.wait_for_timeout(2500)
                clicked_any = True
                logger.info("Clicked contact reveal button", selector=sel)
                break
        except Exception:
            continue

    if not clicked_any:
        logger.info("No contact reveal button found with CSS selectors, trying text-based")

    if not clicked_any:
        # Strategy 2: Try explicit contact reveal labels before generic interest buttons.
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

    if not clicked_any:
        # Strategy 3: Some IndiaMART rows reveal contact only after the interest CTA.
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


async def _wait_for_contact_signal(page: Page, timeout_ms: int = 6000) -> bool:
    """Wait briefly for any visible contact reveal signal in DOM."""
    try:
        await page.wait_for_function(
            """() => {
              const body = (document.body.innerText || '');
              if (/(?:\\+91[\\s-]?)?[6-9]\\d{9}/.test(body)) return true;
              if (/[\\w.+-]+@[\\w.-]+\\.[a-z]{2,}/i.test(body)) return true;
              if (document.querySelector('a[href^="tel:"], a[href^="mailto:"]')) return true;
              return false;
            }""",
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


async def _scrape_contact_from_dom(page: Page) -> dict[str, str]:
    """Pull phone/email/name from DOM - handles IndiaMART contact popup layout."""
    out: dict[str, str] = {}
    try:
        data = await page.evaluate(
            r"""() => {
              const knownNav = new Set(['9716054356','9696969696','18002008300']);
              const phones = [];
              const emails = [];
              const addPhone = (raw) => {
                const d = (raw || '').replace(/\D/g, '');
                if (d.length >= 10 && !knownNav.has(d.slice(-10))) {
                  const p = d.slice(-10);
                  if (/^[6-9]/.test(p)) phones.push(p);
                }
              };
              const addEmail = (raw) => {
                const m = (raw || '').match(/[\w.+-]+@[\w.-]+\.[a-z]{2,}/i);
                if (m) emails.push(m[0].toLowerCase());
              };

              // 1. tel: and mailto: links (most reliable)
              document.querySelectorAll('a[href^="tel:"]').forEach(a => {
                addPhone(a.getAttribute('href').replace('tel:', ''));
              });
              document.querySelectorAll('a[href^="mailto:"]').forEach(a => {
                addEmail(a.getAttribute('href').replace('mailto:', '').split('?')[0]);
              });

              // 2. data attributes on any element
              document.querySelectorAll('[data-phone],[data-mobile],[data-contact],[data-tel]').forEach(el => {
                addPhone(el.getAttribute('data-phone') || el.getAttribute('data-mobile') ||
                         el.getAttribute('data-contact') || el.getAttribute('data-tel') || '');
              });
              document.querySelectorAll('[data-email],[data-mail]').forEach(el => {
                addEmail(el.getAttribute('data-email') || el.getAttribute('data-mail') || '');
              });

              // 3. Specific CSS selectors for contact panel
              const panelSels = [
                '[data-testid="buyer-phone"],[data-testid="contact-phone"]',
                '.buyer-phone,.contact-phone,.byr-phone,.mob-num,.phone-no',
                '[class*="phone"],[class*="mobile"],[class*="mob"]',
                '[data-testid="buyer-email"],[data-testid="contact-email"]',
                '.buyer-email,.contact-email,.byr-email',
                '[class*="email"]',
              ];
              panelSels.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                  const t = (el.textContent || el.innerText || '').trim();
                  addPhone(t); addEmail(t);
                });
              });

              // 4. inputs / textareas that contain phone/email
              document.querySelectorAll('input[type="tel"],input[name*="phone"],input[name*="mobile"]').forEach(inp => {
                addPhone(inp.value || '');
              });
              document.querySelectorAll('input[type="email"],input[name*="email"]').forEach(inp => {
                addEmail(inp.value || '');
              });

              // 5. Scan visible popup/modal text for phone+email patterns
              // IndiaMART contact popup is typically in a dialog, aside, or overlay div
              const popupSels = [
                '[role="dialog"]', '[class*="modal"]', '[class*="popup"]',
                '[class*="overlay"]', '[class*="drawer"]',
                '[class*="detail-panel"]', '[class*="byr-detail"]',
                '[class*="inqry-detail"]', '[class*="contact-detail"]',
                '[class*="buyer-info"]', 'aside',
              ];
              let panelText = '';
              for (const sel of popupSels) {
                const el = document.querySelector(sel);
                if (el) {
                  const t = (el.innerText || '').trim();
                  if (t.length > 20) { panelText = t; break; }
                }
              }
              if (!panelText) panelText = document.body.innerText || '';

              const anyPhoneRe = /(?:\+91[\s-]?)?[6-9]\d{9}/g;
              let m;
              while ((m = anyPhoneRe.exec(panelText)) !== null) addPhone(m[0]);
              const emailRe = /[\w.+-]+@[\w.-]+\.[a-z]{2,}/gi;
              while ((m = emailRe.exec(panelText)) !== null) addEmail(m[0]);

              // 6. Extract name: look for heading/bold text near top of popup
              let name = '';
              // Try data-testid selectors
              for (const sel of [
                '[data-testid="buyer-name"]','[data-testid="contact-name"]',
                '.buyer-name','.contact-name','.byr-name',
                '[class*="buyer-name"],[class*="contact-name"]',
              ]) {
                const el = document.querySelector(sel);
                if (el) {
                  const t = (el.textContent || el.innerText || '').trim();
                  if (t && t.length > 1 && t.length < 80) { name = t; break; }
                }
              }
              // Try first h1/h2/h3/h4/strong in popup
              if (!name && panelText) {
                const lines = panelText.split('\n').map(l => l.trim()).filter(Boolean);
                const skipWords = /email|mobile|phone|contact|verified|last seen|member|enterprise|pvt|ltd|dashboard|leads|settings|logout|help|\d/i;
                for (const line of lines.slice(0, 6)) {
                  if (skipWords.test(line)) continue;
                  if (line.length >= 2 && line.length <= 60 && /[A-Za-z]/.test(line)) {
                    name = line; break;
                  }
                }
              }

              return {
                phones: [...new Set(phones)],
                emails: [...new Set(emails)],
                name: name,
              };
            }"""
        )
        if data.get("phones"):
            out["buyer_phone"] = str(data["phones"][0])
        if data.get("emails"):
            out["buyer_email"] = str(data["emails"][0])
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
                await page.wait_for_timeout(1500)
                return True
        except Exception:
            pass
    if block.selector in ("body-split", "card-heuristic", "heuristic") and title:
        try:
            await page.get_by_text(title, exact=False).first.click(timeout=5000)
            await page.wait_for_timeout(1500)
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
        await page.wait_for_timeout(1500)
        return True
    except Exception:
        if title:
            try:
                await page.get_by_text(title, exact=False).first.click(timeout=5000)
                await page.wait_for_timeout(1500)
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
    """Extract buyer name from panel text using multiple patterns for new IndiaMART layout."""
    # New IndiaMART patterns (2024-2025)
    patterns = (
        # Common label patterns
        r"(?:buyer\s*name|contact\s*person|contact\s*name|customer\s*name)\s*[:\-]\s*([A-Za-z][A-Za-z\s.]{2,60})",
        # Name near phone/email patterns
        r"(?:mobile|phone)\s*[:\-]?\s*\+?\d[\d\s-]{8,}\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})",
        # Name at start of inquiry section
        r"(?:inquiry|message)\s*from\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})",
        # Member/Buyer pattern
        r"(?:member\s*since|buyer)\s*[:\-]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})",
        # Name followed by company/location
        r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*(?:,|from|at)\s*(?:[A-Z][a-z]+",
    )
    for pat in patterns:
        m = re.search(pat, text, re.I | re.MULTILINE)
        if m:
            name = m.group(1).strip()
            # Filter out common false positives
            name_lower = name.lower()
            if name_lower not in ("business use", "probable requirement", "member since",
                                   "buyer name", "contact person", "not provided"):
                # Clean up the name
                name = re.sub(r'\s+', ' ', name).strip()
                if len(name) >= 2:
                    return name[:120]
    return ""


def _extract_product_title_from_panel(text: str) -> str:
    """Extract full product title from detail panel text."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # Pattern 1: Look for "Product:" or "Product Title:" label
    for line in lines:
        m = re.search(r"(?:product|item|title)\s*[:\-]\s*(.+)", line, re.I)
        if m:
            title = m.group(1).strip()
            if len(title) >= 5:
                return title[:200]

    # Pattern 2: Look for "Category > Product" pattern
    for line in lines:
        m = re.search(r">\s*([^>]+?)(?:\s+Power\s*:|\s+Probable|\s*Price\s*:|\s*$)", line, re.I)
        if m:
            title = m.group(1).strip()
            if len(title) >= 5:
                return title[:200]

    # Pattern 3: First substantial line that's not a time marker or location
    for line in lines[:5]:  # Check first 5 lines
        if _TIME_RE.search(line):
            continue
        if _CITY_STATE_RE.search(line) and len(line) < 80:
            continue
        if len(line) >= 10 and re.search(r"[a-zA-Z]{4,}", line):
            # Skip common UI text
            skip_words = ["interested", "sold out", "business use", "requirement type",
                       "automation grade", "probable requirement", "view contact", "buy now"]
            if not any(w in line.lower() for w in skip_words):
                return line[:200]

    return ""


def _extract_name_from_panel_top(panel_text: str) -> str:
    """IndiaMART contact popup shows buyer name as first prominent line."""
    lines = [ln.strip() for ln in panel_text.splitlines() if ln.strip()]
    for line in lines[:8]:
        # Skip lines that are clearly labels, locations, UI text, or very short
        low = line.lower()
        if any(m in low for m in _NAV_NAME_MARKERS):
            continue
        if any(m in low for m in ("email", "mobile", "phone", "contact", "verified",
                                   "last seen", "member since", "enterprise", "pvt",
                                   "ltd")):
            continue
        if _TIME_RE.search(line):
            continue
        if _CITY_STATE_RE.search(line) and len(line) < 80:
            continue
        if _PHONE_RE.search(line) or _EMAIL_RE.search(line):
            continue
        # Must look like a person's name: 2-4 words, capitalised, no digits
        if len(line) < 2 or len(line) > 60 or re.search(r"\d", line):
            continue
        words = line.split()
        if 1 <= len(words) <= 5 and re.search(r"[A-Za-z]", line):
            return line[:80]
    return ""


def _apply_panel_text_to_lead(lead: dict[str, str], panel_text: str, block_text: str) -> None:
    combined = f"{block_text}\n{panel_text}"
    # Extract phones from combined text
    phones = _PHONE_RE.findall(combined)
    plausible_phones = [
        p.replace(" ", "").replace("-", "")
        for p in phones
        if is_plausible_buyer_phone(p, block_text, panel_text)
    ]
    if plausible_phones and not lead.get("buyer_phone"):
        lead["buyer_phone"] = plausible_phones[0]
    elif phones and not lead.get("buyer_phone"):
        # Fall back to first phone found if plausibility filter removed all
        d = normalize_phone_digits(phones[0])
        if d and d not in _KNOWN_NAV_PHONES:
            lead["buyer_phone"] = d
    # Extract email
    emails = _EMAIL_RE.findall(combined)
    if emails and not lead.get("buyer_email"):
        lead["buyer_email"] = emails[0]
    # Extract name — try popup-top heuristic first, then regex patterns
    if not lead.get("buyer_name"):
        name = _extract_name_from_panel_top(panel_text)
        if not name:
            name = _parse_name_from_panel(panel_text)
        lead["buyer_name"] = name


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
        loc = _CITY_STATE_RE.search(block_text)
        if loc:
            lead["buyer_location"] = loc.group(0)
        if not lead.get("buyer_address"):
            lead["buyer_address"] = lead.get("buyer_location", "")

    panel_text = await _read_detail_panel_text(page)
    _apply_panel_text_to_lead(lead, panel_text, block_text)

    # Extract better product title from panel text if available
    if panel_text and len(panel_text) > 50:
        # Try to find product title in panel (often in first few lines or after "Product:" label)
        panel_title = _extract_product_title_from_panel(panel_text)
        if panel_title and len(panel_title) > len(lead.get("product_title", "")):
            lead["product_title"] = panel_title[:200]

    # Updated CSS selectors for new IndiaMART layout (2024-2025)
    # Try multiple selector patterns in order of specificity
    selector_patterns = [
        # Buyer name selectors - new IndiaMART uses data-testid and different class names
        ("[data-testid='buyer-name'], [data-testid='contact-name'], .buyer-name, .byr-name, .contact-name, [class*='buyer'] h3, [class*='contact'] h3, h3[class*='name']", "buyer_name"),
        # Buyer phone selectors - IndiaMART often uses tel: links or specific data attributes
        ("[data-testid='buyer-phone'], [data-testid='contact-phone'], a[href^='tel:'], .buyer-phone, .byr-phone, .contact-phone, [class*='phone'], .phone-no, [class*='mobile']", "buyer_phone"),
        # Message/inquiry selectors
        ("[data-testid='inquiry-message'], [data-testid='buyer-message'], .inqDesc, .inquiry-message, .msg-content, [class*='message'], [class*='requirement']", "message"),
        # Email selectors
        ("[data-testid='buyer-email'], [data-testid='email'], a[href^='mailto:'], .buyer-email, .byr-email, .email", "buyer_email"),
    ]

    for sel, field in selector_patterns:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                val = (await loc.inner_text(timeout=2000)).strip()
                if val and len(val) < 500:
                    if field == "buyer_phone":
                        digits = re.sub(r"\D", "", val)
                        if len(digits) >= 10:
                            lead[field] = digits[-10:] if len(digits) > 10 else digits
                    elif field == "buyer_email":
                        # Validate email format
                        if _EMAIL_RE.match(val):
                            lead[field] = val
                    else:
                        lead[field] = val
        except Exception:
            continue

    dom_contact = await _scrape_contact_from_dom(page)
    if dom_contact.get("buyer_phone") and not lead.get("buyer_phone"):
        lead["buyer_phone"] = dom_contact["buyer_phone"]
    if dom_contact.get("buyer_email") and not lead.get("buyer_email"):
        lead["buyer_email"] = dom_contact["buyer_email"]
    if dom_contact.get("buyer_name") and not lead.get("buyer_name"):
        lead["buyer_name"] = dom_contact["buyer_name"]

    if try_reveal_contact and not lead_has_buyer_contact(lead):
        for attempt in range(3):
            clicked_any = await reveal_indiamart_buyer_contact(page)
            if clicked_any:
                await _wait_for_contact_signal(page, timeout_ms=8000)
            # Re-scrape after reveal attempt regardless of click outcome
            panel_text = await _read_detail_panel_text(page)
            _apply_panel_text_to_lead(lead, panel_text, block_text)
            dom_contact = await _scrape_contact_from_dom(page)
            if dom_contact.get("buyer_phone") and not lead.get("buyer_phone"):
                lead["buyer_phone"] = dom_contact["buyer_phone"]
            if dom_contact.get("buyer_email") and not lead.get("buyer_email"):
                lead["buyer_email"] = dom_contact["buyer_email"]
            if dom_contact.get("buyer_name") and not lead.get("buyer_name"):
                lead["buyer_name"] = dom_contact["buyer_name"]
            if lead_has_buyer_contact(lead):
                break
            if not clicked_any:
                logger.warning("Contact reveal button not found, attempt %d/3", attempt + 1)
                break

    if not lead.get("message") and panel_text:
        for line in panel_text.splitlines():
            line = line.strip()
            if len(line) > 25 and "interested" not in line.lower():
                lead["message"] = line[:500]
                break

    combined = f"{block_text}\n{panel_text}"
    if not lead.get("buyer_location"):
        loc = _CITY_STATE_RE.search(combined)
        if loc:
            lead["buyer_location"] = loc.group(0)
    if not lead.get("buyer_address"):
        lead["buyer_address"] = _parse_address_from_text(combined) or lead.get("buyer_location", "")

    # ===== FALLBACK: Regex-based extraction (layout-independent) =====
    # This catches phone/email even if IndiaMART changes their DOM structure
    if not lead.get("buyer_phone") or not lead.get("buyer_email"):
        fallback = await _regex_fallback_extract(page)
        if fallback.get("phone") and not lead.get("buyer_phone"):
            lead["buyer_phone"] = fallback["phone"]
        if fallback.get("email") and not lead.get("buyer_email"):
            lead["buyer_email"] = fallback["email"]
        if fallback.get("name") and not lead.get("buyer_name"):
            lead["buyer_name"] = fallback["name"]

    return sanitize_lead_contacts(lead, block_text, panel_text)


async def _regex_fallback_extract(page: Page) -> dict[str, str]:
    """
    Layout-independent fallback: extract phone/email/name using pure regex on page text.
    Works even if IndiaMART completely changes their DOM structure.
    
    Phone patterns:
      - +91 followed by 10 digits (with optional spaces/dashes)
      - 10 digits starting with 6-9 (Indian mobile)
      - Numbers near "Mobile", "Phone", "Contact" labels
    
    Email patterns:
      - Standard email format: word@domain.tld
      - Near "Email" label
    
    Name patterns:
      - Text after "Buyer Name:", "Contact Person:", etc.
      - Capitalized words at start of contact section
    """
    result: dict[str, str] = {}
    try:
        # Get full visible text from page
        text = await page.evaluate("() => document.body.innerText || ''")
        if not text or len(text) < 20:
            return result
        
        # Known nav/support numbers to exclude
        nav_phones = {"9716054356", "9696969696", "18002008300", "9999999999"}
        
        # ===== PHONE EXTRACTION =====
        # Priority: Indian mobile > Indian landline > International
        
        # 1. Indian Mobile patterns (most common for IndiaMART)
        indian_mobile_patterns = [
            # +91 prefix
            r"\+91[\s\-]?([6-9]\d{9})",
            r"\+91[\s\-]?([6-9]\d{4})[\s\-]?(\d{5})",
            # Near labels
            r"(?:mobile|phone|contact|tel|call)[\s:.\-]*\+?(?:91)?[\s\-]?([6-9]\d{9})",
            # Standalone 10-digit (starts with 6-9)
            r"(?<!\d)([6-9]\d{9})(?!\d)",
            r"(?<!\d)([6-9]\d{4})[\s\-](\d{5})(?!\d)",
        ]
        
        for pattern in indian_mobile_patterns:
            matches = re.findall(pattern, text, re.I)
            for match in matches:
                digits = "".join(match) if isinstance(match, tuple) else match
                digits = re.sub(r"\D", "", digits)
                if len(digits) >= 10:
                    phone = digits[-10:]
                    if phone not in nav_phones and phone[0] in "6789":
                        result["phone"] = phone
                        break
            if result.get("phone"):
                break
        
        # 2. Indian Landline patterns (STD code + number)
        # Format: 0XX-XXXXXXXX or 0XXX-XXXXXXX (total 11-12 digits with leading 0)
        if not result.get("phone"):
            landline_patterns = [
                # Major cities: 011 (Delhi), 022 (Mumbai), 033 (Kolkata), 044 (Chennai), 080 (Bangalore)
                r"(?:landline|office|tel|phone)[\s:.\-]*(0[1-9]\d{1,2})[\s\-]?(\d{6,8})",
                # Standalone with STD code
                r"(?<!\d)(0[1-9]\d{1,2})[\s\-](\d{6,8})(?!\d)",
                # With parentheses: (022) 12345678
                r"\(?(0[1-9]\d{1,2})\)?[\s\-]?(\d{6,8})",
            ]
            
            for pattern in landline_patterns:
                matches = re.findall(pattern, text, re.I)
                for match in matches:
                    if isinstance(match, tuple):
                        std_code = match[0]
                        number = match[1]
                        full_number = std_code + number
                    else:
                        full_number = match
                    digits = re.sub(r"\D", "", full_number)
                    # Indian landline: 11-12 digits total (with leading 0)
                    if 10 <= len(digits) <= 12 and digits.startswith("0"):
                        if digits not in nav_phones:
                            result["phone"] = digits
                            break
                if result.get("phone"):
                    break
        
        # 3. International numbers (any country code)
        # Format: +XX XXXXXXXXXX or +XXX XXXXXXXXX
        if not result.get("phone"):
            international_patterns = [
                # +country_code followed by number (7-15 digits total is valid internationally)
                r"\+(\d{1,4})[\s\-]?(\d[\d\s\-]{6,14})",
                # Near labels with + prefix
                r"(?:phone|mobile|contact|tel|call|whatsapp)[\s:.\-]*\+(\d{1,4})[\s\-]?(\d[\d\s\-]{6,14})",
            ]
            
            for pattern in international_patterns:
                matches = re.findall(pattern, text, re.I)
                for match in matches:
                    if isinstance(match, tuple):
                        country_code = match[0]
                        number = re.sub(r"\D", "", match[1])
                        full_number = f"+{country_code}{number}"
                    else:
                        full_number = "+" + re.sub(r"\D", "", match)
                    
                    digits_only = re.sub(r"\D", "", full_number)
                    # International: 8-15 digits (including country code)
                    if 8 <= len(digits_only) <= 15:
                        # Skip if it's actually an Indian number we already checked
                        if not (digits_only.startswith("91") and len(digits_only) == 12):
                            result["phone"] = full_number
                            break
                if result.get("phone"):
                    break
        
        # ===== EMAIL EXTRACTION =====
        email_patterns = [
            # Near "Email" label
            r"(?:email|e-mail|mail)[\s:.\-]*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
            # Standalone email
            r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
        ]
        
        skip_emails = {"support@indiamart", "help@indiamart", "info@indiamart", 
                       "noreply@", "no-reply@", "donotreply@"}
        
        for pattern in email_patterns:
            matches = re.findall(pattern, text, re.I)
            for email in matches:
                email_lower = email.lower()
                if not any(skip in email_lower for skip in skip_emails):
                    result["email"] = email_lower
                    break
            if result.get("email"):
                break
        
        # ===== NAME EXTRACTION =====
        name_patterns = [
            # Explicit labels
            r"(?:buyer\s*name|contact\s*person|contact\s*name|name)[\s:.\-]+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3})",
            # Name before company/location
            r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*(?:,|\n|from|at|\|)",
        ]
        
        skip_names = {"buy leads", "dashboard", "settings", "logout", "help", 
                      "indiamart", "seller", "recent", "contact buyer", "view"}
        
        for pattern in name_patterns:
            matches = re.findall(pattern, text, re.M)
            for name in matches:
                name = name.strip()
                if len(name) >= 2 and len(name) <= 60:
                    if not any(skip in name.lower() for skip in skip_names):
                        if not re.search(r"\d", name):  # No digits in name
                            result["name"] = name
                            break
            if result.get("name"):
                break
        
    except Exception:
        pass
    
    return result

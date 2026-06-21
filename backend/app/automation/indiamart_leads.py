from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from playwright.async_api import Page

from app.automation.indiamart_page import (
    INQUIRY_ROW_SELECTORS,
    scroll_lead_list,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

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
    r"\b[A-Za-z][A-Za-z\s.'-]{1,60},\s*[A-Za-z][A-Za-z\s.'&-]{1,60}\b",
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
_IDENTITY_GENERIC_PRODUCT_WORDS = frozenset(
    {
        "laser",
        "machine",
        "machines",
        "system",
        "systems",
        "equipment",
        "marking",
        "marker",
        "welding",
        "welder",
        "cleaning",
        "cleaner",
        "cutting",
        "cutter",
        "engraving",
        "engraver",
        "rust",
        "removal",
        "industrial",
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
        "recommended",
        "sold out!",
        "i am interested",
        "business use",
        "probable requirement type",
        "requirement type",
        "category",
    }
)
_LEAD_BLOCK_BOUNDARY_LINES = frozenset(
    {
        "i am interested",
        "sold out!",
        "buyer info",
        "buyer also viewed",
        "also viewed",
        "similar products",
    }
)
_BAD_BUYER_NAMES = frozenset(
    {
        "indiamart",
        "buy with indiamart",
        "hi tushar",
        "dashboard",
        "profile",
    }
)
_BAD_PRODUCT_TITLES = frozenset(
    {
        "indiamart",
        "buy with indiamart",
        "buy leads",
        "buyleads",
        "lead manager",
        "dashboard",
        "profile",
    }
)
_MATCH_TEXT_STOP_MARKERS = (
    "buyer info",
    "buyer also viewed",
    "also viewed",
    "similar products",
    "recommended",
    "you sell",
    "your products",
    "related products",
)
_NON_LEAD_SECTION_LINES = frozenset(
    {
        "no relevant buyleads found",
        "showing other leads you may like",
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


def _looks_like_address_part(line: str) -> bool:
    line = line.strip(" ,")
    if not line:
        return False
    lower = line.lower().strip(" :")
    if lower in _LOW_VALUE_LEAD_LINES or lower in _NON_LEAD_SECTION_LINES:
        return False
    if _PRODUCT_LINE_RE.search(line):
        return False
    return bool(re.search(r"[A-Za-z]{3,}", line))


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
            if (
                _looks_like_address_part(city)
                and _looks_like_address_part(state)
                and _CITY_STATE_RE.fullmatch(joined)
            ):
                return joined[:300]
    for idx, line in enumerate(lines):
        line = _clean_address_line(line)
        if not line:
            continue
        if idx + 1 < len(lines):
            joined = f"{line.strip(' ,')}, {_clean_address_line(lines[idx + 1])}"
            if (
                _looks_like_address_part(line)
                and _looks_like_address_part(_clean_address_line(lines[idx + 1]))
                and _CITY_STATE_RE.fullmatch(joined)
            ):
                return joined[:300]
        loc = _CITY_STATE_RE.search(line)
        if loc and all(_looks_like_address_part(part) for part in loc.group(0).split(",", 1)):
            return loc.group(0)[:300]
    loc = _CITY_STATE_RE.search(_clean_address_line(text))
    if loc and all(_looks_like_address_part(part) for part in loc.group(0).split(",", 1)):
        return loc.group(0)
    return ""


def lead_fingerprint(block_text: str, lead: dict[str, str] | None = None) -> str:
    """Stable key for dedup — phone/email scoped to product + city, else product + city."""
    lead = lead or {}
    one = _TIME_RE.sub("", " ".join(block_text.split())).lower()
    address = (
        (lead.get("buyer_address") or lead.get("buyer_location") or "").strip()
        or _parse_address_from_text(block_text)
    )
    loc = _CITY_STATE_RE.search(address)
    city = (loc.group(0) if loc else address).lower().strip()
    cat = re.search(r">\s*([^>]+?)(?:\s+power\s*:|\s+probable)", one, re.I)
    product = cat.group(1).strip().lower()[:80] if cat else ""
    if not product:
        product = _lead_title_for_click(block_text).lower()[:80]
    product = re.sub(r"\s+", " ", product).strip()
    scope = f"{product}|{city}"
    digits = re.sub(r"\D", "", lead.get("buyer_phone") or "")
    if len(digits) >= 10:
        return f"ph:{digits[-10:]}|{scope}"
    email = (lead.get("buyer_email") or "").strip().lower()
    if email:
        return f"em:{email}|{scope}"
    return f"pk:{product}|{city}"


def _normalize_identity_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", title.lower())).strip()


def _identity_product_tokens(title: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _normalize_identity_title(title))
        if len(token) >= 2
    }


def _identity_discriminator_tokens(title: str) -> set[str]:
    return {
        token
        for token in _identity_product_tokens(title)
        if token not in _IDENTITY_GENERIC_PRODUCT_WORDS
    }


def _lead_identity_titles(block_text: str) -> list[str]:
    titles: list[str] = []

    def add(title: str) -> None:
        clean = re.sub(r"^category\s*:\s*", "", (title or "").strip(), flags=re.I)
        clean = re.sub(r"\s+", " ", clean.strip(" ,-|:"))
        if len(clean) < 8 or _is_bad_product_title(clean):
            return
        if ":" in clean:
            return
        if _looks_like_address_part(clean) and not _PRODUCT_LINE_RE.search(clean):
            return
        norm = _normalize_identity_title(clean)
        if norm and norm not in {_normalize_identity_title(t) for t in titles}:
            titles.append(clean[:120])

    add(_lead_title_for_click(block_text))
    lines = [line.strip() for line in block_text.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        low = line.lower().strip(" :")
        if low == "category" and idx + 1 < len(lines):
            add(lines[idx + 1])
        if low.startswith("category:"):
            add(line.split(":", 1)[1])
        if _looks_like_product_line(line):
            add(line)
    one = " ".join(block_text.split())
    for match in re.finditer(r">\s*([^>]+?)(?:\s+[A-Z][A-Za-z ]+\s*:|\s*$)", one):
        add(match.group(1))
    return titles


def _product_titles_compatible(candidate_title: str, expected_title: str) -> bool:
    candidate_norm = _normalize_identity_title(candidate_title)
    expected_norm = _normalize_identity_title(expected_title)
    if not candidate_norm or not expected_norm:
        return False
    if candidate_norm == expected_norm:
        return True
    if candidate_norm in expected_norm or expected_norm in candidate_norm:
        return True

    candidate_tokens = _identity_product_tokens(candidate_title)
    expected_tokens = _identity_product_tokens(expected_title)
    if not candidate_tokens or not expected_tokens:
        return False
    shared = candidate_tokens & expected_tokens
    shorter = min(len(candidate_tokens), len(expected_tokens))
    if shorter <= 0 or len(shared) / shorter < 0.75 or len(shared) < 3:
        return False

    candidate_discriminators = _identity_discriminator_tokens(candidate_title)
    expected_discriminators = _identity_discriminator_tokens(expected_title)
    if (
        candidate_discriminators
        and expected_discriminators
        and not (candidate_discriminators & expected_discriminators)
    ):
        return False
    return True


def lead_identity_matches(candidate_text: str, expected_text: str) -> bool:
    """True when a currently visible row is the same lead captured earlier."""
    if not candidate_text or not expected_text:
        return False
    if lead_fingerprint(candidate_text, {}) == lead_fingerprint(expected_text, {}):
        return True

    candidate_title = _lead_title_for_click(candidate_text).lower()
    expected_title = _lead_title_for_click(expected_text).lower()
    if not candidate_title or not expected_title:
        return False

    candidate_address = _parse_address_from_text(candidate_text).lower()
    expected_address = _parse_address_from_text(expected_text).lower()
    if candidate_address and expected_address:
        if candidate_address != expected_address:
            return False
        candidate_titles = _lead_identity_titles(candidate_text)
        expected_titles = _lead_identity_titles(expected_text)
        candidate_discriminators = set().union(
            *(_identity_discriminator_tokens(title) for title in candidate_titles)
        )
        expected_discriminators = set().union(
            *(_identity_discriminator_tokens(title) for title in expected_titles)
        )
        if (
            candidate_discriminators
            and expected_discriminators
            and not (candidate_discriminators & expected_discriminators)
        ):
            return False
        return any(
            _product_titles_compatible(candidate, expected)
            for candidate in candidate_titles
            for expected in expected_titles
        )

    return False


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
        if low in _BAD_BUYER_NAMES:
            continue
        if any(m in low for m in _NAV_NAME_MARKERS):
            continue
        if low in ("business use", "probable requirement type", "sold out!"):
            continue
        kept.append(line)
    return " ".join(kept)[:120].strip()


def _is_bad_product_title(title: str) -> bool:
    low = re.sub(r"\s+", " ", (title or "").strip().lower())
    if not low:
        return True
    if low in _BAD_PRODUCT_TITLES:
        return True
    if any(marker in low for marker in ("seller dashboard", "buy with indiamart")):
        return True
    return False


def sanitize_product_title(title: str, block_text: str = "") -> str:
    """Prefer the matched feed-card title over nav/header text from the page shell."""
    candidate = re.sub(r"\s+", " ", (title or "").strip())
    candidate = re.sub(r"^category\s*:\s*", "", candidate, flags=re.IGNORECASE)
    if candidate and not _is_bad_product_title(candidate):
        return candidate[:200]
    fallback = _lead_title_for_click(block_text)
    fallback = re.sub(r"^category\s*:\s*", "", fallback, flags=re.IGNORECASE)
    if fallback and not _is_bad_product_title(fallback):
        return fallback[:200]
    return ""


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
    if out.get("product_title"):
        clean_title = sanitize_product_title(str(out["product_title"]), block_text)
        if clean_title:
            out["product_title"] = clean_title
        else:
            out.pop("product_title", None)
    else:
        clean_title = sanitize_product_title("", block_text)
        if clean_title:
            out["product_title"] = clean_title

    if out.get("buyer_name"):
        out["buyer_name"] = sanitize_buyer_name(str(out["buyer_name"]))
        if not out["buyer_name"]:
            out.pop("buyer_name", None)
    
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


async def _wait_for_lead_feed(page: Page, timeout_ms: int = 6_000) -> bool:
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


def _line_has_time_marker(line: str) -> bool:
    return bool(_TIME_LINE_RE.match(line) or _TIME_RE.search(line))


def _blocks_from_body_text(body: str, max_blocks: int = 40) -> list[BuyerLeadBlock]:
    """Split full page text into lead chunks when DOM selectors miss cards."""
    if not body or len(body) < 50:
        return []
    lines = [
        ln.strip()
        for ln in body.splitlines()
        if ln.strip() and ln.strip().lower() not in _NON_LEAD_SECTION_LINES
    ]
    blocks: list[BuyerLeadBlock] = []
    i = 0
    while i < len(lines):
        if not _line_has_time_marker(lines[i]):
            i += 1
            continue
        start = i
        lookback = 0
        while start > 0 and lookback < 3:
            prev = lines[start - 1]
            prev_low = prev.lower().strip(" :")
            if (
                _line_has_time_marker(prev)
                or prev_low in _LEAD_BLOCK_BOUNDARY_LINES
                or prev_low in _NON_LEAD_SECTION_LINES
                or prev_low in ("recent", "buy leads", "all", "recommended")
                or prev_low.startswith("category:")
            ):
                break
            start -= 1
            lookback += 1
            if _looks_like_product_line(prev):
                break
        while start < i and (
            _TIME_LINE_RE.match(lines[start])
            or len(lines[start]) < 3
            or lines[start].lower() in ("recent", "buy leads", "all", "recommended")
        ):
            start += 1
        end = i + 1
        while end < len(lines) and not _line_has_time_marker(lines[end]) and end - i < 22:
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


def _split_candidate_text_into_cards(
    text: str, selector: str = "raw-split", max_blocks: int = 40
) -> list[BuyerLeadBlock]:
    """Recover individual lead cards from broad list/section wrapper text."""
    if not text:
        return []
    time_hits = len(_TIME_RE.findall(text))
    lower = text.lower()
    if time_hits <= 1 and not any(line in lower for line in _NON_LEAD_SECTION_LINES):
        return []
    return _blocks_from_body_text(text, max_blocks=max_blocks)


async def collect_buyer_lead_blocks(
    page: Page, max_blocks: int = 40, *, visible_only: bool = False
) -> list[BuyerLeadBlock]:
    await _wait_for_lead_feed(
        page,
        timeout_ms=settings.INDIAMART_VISIBLE_SCAN_WAIT_MS if visible_only else 6_000,
    )
    if not visible_only:
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
            await sleep(600);
            return true;
          } catch (e) {}
        }
        return false;
      };

      if (!config.visibleOnly) {
        scrollRoots.forEach(root => { try { root.scrollTop = 0; } catch (e) {} });
        window.scrollTo(0, 0);
        await sleep(200);
      }

      let stagnant = 0;
      const maxSteps = config.visibleOnly ? 1 : 12;
      for (let step = 0; step < maxSteps && out.length < maxBlocks * 4; step += 1) {
        sampleVisibleRows(`scan-${step}`);
        if (config.visibleOnly) break;
        if (step > 0 && step % 6 === 0) await clickLoadMore();

        let moved = false;
        for (const root of scrollRoots.slice(0, 6)) {
          try {
            const before = root.scrollTop || 0;
            const delta = Math.max(520, Math.floor((root.clientHeight || window.innerHeight) * 0.9));
            root.scrollTop = Math.min(root.scrollHeight, before + delta);
            if ((root.scrollTop || 0) > before + 4) moved = true;
          } catch (e) {}
        }
        const beforeWindow = window.scrollY || pageYOffset || 0;
        window.scrollBy(0, Math.max(420, Math.floor(window.innerHeight * 0.72)));
        if ((window.scrollY || pageYOffset || 0) > beforeWindow + 4) moved = true;

        await sleep(250);
        stagnant = moved ? 0 : stagnant + 1;
        if (stagnant >= 3) break;
      }

      if (!config.visibleOnly) {
        sampleVisibleRows('scan-final');
        scrollRoots.forEach(root => { try { root.scrollTop = 0; } catch (e) {} });
        window.scrollTo(0, 0);
      }
      return out;
    }
    """
    raw: list = []
    try:
        raw = await page.evaluate(
            script,
            {
                "selectors": INQUIRY_ROW_SELECTORS,
                "maxBlocks": max_blocks,
                "visibleOnly": visible_only,
            },
        )
    except Exception:
        raw = []

    candidates: list[dict[str, object]] = []
    for item in raw or []:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        split_blocks = _split_candidate_text_into_cards(
            text,
            selector=f"{item.get('selector') or 'raw'}:split",
            max_blocks=max_blocks,
        )
        for block in split_blocks:
            candidates.append(
                {
                    "text": block.text,
                    "row_index": block.row_index,
                    "selector": block.selector,
                }
            )
        candidates.append(item)

    def candidate_sort_score(item: dict[str, object]) -> int:
        text = str(item.get("text") or "")
        score = _lead_candidate_score(text)
        time_hits = len(_TIME_RE.findall(text))
        lower = text.lower()
        if time_hits > 1:
            score -= 90 * (time_hits - 1)
        if any(line in lower for line in _NON_LEAD_SECTION_LINES):
            score -= 120
        return score

    sorted_raw = sorted(candidates, key=candidate_sort_score, reverse=True)
    blocks: list[BuyerLeadBlock] = []
    seen_texts: list[str] = []
    for item in sorted_raw:
        text = (item.get("text") or "").strip()
        if not is_seller_incoming_buy_lead(text):
            continue
        compact = re.sub(r"\s+", " ", text).strip().lower()
        if any(compact == prev or compact in prev or prev in compact for prev in seen_texts):
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
            or lower.startswith("buyer filled details")
            or lower.startswith("buyer also mentioned")
            or lower.startswith("buyer details")
            or lower.startswith("category")
            or lower.startswith("power")
            or lower.startswith("output power")
            or lower.startswith("laser power")
            or lower.startswith("marking area")
            or lower.startswith("working area")
            or lower.startswith("material")
            or lower.startswith("requirement type")
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


def lead_match_text(block_text: str) -> str:
    """
    Text that is safe for keyword matching.

    IndiaMART cards can include recommendations, seller catalog snippets, or buyer-profile
    text. Matching the whole block can pick wrong products. Keep only the lead's own title,
    category/search intent, and location so location filters still work.
    """
    parts: list[str] = []

    def add(value: str) -> None:
        value = re.sub(r"\s+", " ", (value or "").strip(" ,-|:"))
        if not value or len(value) < 3:
            return
        low = value.lower()
        if low in _LOW_VALUE_LEAD_LINES or low in _BAD_PRODUCT_TITLES:
            return
        if value not in parts:
            parts.append(value)

    lead_only_lines: list[str] = []
    for raw in block_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if any(marker in line.lower() for marker in _MATCH_TEXT_STOP_MARKERS):
            break
        lead_only_lines.append(line)

    lead_only_text = "\n".join(lead_only_lines) if lead_only_lines else block_text

    buyer_search_terms: list[str] = []
    for line in lead_only_lines:
        m = re.search(r"\bbuyer\s+searched\s+for\s+(.+)$", line, re.IGNORECASE)
        if m:
            term = re.sub(r"\s+", " ", m.group(1).strip(" ,-|:"))
            if term and term.lower() not in _LOW_VALUE_LEAD_LINES:
                buyer_search_terms.append(term)

    one = " ".join(lead_only_text.split())
    for match in re.finditer(
        r"\bBuyer\s+Searched\s+for\s+(.+?)(?:\s+(?:Laser\s+Power|Power|"
        r"Marking\s+Area|Requirement\s+Type|Requirement\s*:|Sold\s+Out|Buyer\s+Info)\b|$)",
        one,
        re.IGNORECASE,
    ):
        term = re.sub(r"\s+", " ", match.group(1).strip(" ,-|:"))
        if term and term.lower() not in _LOW_VALUE_LEAD_LINES:
            buyer_search_terms.append(term)

    if buyer_search_terms:
        for term in buyer_search_terms:
            add(term)
        address = _parse_address_from_text(block_text)
        if address:
            add(address)
        return "\n".join(parts) if parts else block_text

    title = _lead_title_for_click(lead_only_text)
    if title:
        add(title)

    for line in lead_only_lines:
        line = re.sub(r"^category\s*:\s*", "Category: ", line, flags=re.IGNORECASE)
        m = re.search(r"\bcategory\s*:\s*(.+)$", line, re.IGNORECASE)
        if m:
            add(m.group(1))
            continue
        m = re.search(r"\bbuyer\s+searched\s+for\s+(.+)$", line, re.IGNORECASE)
        if m:
            add(m.group(1))
            continue
        if _TIME_RE.search(line) or _CITY_STATE_RE.search(line):
            continue
        lower = line.lower().strip(" :")
        if lower in _LOW_VALUE_LEAD_LINES or lower in (
            "laser power",
            "power",
            "marking area",
            "working area",
            "requirement type",
            "probable requirement type",
            "finance/loan requirement",
            "automatic grade",
        ):
            continue

    for pat in (
        r"\bCategory\s*:\s*([^:]+?)(?:\s+(?:Buyer\s+Searched|Laser\s+Power|"
        r"Power|Marking\s+Area|Requirement\s+Type)\b|$)",
        r"\bBuyer\s+Searched\s+for\s+(.+?)(?:\s+(?:Laser\s+Power|Power|"
        r"Marking\s+Area|Requirement\s+Type)\b|$)",
        r">\s*([^>]+?)(?:\s+(?:Working\s+Area|Laser\s+Power|Power|Probable|"
        r"Requirement\s+Type|Price|Quantity)\s*:|\s+Probable\b|\s*$)",
    ):
        for match in re.finditer(pat, one, re.IGNORECASE):
            add(match.group(1))

    address = _parse_address_from_text(block_text)
    if address:
        add(address)
    return "\n".join(parts) if parts else block_text


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
    "Call Now",
    "View Buyer Details",
    "Contact Now",
    "View Phone",
)


async def reveal_indiamart_buyer_contact(page: Page) -> bool:
    """Click any detail-panel control that likely reveals buyer phone/name."""
    clicked_any = False

    async def panel_scopes() -> list:
        scopes = []
        for sel in (
            "[role='dialog']",
            ".inqry-detail-panel",
            ".inquiry-detail",
            ".byr-detail",
            ".msg-detail-panel",
            "[class*='detail-panel']",
            "[class*='contact-detail']",
            "[class*='buyer-info']",
            "[class*='Detail']",
            "aside",
            "main",
        ):
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    scopes.append(loc)
            except Exception:
                continue
        return scopes

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
            for scope in await panel_scopes():
                loc = scope.locator(sel).first
                if await loc.count() > 0:
                    await loc.scroll_into_view_if_needed(timeout=2000)
                    await loc.click(timeout=4000)
                    await page.wait_for_timeout(2500)
                    clicked_any = True
                    logger.info("Clicked contact reveal button selector=%s", sel)
                    break
            if clicked_any:
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
                    for scope in await panel_scopes():
                        loc = scope.get_by_role(
                            role, name=re.compile(re.escape(label), re.I)
                        )
                        n = await loc.count()
                        for i in range(min(n, 2)):
                            try:
                                el = loc.nth(i)
                                await el.scroll_into_view_if_needed(timeout=3000)
                                await el.click(timeout=4000)
                                await page.wait_for_timeout(1800)
                                clicked_any = True
                                break
                            except Exception:
                                continue
                        if clicked_any:
                            break
                except Exception:
                    pass
                if clicked_any:
                    break
            if clicked_any:
                break

    if not clicked_any:
        # Strategy 3: Some IndiaMART rows reveal contact only after the interest CTA.
        for label in _INTEREST_BUTTON_LABELS:
            for role in ("button", "link"):
                try:
                    for scope in await panel_scopes():
                        loc = scope.get_by_role(
                            role, name=re.compile(re.escape(label), re.I)
                        )
                        n = await loc.count()
                        for i in range(min(n, 2)):
                            try:
                                el = loc.nth(i)
                                await el.scroll_into_view_if_needed(timeout=3000)
                                await el.click(timeout=5000)
                                await page.wait_for_timeout(2200)
                                clicked_any = True
                                break
                            except Exception:
                                continue
                        if clicked_any:
                            break
                except Exception:
                    pass
                if clicked_any:
                    break
            if clicked_any:
                break
    try:
        broad = None
        for scope in await panel_scopes():
            broad = scope.locator("button, a, [role='button']").filter(
                has_text=re.compile(
                    r"contact|mobile|phone|number|call|whatsapp|buyer|detail",
                    re.I,
                )
            )
            if await broad.count() > 0:
                break
        n = await broad.count() if broad is not None else 0
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
                document.querySelector('[role="dialog"]'),
                document.querySelector('[class*="detail"]'),
                document.querySelector('[class*="Detail"]'),
                document.querySelector('[class*="contact"]'),
                document.querySelector('main'),
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


async def click_buyer_lead_block(
    page: Page, block: BuyerLeadBlock, *, stale_panel_text: str = ""
) -> bool:
    title = _lead_title_for_click(block.text)
    if title:
        try:
            target = await page.evaluate(
                """(args) => {
                  const t = args.title.toLowerCase().slice(0, 80);
                  const address = (args.address || '').toLowerCase();
                  const addressParts = address.split(',').map(s => s.trim()).filter(Boolean);
                  const norm = (s) => (s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
                  const titleNeedle = norm(t);
                  const addressNeedles = addressParts.map(norm).filter(Boolean);
                  const timeRe = /just\\s+now|\\d+\\s*(?:min|mins|hr|hrs|hour|hours|day|days)\\s*ago/i;
                  const timeGlobalRe = /just\\s+now|\\d+\\s*(?:min|mins|hr|hrs|hour|hours|day|days)\\s*ago/gi;
                  const preferredClickText = /contact\\s*buyer|contact\\s*now|view\\s*(?:mobile|number|phone|contact)|show\\s*(?:mobile|number|phone|contact)|get\\s*contact|call\\s*(?:buyer|now)|phone|mobile|whatsapp|i\\s*am\\s*interested/i;
                  const clickableSelector = 'a, button, [role="button"], [role="link"], [onclick], [tabindex], [class*="contact"], [class*="mobile"], [class*="phone"], [class*="card"], [class*="lead"], [class*="inq"]';
                  const leadTimeCount = (el) => ((el.innerText || '').match(timeGlobalRe) || []).length;
                  const visible = (el) => {
                    const r = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return r.width > 2 && r.height > 2 && style.visibility !== 'hidden' && style.display !== 'none';
                  };
                  const nodeMatchesLead = (el) => {
                    const raw = (el.innerText || '').trim();
                    if (raw.length < 15 || raw.length > 4200) return false;
                    const compact = norm(raw);
                    if (!compact.includes(titleNeedle)) return false;
                    if (addressNeedles.length && !addressNeedles.every(part => compact.includes(part))) return false;
                    if (!timeRe.test(raw)) return false;
                    // A parent feed/list can contain the matched title plus a CTA for
                    // an earlier card. Only click inside one lead-card sized scope.
                    if (((raw.match(timeGlobalRe) || []).length) > 1) return false;
                    return visible(el);
                  };
                  const preferredTargets = (root) => {
                    if (leadTimeCount(root) > 1) return [];
                    const nodes = root.matches && root.matches(clickableSelector)
                      ? [root, ...root.querySelectorAll(clickableSelector)]
                      : [...root.querySelectorAll(clickableSelector)];
                    const out = [];
                    for (const el of nodes) {
                      const text = (el.innerText || el.textContent || '').trim();
                      if (!text || text.length > 1200 || !visible(el)) continue;
                      if (preferredClickText.test(text)) out.push(el);
                    }
                    out.sort((a, b) => {
                      const ar = a.getBoundingClientRect();
                      const br = b.getBoundingClientRect();
                      return (ar.width * ar.height) - (br.width * br.height);
                    });
                    return out;
                  };
                  const candidates = [];
                  for (const el of [...document.querySelectorAll('div, li, article, a, tr, section')]) {
                    if (!nodeMatchesLead(el)) continue;
                    const r = el.getBoundingClientRect();
                    candidates.push({ el, area: r.width * r.height, preferred: preferredTargets(el) });
                    let parent = el.parentElement;
                    for (let depth = 0; depth < 10 && parent && parent !== document.body; depth += 1) {
                      if (!nodeMatchesLead(parent)) break;
                      const pr = parent.getBoundingClientRect();
                      const preferred = preferredTargets(parent);
                      candidates.push({ el: parent, area: pr.width * pr.height, preferred });
                      if (preferred.length) break;
                      parent = parent.parentElement;
                    }
                  }
                  candidates.sort((a, b) => {
                    if (b.preferred.length !== a.preferred.length) return b.preferred.length - a.preferred.length;
                    return a.area - b.area;
                  });
                  if (!candidates.length) return null;
                  const card = candidates[0].el;
                  card.scrollIntoView({ block: 'center', inline: 'nearest' });
                  const targets = candidates[0].preferred.length ? candidates[0].preferred : [card];
                  const target = targets[0];
                  target.scrollIntoView({ block: 'center', inline: 'nearest' });
                  const r = target.getBoundingClientRect();
                  return {
                    x: r.left + r.width / 2,
                    y: r.top + r.height / 2,
                    text: (target.innerText || target.textContent || '').trim().slice(0, 160),
                    card_preview: (card.innerText || card.textContent || '').trim().slice(0, 260),
                    preferred_count: candidates[0].preferred.length,
                    time_count: leadTimeCount(card),
                  };
                }""",
                {"title": title, "address": _parse_address_from_text(block.text)},
            )
            if target and target.get("x") is not None and target.get("y") is not None:
                await page.mouse.move(float(target["x"]), float(target["y"]))
                await page.mouse.down()
                await page.wait_for_timeout(80)
                await page.mouse.up()
                await page.wait_for_timeout(1800)
                panel_text = await _wait_for_detail_panel_after_click(
                    page,
                    block.text,
                    stale_panel_text=stale_panel_text,
                    timeout_ms=2500,
                )
                if _panel_matches_block(
                    panel_text, block.text, stale_panel_text=stale_panel_text
                ):
                    logger.info(
                        "Native mouse clicked verified lead target text=%r card=%r",
                        str(target.get("text") or "")[:100],
                        str(target.get("card_preview") or "")[:160],
                    )
                    return True
                logger.warning(
                    "Native mouse click target did not open matching panel "
                    "target_text=%r card_preview=%r time_count=%s panel_preview=%r",
                    str(target.get("text") or "")[:120],
                    str(target.get("card_preview") or "")[:180],
                    target.get("time_count"),
                    panel_text[:180],
                )
        except Exception:
            pass
        try:
            clicked = await page.evaluate(
                """(args) => {
                  const t = args.title.toLowerCase().slice(0, 80);
                  const address = (args.address || '').toLowerCase();
                  const addressParts = address.split(',').map(s => s.trim()).filter(Boolean);
                  const norm = (s) => (s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
                  const titleNeedle = norm(t);
                  const addressNeedles = addressParts.map(norm).filter(Boolean);
                  const timeRe = /just\\s+now|\\d+\\s*(?:min|mins|hr|hrs|hour|hours|day|days)\\s*ago/i;
                  const timeGlobalRe = /just\\s+now|\\d+\\s*(?:min|mins|hr|hrs|hour|hours|day|days)\\s*ago/gi;
                  const preferredClickText = /contact\\s*buyer|contact\\s*now|view\\s*(?:mobile|number|phone|contact)|show\\s*(?:mobile|number|phone|contact)|get\\s*contact|call\\s*(?:buyer|now)|phone|mobile|whatsapp|i\\s*am\\s*interested/i;
                  const dispatchClick = (el) => {
                    el.scrollIntoView({ block: 'center', inline: 'nearest' });
                    const r = el.getBoundingClientRect();
                    if (r.width < 2 || r.height < 2) return false;
                    const x = r.left + Math.min(Math.max(r.width / 2, 6), Math.max(r.width - 6, 1));
                    const y = r.top + Math.min(Math.max(r.height / 2, 6), Math.max(r.height - 6, 1));
                    for (const type of ['pointerover', 'pointerenter', 'mouseover', 'mouseenter', 'pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                      const opts = { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y, button: 0 };
                      try {
                        if (type.startsWith('pointer')) {
                          el.dispatchEvent(new PointerEvent(type, { ...opts, pointerId: 1, pointerType: 'mouse', isPrimary: true }));
                        } else {
                          el.dispatchEvent(new MouseEvent(type, opts));
                        }
                      } catch (e) {
                        el.dispatchEvent(new MouseEvent(type.replace('pointer', 'mouse'), opts));
                      }
                    }
                    try { el.click(); } catch (e) {}
                    return true;
                  };
                  const clickableSelector = 'a, button, [role="button"], [role="link"], [onclick], [tabindex], [class*="contact"], [class*="mobile"], [class*="phone"], [class*="card"], [class*="lead"], [class*="inq"]';
                  const leadTimeCount = (el) => ((el.innerText || '').match(timeGlobalRe) || []).length;
                  const findPreferredTargets = (root) => {
                    if (leadTimeCount(root) > 1) return [];
                    const out = [];
                    const nodes = root.matches && root.matches(clickableSelector)
                      ? [root, ...root.querySelectorAll(clickableSelector)]
                      : [...root.querySelectorAll(clickableSelector)];
                    for (const el of nodes) {
                      const text = (el.innerText || el.textContent || '').trim();
                      if (!text || text.length > 1200) continue;
                      if (preferredClickText.test(text)) out.push(el);
                    }
                    out.sort((a, b) => {
                      const ar = a.getBoundingClientRect();
                      const br = b.getBoundingClientRect();
                      return (ar.width * ar.height) - (br.width * br.height);
                    });
                    return out;
                  };
                  const nodeMatchesLead = (el) => {
                    const raw = (el.innerText || '').trim();
                    if (raw.length < 15 || raw.length > 3200) return false;
                    const compact = norm(raw);
                    if (!compact.includes(titleNeedle)) return false;
                    if (addressNeedles.length && !addressNeedles.every(part => compact.includes(part))) return false;
                    if (!timeRe.test(raw)) return false;
                    if (((raw.match(timeGlobalRe) || []).length) > 1) return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 2 && r.height > 2;
                  };
                  const nodes = [...document.querySelectorAll('div, li, article, a, tr, section')];
                  const candidates = [];
                  for (const el of nodes) {
                    if (!nodeMatchesLead(el)) continue;
                    const r = el.getBoundingClientRect();
                    const area = r.width * r.height;
                    const preferred = findPreferredTargets(el);
                    candidates.push({ el, area, preferredCount: preferred.length });
                    // If the matching text node is smaller than the whole card,
                    // climb ancestors to find the enclosing card that owns the CTA.
                    let parent = el.parentElement;
                    for (let depth = 0; depth < 8 && parent && parent !== document.body; depth += 1) {
                      if (!nodeMatchesLead(parent)) break;
                      const pr = parent.getBoundingClientRect();
                      const pArea = pr.width * pr.height;
                      const pPreferred = findPreferredTargets(parent);
                      candidates.push({ el: parent, area: pArea, preferredCount: pPreferred.length });
                      if (pPreferred.length) break;
                      parent = parent.parentElement;
                    }
                  }
                  candidates.sort((a, b) => {
                    if (b.preferredCount !== a.preferredCount) return b.preferredCount - a.preferredCount;
                    return a.area - b.area;
                  });
                  const best = candidates.length ? candidates[0].el : null;
                  if (best) {
                    best.scrollIntoView({ block: 'center', inline: 'nearest' });
                    const clickable = best.matches && best.matches(clickableSelector)
                      ? [best, ...best.querySelectorAll(clickableSelector)]
                      : [...best.querySelectorAll(clickableSelector)];
                    const preferredTargets = [];
                    const identityTargets = [];
                    for (const el of clickable) {
                      const text = (el.innerText || el.textContent || '').trim();
                      if (!text || text.length > 1200) continue;
                      const compactText = norm(text);
                      if (preferredClickText.test(text)) {
                        preferredTargets.push(el);
                      } else if (compactText.includes(titleNeedle) || addressNeedles.some(part => compactText.includes(part))) {
                        identityTargets.push(el);
                      }
                    }
                    const targets = [...preferredTargets, ...identityTargets, best];
                    for (const target of targets) {
                      if (dispatchClick(target)) {
                        return true;
                      }
                    }
                  }
                  return false;
                }""",
                {"title": title, "address": _parse_address_from_text(block.text)},
            )
            if clicked:
                await page.wait_for_timeout(1800)
                panel_text = await _wait_for_detail_panel_after_click(
                    page,
                    block.text,
                    stale_panel_text=stale_panel_text,
                    timeout_ms=2500,
                )
                if _panel_matches_block(
                    panel_text, block.text, stale_panel_text=stale_panel_text
                ):
                    return True
                logger.warning(
                    "Verified lead click did not open matching panel; trying locator fallback "
                    "block_title=%r panel_preview=%r",
                    title,
                    panel_text[:180],
                )
        except Exception:
            pass
    try:
        if block.selector not in ("body-split", "card-heuristic", "heuristic"):
            loc = page.locator(block.selector)
            count = await loc.count()
            if count > block.row_index:
                candidate_text = (await loc.nth(block.row_index).inner_text(timeout=3000)).strip()
                if lead_identity_matches(candidate_text, block.text):
                    await loc.nth(block.row_index).click(timeout=8000, force=True)
                    await page.wait_for_timeout(1800)
                    panel_text = await _wait_for_detail_panel_after_click(
                        page,
                        block.text,
                        stale_panel_text=stale_panel_text,
                        timeout_ms=2500,
                    )
                    return _panel_matches_block(
                        panel_text, block.text, stale_panel_text=stale_panel_text
                    )
    except Exception:
        return False
    return False


async def _read_detail_panel_text(page: Page) -> str:
    panel_text = ""
    for sel in (
        "[role='dialog']",
        "[aria-modal='true']",
        "[class*='modal']",
        "[class*='Modal']",
        "[class*='popup']",
        "[class*='Popup']",
        "[class*='overlay']",
        "[class*='Overlay']",
        "[class*='drawer']",
        "[class*='Drawer']",
        "[class*='contact-detail']",
        "[class*='contactDetail']",
        "[class*='buyer-info']",
        "[class*='buyerInfo']",
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
        modal_text = await page.evaluate(
            """() => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 20 && r.height > 20 &&
                  s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity || 1) > 0;
              };
              const signal = /contact|buyer|mobile|phone|email|whatsapp|view number|contact buyer|hi\\s+[a-z]/i;
              const roots = [...document.querySelectorAll(
                '[role="dialog"],[aria-modal="true"],[class*="modal"],[class*="Modal"],' +
                '[class*="popup"],[class*="Popup"],[class*="overlay"],[class*="Overlay"],' +
                '[class*="drawer"],[class*="Drawer"],[class*="contact"],[class*="buyer"],aside'
              )];
              const candidates = [];
              for (const el of roots) {
                if (!visible(el)) continue;
                const text = (el.innerText || '').trim();
                if (text.length < 40 || text.length > 5000 || !signal.test(text)) continue;
                const r = el.getBoundingClientRect();
                const z = Number.parseInt(window.getComputedStyle(el).zIndex || '0', 10) || 0;
                candidates.push({ text, area: r.width * r.height, z });
              }
              candidates.sort((a, b) => (b.z - a.z) || (a.area - b.area));
              return candidates.length ? candidates[0].text : '';
            }"""
        )
        if modal_text and len(str(modal_text)) > 40:
            return str(modal_text)
    except Exception:
        pass
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


def _product_context_words(text: str) -> list[str]:
    words = [
        w
        for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(w) >= 3 and w not in _GENERIC_MATCH_WORDS
    ]
    out: list[str] = []
    for word in words:
        if word not in out:
            out.append(word)
    return out


def _normalized_panel_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _panel_changed_enough(before: str, after: str) -> bool:
    prev = _normalized_panel_text(before)
    cur = _normalized_panel_text(after)
    if not prev:
        return True
    if not cur or prev == cur:
        return False
    if len(cur) > 80 and (cur in prev or prev in cur):
        return False
    return True


def _panel_has_contact_card(text: str) -> bool:
    if not text:
        return False
    has_contact = bool(_PHONE_RE.search(text) or _EMAIL_RE.search(text))
    if not has_contact:
        return False
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    has_nameish = bool(_extract_name_from_panel_top(text) or _parse_name_from_panel(text))
    return has_nameish or len(lines) <= 20


def _panel_has_fresh_buyer_response_popup(text: str) -> bool:
    """IndiaMART response popup may omit product title; require buyer-name greeting."""
    if not _panel_has_contact_card(text):
        return False
    name = _extract_name_from_panel_top(text) or _parse_name_from_panel(text)
    if not name:
        return False
    first = re.escape(name.split()[0])
    return bool(re.search(rf"\bhi\s+{first}\b", text, re.IGNORECASE))


def _panel_address_conflicts(panel_text: str, block_text: str) -> bool:
    expected = _parse_address_from_text(block_text).lower()
    if not expected:
        return False
    panel = (panel_text or "").lower()
    if expected in panel:
        return False
    parsed_panel_address = _parse_address_from_text(panel_text).lower()
    if parsed_panel_address:
        return parsed_panel_address != expected
    found = [
        match.group(0).lower()
        for match in _CITY_STATE_RE.finditer(panel_text or "")
        if all(_looks_like_address_part(part) for part in match.group(0).split(",", 1))
    ]
    return bool(found)


def _panel_matches_block(
    panel_text: str, block_text: str, *, stale_panel_text: str = ""
) -> bool:
    """True when the open detail/contact panel still appears to be the clicked row."""
    if not block_text:
        return True
    panel = (panel_text or "").lower()
    if not panel or len(panel) < 40:
        return False
    panel_changed = _panel_changed_enough(stale_panel_text, panel_text)
    if stale_panel_text and not panel_changed:
        return False
    if _panel_address_conflicts(panel_text, block_text):
        return False

    title = _lead_title_for_click(block_text)
    title_words = _product_context_words(title)
    if not title_words:
        title_words = _product_context_words(lead_match_text(block_text))
    if not title_words:
        return True

    hits = [word for word in title_words if re.search(rf"\b{re.escape(word)}\b", panel)]
    needed = min(len(title_words), 2)
    if len(hits) >= needed:
        return True

    # IndiaMART's response popup can show buyer name/email/phone in the left rail while
    # the message area contains seller product/template text, not the buy-lead title.
    # Accept that no-title contact card only when it is freshly opened and has a
    # buyer-name greeting. This prevents stale old panels from leaking old phones
    # like 9313310116 into unrelated leads.
    return (
        bool(stale_panel_text)
        and panel_changed
        and _panel_has_fresh_buyer_response_popup(panel_text)
    )


async def _wait_for_detail_panel_after_click(
    page: Page,
    block_text: str,
    stale_panel_text: str = "",
    timeout_ms: int = 4500,
) -> str:
    """Wait until the clicked lead's detail/contact panel replaces stale content."""
    deadline = timeout_ms / 1000
    loop = 0.0
    latest = ""
    while loop <= deadline:
        latest = await _read_detail_panel_text(page)
        if latest and _panel_matches_block(
            latest, block_text, stale_panel_text=stale_panel_text
        ):
            return latest
        await page.wait_for_timeout(250)
        loop += 0.25
    return latest


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


def _contact_failure_reason(
    *,
    panel_text: str,
    panel_matches_block: bool,
    reveal_clicked: bool,
    contact_signal_seen: bool,
) -> str:
    """Short operator-facing reason for a matched lead without phone/email."""
    panel = (panel_text or "").lower()
    if not panel_matches_block:
        return "detail panel did not match clicked lead"
    if not reveal_clicked:
        return "contact reveal button not found"
    if re.search(r"initiated\s+(?:a\s+)?contact|contact\s+initiated", panel):
        return "IndiaMART says contact was initiated but did not expose phone/email"
    if "sold out" in panel:
        return "IndiaMART marked lead sold out before contact was revealed"
    if contact_signal_seen:
        return "contact signal appeared but phone/email text could not be parsed"
    return "contact reveal clicked but phone/email was not visible in page text"


async def extract_buyer_details(
    page: Page,
    block_text: str = "",
    *,
    try_reveal_contact: bool = True,
    stale_panel_text: str = "",
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

    panel_text = await _wait_for_detail_panel_after_click(
        page, block_text, stale_panel_text=stale_panel_text
    )
    panel_matches_block = _panel_matches_block(
        panel_text, block_text, stale_panel_text=stale_panel_text
    )
    if panel_matches_block:
        _apply_panel_text_to_lead(lead, panel_text, block_text)
    elif block_text:
        logger.warning(
            "Detail panel does not match clicked lead; ignoring panel contact text "
            "block_title=%r panel_preview=%r",
            _lead_title_for_click(block_text),
            panel_text[:180],
        )
        lead["contact_status_reason"] = _contact_failure_reason(
            panel_text=panel_text,
            panel_matches_block=False,
            reveal_clicked=False,
            contact_signal_seen=False,
        )
        return sanitize_lead_contacts(lead, block_text, "")

    # Extract better product title from panel text if available
    if panel_matches_block and panel_text and len(panel_text) > 50:
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

    if panel_matches_block:
        for sel, field in selector_patterns:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    val = (await loc.inner_text(timeout=2000)).strip()
                    if val and len(val) < 500:
                        if field == "buyer_phone":
                            digits = re.sub(r"\D", "", val)
                            if len(digits) >= 10 and is_plausible_buyer_phone(
                                val, block_text, panel_text
                            ):
                                lead[field] = digits[-10:] if len(digits) > 10 else digits
                        elif field == "buyer_email":
                            # Validate email format
                            if _EMAIL_RE.match(val) and val.lower() in panel_text.lower():
                                lead[field] = val
                        else:
                            lead[field] = val
            except Exception:
                continue

        dom_contact = await _scrape_contact_from_dom(page)
        if (
            dom_contact.get("buyer_phone")
            and not lead.get("buyer_phone")
            and is_plausible_buyer_phone(
                dom_contact["buyer_phone"], block_text, panel_text
            )
        ):
            lead["buyer_phone"] = dom_contact["buyer_phone"]
        if (
            dom_contact.get("buyer_email")
            and not lead.get("buyer_email")
            and dom_contact["buyer_email"].lower() in panel_text.lower()
        ):
            lead["buyer_email"] = dom_contact["buyer_email"]
        if dom_contact.get("buyer_name") and not lead.get("buyer_name"):
            lead["buyer_name"] = dom_contact["buyer_name"]

    if try_reveal_contact and not lead_has_buyer_contact(lead):
        reveal_clicked = False
        contact_signal_seen = False
        for attempt in range(2):
            clicked_any = await reveal_indiamart_buyer_contact(page)
            reveal_clicked = reveal_clicked or clicked_any
            if clicked_any:
                contact_signal_seen = (
                    await _wait_for_contact_signal(page, timeout_ms=4000)
                    or contact_signal_seen
                )
            # Re-scrape after reveal attempt regardless of click outcome
            panel_text = await _read_detail_panel_text(page)
            panel_matches_block = _panel_matches_block(
                panel_text, block_text, stale_panel_text=stale_panel_text
            )
            if panel_matches_block:
                _apply_panel_text_to_lead(lead, panel_text, block_text)
                dom_contact = await _scrape_contact_from_dom(page)
                if (
                    dom_contact.get("buyer_phone")
                    and not lead.get("buyer_phone")
                    and is_plausible_buyer_phone(
                        dom_contact["buyer_phone"], block_text, panel_text
                    )
                ):
                    lead["buyer_phone"] = dom_contact["buyer_phone"]
                if (
                    dom_contact.get("buyer_email")
                    and not lead.get("buyer_email")
                    and dom_contact["buyer_email"].lower() in panel_text.lower()
                ):
                    lead["buyer_email"] = dom_contact["buyer_email"]
                if dom_contact.get("buyer_name") and not lead.get("buyer_name"):
                    lead["buyer_name"] = dom_contact["buyer_name"]
            else:
                logger.warning(
                    "Contact reveal panel mismatch; keeping lead partial "
                    "block_title=%r panel_preview=%r",
                    _lead_title_for_click(block_text),
                    panel_text[:180],
                )
            if lead_has_buyer_contact(lead):
                break
            if not clicked_any:
                logger.warning("Contact reveal button not found, attempt %d/2", attempt + 1)
                break
        if not lead_has_buyer_contact(lead):
            lead["contact_status_reason"] = _contact_failure_reason(
                panel_text=panel_text,
                panel_matches_block=panel_matches_block,
                reveal_clicked=reveal_clicked,
                contact_signal_seen=contact_signal_seen,
            )

    if panel_matches_block and not lead.get("message") and panel_text:
        for line in panel_text.splitlines():
            line = line.strip()
            if len(line) > 25 and "interested" not in line.lower():
                lead["message"] = line[:500]
                break

    combined = f"{block_text}\n{panel_text if panel_matches_block else ''}"
    if not lead.get("buyer_location"):
        loc = _CITY_STATE_RE.search(combined)
        if loc:
            lead["buyer_location"] = loc.group(0)
    if not lead.get("buyer_address"):
        lead["buyer_address"] = _parse_address_from_text(combined) or lead.get("buyer_location", "")

    # ===== FALLBACK: Regex-based extraction (layout-independent) =====
    # This catches phone/email even if IndiaMART changes their DOM structure
    if panel_matches_block and (not lead.get("buyer_phone") or not lead.get("buyer_email")):
        fallback = await _regex_fallback_extract(page, panel_text)
        if fallback.get("phone") and not lead.get("buyer_phone"):
            lead["buyer_phone"] = fallback["phone"]
        if fallback.get("email") and not lead.get("buyer_email"):
            lead["buyer_email"] = fallback["email"]
        if fallback.get("name") and not lead.get("buyer_name"):
            lead["buyer_name"] = fallback["name"]

    return sanitize_lead_contacts(lead, block_text, panel_text)


async def _regex_fallback_extract(page: Page, text: str | None = None) -> dict[str, str]:
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
        # Prefer caller-provided detail panel text. Full-page fallback can pick stale
        # phone numbers from the shell or an old detail panel.
        if text is None:
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

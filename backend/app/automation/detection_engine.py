from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.core.logging import get_logger
from app.models.keyword import MatchType


@runtime_checkable
class KeywordLike(Protocol):
    id: str
    value: str
    match_type: MatchType
    case_sensitive: bool
    priority: int
    score: float
    cooldown_seconds: int
    is_active: bool
    location_filter: str | None = None

logger = get_logger(__name__)

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

_SEMANTIC_TOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    # Keep keyword matching strict by default. Do not silently broaden
    # "marking" into "engraving"; clicking the wrong IndiaMART lead sends a buyer message.
}
_SEMANTIC_VARIANT_TO_CANONICAL: dict[str, str] = {}
for _canonical, _variants in _SEMANTIC_TOKEN_ALIASES.items():
    for _variant in _variants:
        _SEMANTIC_VARIANT_TO_CANONICAL.setdefault(_variant, _canonical)


def _normalize_semantic_tokens(text: str) -> str:
    out = text.lower()
    for variant, canonical in _SEMANTIC_VARIANT_TO_CANONICAL.items():
        if variant == canonical:
            continue
        out = re.sub(rf"\b{re.escape(variant)}\b", canonical, out)
    # IndiaMART product titles drift between singular/plural forms.
    out = re.sub(
        r"\b(machines|equipments|systems|cleaners|cutters|welders|markers)\b",
        lambda m: m.group(1)[:-1],
        out,
    )
    return out


def _significant_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3]


@dataclass
class DetectionResult:
    matched: bool
    keyword_id: str
    keyword_value: str
    match_type: MatchType
    score: float
    priority: int
    matched_text: str = ""
    context_snippet: str = ""


@dataclass
class CooldownTracker:
    """Tracks per-keyword cooldown to prevent duplicate triggers."""
    _timestamps: dict[str, float] = field(default_factory=dict)

    def is_cooling_down(self, keyword_id: str, cooldown_seconds: int) -> bool:
        last = self._timestamps.get(keyword_id)
        if last is None:
            return False
        return (time.monotonic() - last) < cooldown_seconds

    def record_match(self, keyword_id: str) -> None:
        self._timestamps[keyword_id] = time.monotonic()

    def reset(self, keyword_id: str) -> None:
        self._timestamps.pop(keyword_id, None)


def _keyword_search_terms(value: str, match_type: MatchType) -> list[str]:
    """
    Dashboard often stores several products in one field separated by commas.
    Treat each segment as OR (any one match counts) for non-regex types.
    """
    if match_type == MatchType.regex:
        return [value]
    raw = value.replace(";", ",")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts if len(parts) > 1 else [value.strip()]


class DetectionEngine:
    """
    Evaluates page content against configured keyword rules.
    Supports exact, contains, regex, starts_with, ends_with matching
    with scoring, prioritization, and cooldown logic.
    """

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self._cooldown = CooldownTracker()
        self._compiled_patterns: dict[str, re.Pattern[str]] = {}

    def _get_pattern(self, keyword: Any, term: str) -> re.Pattern[str]:
        cache_key = f"{keyword.id}:{term}"
        if cache_key not in self._compiled_patterns:
            flags = 0 if keyword.case_sensitive else re.IGNORECASE
            if keyword.match_type == MatchType.regex:
                pattern = re.compile(term, flags)
            elif keyword.match_type == MatchType.exact:
                pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", flags)
            elif keyword.match_type == MatchType.contains:
                pattern = re.compile(re.escape(term), flags)
            elif keyword.match_type == MatchType.starts_with:
                pattern = re.compile(r"^" + re.escape(term), flags | re.MULTILINE)
            elif keyword.match_type == MatchType.ends_with:
                pattern = re.compile(re.escape(term) + r"$", flags | re.MULTILINE)
            else:
                pattern = re.compile(re.escape(term), flags)
            self._compiled_patterns[cache_key] = pattern
        return self._compiled_patterns[cache_key]

    def _flexible_contains(
        self, term: str, text: str, case_sensitive: bool
    ) -> re.Match[str] | None:
        """Fallback when exact substring fails (spacing/casing/product title variants)."""
        flags = 0 if case_sensitive else re.IGNORECASE
        t = term if case_sensitive else term.lower()
        body = text if case_sensitive else text.lower()
        words = _significant_words(t)
        if not words:
            return None
        specific = [w for w in words if w not in _GENERIC_MATCH_WORDS]
        allow_semantic_alias = False
        body_norm = _normalize_semantic_tokens(body)

        # First check: exact phrase match. Semantic aliases are allowed only for
        # longer/specific product phrases; short phrases stay literal.
        if t in body or (
            allow_semantic_alias and _normalize_semantic_tokens(t) in body_norm
        ):
            return re.search(re.escape(term), text, flags) or re.search(
                re.escape(_significant_words(term)[0]), text, flags
            )

        # CRITICAL FIX: Require ALL specific words to match, not just some
        # This prevents "laser marking" from matching "laser engraving"
        if specific:
            # Check if ALL specific words are present. For short keywords like
            # "Laser marking machine", do not let the marking/engraving alias
            # broaden the match into unrelated IndiaMART recommendations.
            all_specific_match = all(
                w in body
                or (allow_semantic_alias and _normalize_semantic_tokens(w) in body_norm)
                for w in specific
            )
            if not all_specific_match:
                return None
            # All specific words found - return match for first word
            return re.search(re.escape(specific[0]), text, flags)

        # If no specific words (all generic like "laser marking machine"),
        # require at least 2 words to match to reduce false positives
        if len(words) >= 2:
            hits = [
                w for w in words
                if w in body or _normalize_semantic_tokens(w) in body_norm
            ]
            # Require ALL words to match for generic phrases
            if len(hits) == len(words):
                return re.search(re.escape(words[0]), text, flags)

        return None

    def _flexible_product_match(
        self, term: str, text: str, case_sensitive: bool
    ) -> re.Match[str] | None:
        """Controlled fallback for IndiaMART product titles saved as exact/ends_with."""
        if case_sensitive:
            return None
        words = _significant_words(term)
        if len(words) < 2:
            return None
        specific = [w for w in words if w not in _GENERIC_MATCH_WORDS]
        if not specific:
            return None
        body_norm = _normalize_semantic_tokens(text)
        if not all(_normalize_semantic_tokens(w) in body_norm for w in specific):
            return None
        return re.search(re.escape(specific[0]), text, re.IGNORECASE)

    def evaluate_blocks(self, text: str, keywords: list[Any]) -> list[DetectionResult]:
        """Match each lead row/chunk first — location + product usually sit in the same block."""
        blocks = [b.strip() for b in text.split("---") if b.strip()]
        if len(blocks) <= 1:
            return self.evaluate(text, keywords)
        seen: set[str] = set()
        merged: list[DetectionResult] = []
        for block in blocks:
            for result in self.evaluate(block, keywords):
                if result.keyword_id in seen:
                    continue
                seen.add(result.keyword_id)
                merged.append(result)
        if not merged:
            merged = self.evaluate(text, keywords)
        merged.sort(key=lambda r: (r.priority, r.score), reverse=True)
        return merged

    def evaluate(self, text: str, keywords: list[Any]) -> list[DetectionResult]:
        """
        Evaluates text against all active keywords.
        Returns sorted list of DetectionResults (highest priority first).
        """
        results: list[DetectionResult] = []

        for kw in keywords:
            if not kw.is_active:
                continue
            if self._cooldown.is_cooling_down(kw.id, kw.cooldown_seconds):
                logger.debug(
                    "Keyword on cooldown — skipped",
                    job_id=self.job_id,
                    keyword_id=kw.id,
                    cooldown_seconds=kw.cooldown_seconds,
                )
                continue

            try:
                match = None
                matched_term: str | None = None
                for term in _keyword_search_terms(kw.value, kw.match_type):
                    pattern = self._get_pattern(kw, term)
                    match = pattern.search(text)
                    if (
                        not match
                        and kw.match_type
                        in (MatchType.contains, MatchType.exact, MatchType.ends_with)
                        and not kw.case_sensitive
                    ):
                        if kw.match_type == MatchType.contains:
                            match = self._flexible_contains(term, text, kw.case_sensitive)
                        else:
                            match = self._flexible_product_match(
                                term, text, kw.case_sensitive
                            )
                    if match:
                        matched_term = term
                        break
                if match and matched_term:
                    if kw.location_filter:
                        loc_lower = kw.location_filter.lower()
                        text_lower = text.lower()
                        locations = [
                            location.strip()
                            for location in loc_lower.split(",")
                            if location.strip()
                        ]
                        location_found = any(loc in text_lower for loc in locations)
                        if not location_found:
                            logger.info(
                                "Product matched but location filter did not — lead skipped",
                                job_id=self.job_id,
                                keyword=matched_term,
                                location_filter=kw.location_filter,
                                text_sample=text_lower[:400],
                            )
                            continue
                    snippet = text[max(0, match.start() - 60): match.end() + 60]
                    result = DetectionResult(
                        matched=True,
                        keyword_id=kw.id,
                        keyword_value=matched_term,
                        match_type=kw.match_type,
                        score=kw.score,
                        priority=kw.priority,
                        matched_text=match.group(0),
                        context_snippet=snippet.strip(),
                    )
                    results.append(result)
                    self._cooldown.record_match(kw.id)
                    logger.info(
                        "Keyword matched",
                        job_id=self.job_id,
                        keyword=matched_term,
                        match_type=kw.match_type,
                    )
            except re.error as exc:
                logger.warning(
                    "Invalid regex pattern",
                    job_id=self.job_id,
                    keyword=kw.value,
                    error=str(exc),
                )

        # Sort by priority desc, then score desc
        results.sort(key=lambda r: (r.priority, r.score), reverse=True)
        return results

    def evaluate_element_texts(
        self, elements: list[dict[str, Any]], keywords: list[Any]
    ) -> list[tuple[dict[str, Any], list[DetectionResult]]]:
        """
        Evaluates a list of {'text': str, 'selector': str, ...} element dicts.
        Returns elements that produced at least one match.
        """
        matched_elements: list[tuple[dict[str, Any], list[DetectionResult]]] = []
        for element in elements:
            text = element.get("text", "")
            if not text:
                continue
            results = self.evaluate(text, keywords)
            if results:
                matched_elements.append((element, results))
        return matched_elements

    def invalidate_cache(self) -> None:
        self._compiled_patterns.clear()

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

    def _get_pattern(self, keyword: Any) -> re.Pattern[str]:
        if keyword.id not in self._compiled_patterns:
            flags = 0 if keyword.case_sensitive else re.IGNORECASE
            if keyword.match_type == MatchType.regex:
                pattern = re.compile(keyword.value, flags)
            elif keyword.match_type == MatchType.exact:
                pattern = re.compile(r"(?<!\w)" + re.escape(keyword.value) + r"(?!\w)", flags)
            elif keyword.match_type == MatchType.contains:
                pattern = re.compile(re.escape(keyword.value), flags)
            elif keyword.match_type == MatchType.starts_with:
                pattern = re.compile(r"^" + re.escape(keyword.value), flags | re.MULTILINE)
            elif keyword.match_type == MatchType.ends_with:
                pattern = re.compile(re.escape(keyword.value) + r"$", flags | re.MULTILINE)
            else:
                pattern = re.compile(re.escape(keyword.value), flags)
            self._compiled_patterns[keyword.id] = pattern
        return self._compiled_patterns[keyword.id]

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
                continue

            try:
                pattern = self._get_pattern(kw)
                match = pattern.search(text)
                if match:
                    # ── Location Filter Check ─────────────────────────────────────
                    if kw.location_filter:
                        loc_lower = kw.location_filter.lower()
                        text_lower = text.lower()
                        # Check if any of the comma-separated locations match
                        locations = [l.strip() for l in loc_lower.split(",") if l.strip()]
                        location_found = any(loc in text_lower for loc in locations)
                        if not location_found:
                            # Keyword matched but location didn't match — skip
                            logger.debug(
                                "Keyword matched but location filter failed",
                                job_id=self.job_id,
                                keyword=kw.value,
                                location_filter=kw.location_filter,
                            )
                            continue
                    # ─────────────────────────────────────────────────────────────
                    snippet = text[max(0, match.start() - 60): match.end() + 60]
                    result = DetectionResult(
                        matched=True,
                        keyword_id=kw.id,
                        keyword_value=kw.value,
                        match_type=kw.match_type,
                        score=kw.score,
                        priority=kw.priority,
                        matched_text=match.group(0),
                        context_snippet=snippet.strip(),
                    )
                    results.append(result)
                    self._cooldown.record_match(kw.id)
                    logger.debug(
                        "Keyword matched",
                        job_id=self.job_id,
                        keyword=kw.value,
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

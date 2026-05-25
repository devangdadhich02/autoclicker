from __future__ import annotations

import pytest

from app.automation.detection_engine import DetectionEngine
from app.models.keyword import Keyword, MatchType


def make_keyword(
    kw_id: str,
    value: str,
    match_type: MatchType = MatchType.contains,
    case_sensitive: bool = False,
    priority: int = 5,
    score: float = 1.0,
    cooldown_seconds: int = 0,
) -> Keyword:
    kw = Keyword.__new__(Keyword)
    kw.id = kw_id
    kw.value = value
    kw.match_type = match_type
    kw.case_sensitive = case_sensitive
    kw.priority = priority
    kw.score = score
    kw.cooldown_seconds = cooldown_seconds
    kw.is_active = True
    kw.match_count = 0
    return kw


def test_contains_match():
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw1", "steel pipe")
    results = engine.evaluate("Buyer wants steel pipe 50mm", [kw])
    assert len(results) == 1
    assert results[0].keyword_value == "steel pipe"


def test_contains_no_match():
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw1", "aluminium sheet")
    results = engine.evaluate("Buyer wants steel pipe 50mm", [kw])
    assert len(results) == 0


def test_exact_match():
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw2", "pipe", match_type=MatchType.exact)
    results = engine.evaluate("steel pipe 50mm", [kw])
    assert len(results) == 1


def test_regex_match():
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw3", r"steel\s+pipe", match_type=MatchType.regex)
    results = engine.evaluate("Buyer wants steel    pipe 50mm", [kw])
    assert len(results) == 1


def test_case_sensitive_no_match():
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw4", "Steel Pipe", case_sensitive=True)
    results = engine.evaluate("buyer wants steel pipe", [kw])
    assert len(results) == 0


def test_case_insensitive_match():
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw4", "Steel Pipe", case_sensitive=False)
    results = engine.evaluate("buyer wants steel pipe", [kw])
    assert len(results) == 1


def test_cooldown_prevents_double_trigger():
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw5", "inquiry", cooldown_seconds=999)
    r1 = engine.evaluate("new inquiry received", [kw])
    r2 = engine.evaluate("new inquiry received", [kw])
    assert len(r1) == 1
    assert len(r2) == 0  # Cooldown blocks second match


def test_priority_ordering():
    engine = DetectionEngine("test-job")
    kw_low = make_keyword("kw6", "pipe", priority=1, cooldown_seconds=0)
    kw_high = make_keyword("kw7", "steel", priority=9, cooldown_seconds=0)
    results = engine.evaluate("steel pipe inquiry", [kw_low, kw_high])
    assert len(results) == 2
    assert results[0].priority == 9


def test_inactive_keyword_skipped():
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw8", "pipe")
    kw.is_active = False
    results = engine.evaluate("buyer wants pipe", [kw])
    assert len(results) == 0


def test_starts_with_match():
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw9", "New inquiry", match_type=MatchType.starts_with)
    results = engine.evaluate("New inquiry from Delhi buyer", [kw])
    assert len(results) == 1


def test_invalid_regex_does_not_crash():
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw10", "[invalid(regex", match_type=MatchType.regex)
    results = engine.evaluate("some text [invalid(regex", [kw])
    assert results == []

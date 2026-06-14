from __future__ import annotations

import types

from app.automation.detection_engine import DetectionEngine
from app.models.keyword import MatchType


def make_keyword(
    kw_id: str,
    value: str,
    match_type: MatchType = MatchType.contains,
    case_sensitive: bool = False,
    priority: int = 5,
    score: float = 1.0,
    cooldown_seconds: int = 0,
    location_filter: str | None = None,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=kw_id,
        value=value,
        match_type=match_type,
        case_sensitive=case_sensitive,
        priority=priority,
        score=score,
        cooldown_seconds=cooldown_seconds,
        location_filter=location_filter,
        is_active=True,
        match_count=0,
    )


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


def test_contains_semantic_marking_matches_engraving():
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw-semantic-1", "fiber laser metal marking machine")
    text = "Buyer needs fiber laser metal engraving machine for steel parts"
    results = engine.evaluate(text, [kw])
    assert len(results) == 1


def test_short_marking_keyword_matches_indiamart_engraving_machine_alias():
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw-short-marking", "Laser marking machine")
    text = "Laser Engraving Machines\nCr-laser Falcon Engraver-20w\nMumbai, Maharashtra"
    results = engine.evaluate(text, [kw])
    assert len(results) == 1


def test_exact_match():
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw2", "pipe", match_type=MatchType.exact)
    results = engine.evaluate("steel pipe 50mm", [kw])
    assert len(results) == 1


def test_exact_product_keyword_tolerates_plural_feed_title():
    engine = DetectionEngine("test-job")
    kw = make_keyword(
        "kw-product-exact", "Laser welding machine", match_type=MatchType.exact
    )
    text = "Laser Welding Machines\n4 mins ago\nKheda, Gujarat\nSold Out!"
    results = engine.evaluate(text, [kw])
    assert len(results) == 1


def test_exact_product_keyword_does_not_match_different_laser_machine():
    engine = DetectionEngine("test-job")
    kw = make_keyword(
        "kw-product-exact-2", "Laser welding machine", match_type=MatchType.exact
    )
    text = "Non Metal Laser Cutting Machine\n19 mins ago\nKolkata, West Bengal"
    results = engine.evaluate(text, [kw])
    assert results == []


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


def test_location_filter_match():
    """Keyword matches and location filter matches."""
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw11", "steel pipe", location_filter="Bangalore")
    results = engine.evaluate("Buyer from Bangalore wants steel pipe", [kw])
    assert len(results) == 1


def test_location_filter_no_match():
    """Keyword matches but location filter does not match."""
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw12", "steel pipe", location_filter="Bangalore")
    results = engine.evaluate("Buyer from Delhi wants steel pipe", [kw])
    assert len(results) == 0


def test_location_filter_multiple_locations():
    """Location filter with multiple comma-separated locations."""
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw13", "copper wire", location_filter="Bangalore, Delhi, Mumbai")
    results = engine.evaluate("Buyer from Delhi wants copper wire", [kw])
    assert len(results) == 1


def test_location_filter_not_set():
    """When location_filter is None, keyword should match regardless of location."""
    engine = DetectionEngine("test-job")
    kw = make_keyword("kw14", "pvc pipe", location_filter=None)
    results = engine.evaluate("Buyer from Chennai wants pvc pipe", [kw])
    assert len(results) == 1


def test_hyderabad_marking_machine_matches_when_telangana_allowed():
    engine = DetectionEngine("test-job")
    kw = make_keyword(
        "kw-hyd-marking",
        "Laser marking machine",
        match_type=MatchType.contains,
        location_filter="Telangana, Hyderabad",
    )
    text = (
        "Laser Marking Machine\n"
        "Hyderabad, Telangana\n"
        "Just Now\n"
        "Category: Laser Marking Machine\n"
        "Power : 60 W\n"
        "Requirement Type : Business Use\n"
        "I am Interested"
    )
    results = engine.evaluate(text, [kw])
    assert len(results) == 1


def test_hyderabad_marking_machine_matches_without_location_filter():
    engine = DetectionEngine("test-job")
    kw = make_keyword(
        "kw-hyd-marking-no-filter",
        "Laser marking machine",
        match_type=MatchType.contains,
        location_filter=None,
    )
    text = (
        "Laser Marking Machine\n"
        "Hyderabad, Telangana\n"
        "Just Now\n"
        "Category: Laser Marking Machine\n"
        "Power : 60 W\n"
        "Requirement Type : Business Use\n"
        "I am Interested"
    )
    results = engine.evaluate(text, [kw])
    assert len(results) == 1

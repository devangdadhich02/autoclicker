import types

import pytest

import app.automation.indiamart_leads as indiamart_leads
from app.automation.detection_engine import DetectionEngine
from app.automation.indiamart_leads import (
    _apply_panel_text_to_lead,
    _blocks_from_body_text,
    _lead_title_for_click,
    _panel_matches_block,
    _parse_address_from_text,
    _split_candidate_text_into_cards,
    extract_buyer_details,
    is_buyer_inquiry_block,
    is_plausible_buyer_phone,
    is_weak_match_context,
    lead_identity_matches,
    lead_fingerprint,
    lead_has_buyer_contact,
    lead_match_text,
    lead_record_is_complete,
    sanitize_buyer_name,
    sanitize_lead_contacts,
    sanitize_product_title,
)
from app.automation.indiamart_page import (
    _is_non_recent_buy_leads_url,
    is_indiamart_logged_out_body,
    is_indiamart_marketing_landing,
)
from app.automation.job_runner import _is_non_recent_indiamart_feed
from app.models.keyword import MatchType


def make_keyword(value: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=value,
        value=value,
        match_type=MatchType.contains,
        case_sensitive=False,
        priority=5,
        score=1.0,
        cooldown_seconds=0,
        location_filter=None,
        is_active=True,
        match_count=0,
    )


def test_rejects_parts_and_spares_nav():
    assert not is_buyer_inquiry_block("Parts & Spares")
    assert is_weak_match_context("Parts & Spares", "metal laser cutting machine")


def test_accepts_realistic_buyer_row():
    text = (
        "Metal Laser Marking Machine\n"
        "New Delhi, Delhi · 46 mins ago\n"
        "Requirement Type: Business Use\n"
        "I am Interested"
    )
    assert is_buyer_inquiry_block(text)


def test_client_metal_laser_marking_machine_matches_keyword():
    block = (
        "Metal Laser Marking Machine\n"
        "Agra, Uttar Pradesh\n"
        "10 mins ago\n"
        "Phone Email WhatsApp GST\n"
        "Category: Metal Laser Marking Machine\n"
        "Buyer Searched for Metal Laser Marking Machine\n"
        "Laser Power : 30 W\n"
        "Marking Area : 300 x 300 mm\n"
        "Requirement Type : Business Use\n"
        "Sold Out!\n"
        "I am Interested\n"
        "Buyer Info"
    )
    assert is_buyer_inquiry_block(block)
    results = DetectionEngine("test-job").evaluate(
        lead_match_text(block), [make_keyword("Laser marking machine")]
    )
    assert len(results) == 1


def test_client_laser_marking_machine_matches_keyword():
    block = (
        "Laser Marking Machine\n"
        "Sonipat, Haryana\n"
        "2 hrs ago\n"
        "Phone\n"
        "Category: Laser Marking Machine\n"
        "Power : 30 W\n"
        "Requirement Type : Business Use\n"
        "Sold Out!\n"
        "I am Interested"
    )
    assert is_buyer_inquiry_block(block)
    results = DetectionEngine("test-job").evaluate(
        lead_match_text(block), [make_keyword("Laser marking machine")]
    )
    assert len(results) == 1


def test_buyer_searched_for_overrides_indiamart_recommended_title():
    block = (
        "Laser Marking Machine\n"
        "Gurugram, Haryana\n"
        "2 hrs ago\n"
        "Phone WhatsApp\n"
        "Category: Laser Marking Machine\n"
        "Buyer Searched for sport t shirt\n"
        "Power : 50 W\n"
        "Marking Area : 100x100 mm\n"
        "Requirement Type : Business Use\n"
        "Sold Out!\n"
        "I am Interested"
    )
    match_text = lead_match_text(block)
    assert "sport t shirt" in match_text
    assert "Laser Marking Machine" not in match_text
    results = DetectionEngine("test-job").evaluate(
        match_text, [make_keyword("Laser marking machine")]
    )
    assert results == []


def test_buyer_searched_for_matching_product_still_matches_keyword():
    block = (
        "Laser Marking System\n"
        "Jhunjhunu, Rajasthan\n"
        "11 mins ago\n"
        "Phone Email WhatsApp GST\n"
        "Category: Laser Marking System\n"
        "Buyer Searched for Laser Marking System\n"
        "Requirement Type : Business Use\n"
        "Sold Out!\n"
        "I am Interested"
    )
    results = DetectionEngine("test-job").evaluate(
        lead_match_text(block), [make_keyword("Laser marking machine")]
    )
    assert len(results) == 1


def test_keyword_match_ignores_related_product_noise():
    block = (
        "Laser Marking Machine\n"
        "Sonipat, Haryana\n"
        "2 hrs ago\n"
        "Category: Laser Marking Machine\n"
        "Requirement Type : Business Use\n"
        "Sold Out!\n"
        "I am Interested\n"
        "Buyer Info\n"
        "Gold Testing Machine\n"
        "Double Holder Machine\n"
        "Wall Mounted Cleaning Stations"
    )
    match_text = lead_match_text(block)
    assert "Gold Testing Machine" not in match_text
    assert "Double Holder Machine" not in match_text
    results = DetectionEngine("test-job").evaluate(
        match_text, [make_keyword("Gold Testing Machine")]
    )
    assert results == []


def test_lead_complete_with_phone():
    assert lead_record_is_complete(
        "Metal Laser Marking Machine\nNew Delhi · 10 mins ago",
        {"buyer_phone": "9876543210"},
    )


def test_lead_has_contact_requires_phone():
    assert lead_has_buyer_contact({"buyer_phone": "9876543210"})
    assert not lead_has_buyer_contact({"buyer_name": "Raj", "buyer_location": "Pune"})


def test_lead_fingerprint_ignores_time_ago():
    block = (
        "Laser Cleaning Machine Pune , Maharashtra 2 hrs ago "
        "Oil & Stain Cleaner > Laser Cleaning Machine"
    )
    block2 = block.replace("2 hrs", "3 hrs")
    assert lead_fingerprint(block, {}) == lead_fingerprint(block2, {})


def test_lead_fingerprint_uses_phone_when_present():
    block = "Laser Cleaning Machine\nPune, Maharashtra\n2 hrs ago"
    fp = lead_fingerprint(block, {"buyer_phone": "9876543210"})
    assert fp == "ph:9876543210|laser cleaning machine|pune, maharashtra"


def test_lead_identity_requires_same_product_and_city_before_click():
    expected = (
        "Laser Marking Machine\n"
        "Saharanpur, Uttar Pradesh\n"
        "23 hrs ago\n"
        "Category: Laser Marking Machine\n"
        "I am Interested"
    )
    same = expected.replace("23 hrs ago", "24 hrs ago")
    wrong_product = expected.replace("Laser Marking Machine", "Laser Engraving Machine")
    wrong_city = expected.replace("Saharanpur, Uttar Pradesh", "Moradabad, Uttar Pradesh")
    assert lead_identity_matches(same, expected)
    assert not lead_identity_matches(wrong_product, expected)
    assert not lead_identity_matches(wrong_city, expected)


def test_lead_identity_accepts_location_first_category_variant():
    expected = (
        "Anantapur\n"
        ",\n"
        "Andhra Pradesh\n"
        "19 hrs ago\n"
        "Laser Marking Machine\n"
        ">\n"
        "UV Laser Marking Machine\n"
        "Power\n"
        ":\n"
        "5 W\n"
        "Requirement Type\n"
        ":\n"
        "Business Use"
    )
    current = (
        "Laser Marking Machine\n"
        "Anantapur, Andhra Pradesh\n"
        "20 hrs ago\n"
        "Category: Laser Marking Machine\n"
        "Power : 5 W\n"
        "I am Interested"
    )
    assert lead_identity_matches(current, expected)


def test_lead_identity_rejects_conflicting_explicit_subtype_same_city():
    expected = (
        "Anantapur\n"
        ",\n"
        "Andhra Pradesh\n"
        "19 hrs ago\n"
        "Laser Marking Machine\n"
        ">\n"
        "UV Laser Marking Machine"
    )
    wrong_subtype = (
        "Fiber Laser Marking Machine\n"
        "Anantapur, Andhra Pradesh\n"
        "19 hrs ago\n"
        "Category: Fiber Laser Marking Machine\n"
        "I am Interested"
    )
    assert not lead_identity_matches(wrong_subtype, expected)


def test_same_phone_different_product_gets_distinct_fingerprint():
    phone = {"buyer_phone": "9876543210"}
    welding = "Laser Welding Machine\nKheda, Gujarat\n4 mins ago"
    cleaning = "Laser Cleaning Machine\nKheda, Gujarat\n5 mins ago"
    assert lead_fingerprint(welding, phone) != lead_fingerprint(cleaning, phone)


def test_lead_complete_with_time_and_location():
    block = "Metal Laser Marking Machine\nNew Delhi, Delhi · 46 mins ago\nBusiness Use"
    assert lead_record_is_complete(
        block,
        {
            "product_title": "Metal Laser Marking Machine",
            "buyer_address": "New Delhi, Delhi",
            "buyer_location": "New Delhi",
        },
    )


def test_accepts_client_laser_welding_sold_out_row():
    """Matches IndiaMART Recent feed row from client screenshot (Kheda, Sold Out)."""
    text = (
        "Laser Welding Machine\n"
        "4 mins ago\n"
        "Kheda, Gujarat\n"
        "Sold Out!\n"
        "I am Interested"
    )
    assert is_buyer_inquiry_block(text)


def test_client_led_laser_marking_with_conveyor_matches_keyword():
    block = (
        "LED Laser Marking Machine\n"
        "Moradabad, Uttar Pradesh\n"
        "13 hrs ago\n"
        "Phone Email WhatsApp\n"
        "Category: Laser Marking Machine\n"
        "Buyer Searched for laser marking machine with conveyor\n"
        "Power : 30 W\n"
        "Marking Area : 200x200 mm\n"
        "Requirement Type : Business Use\n"
        "Sold Out!\n"
        "I am Interested"
    )
    assert is_buyer_inquiry_block(block)
    results = DetectionEngine("test-job").evaluate(
        lead_match_text(block), [make_keyword("Laser marking machine")]
    )
    assert len(results) == 1


def test_client_mini_fiber_marking_body_matches_marker_keyword():
    block = (
        "Mini Fiber Laser Marking Machine Body\n"
        "Firozabad, Uttar Pradesh\n"
        "1 hr ago\n"
        "Phone WhatsApp Address\n"
        "Category: Fiber Laser Marker\n"
        "Output Power : 30 W\n"
        "Requirement Type : Business Use\n"
        "Sold Out!\n"
        "I am Interested"
    )
    assert is_buyer_inquiry_block(block)
    results = DetectionEngine("test-job").evaluate(
        lead_match_text(block), [make_keyword("Fiber laser marker")]
    )
    assert len(results) == 1


def test_client_uv_marking_machine_matches_marking_keyword():
    block = (
        "Dual-head UV Laser Marking Machine 5watt\n"
        "Moradabad, Uttar Pradesh\n"
        "15 hrs ago\n"
        "Phone Email WhatsApp Business Address\n"
        "Category: UV Laser Marking Machine\n"
        "Marking Area : 100x100 mm\n"
        "Material : Glass / Ceramics\n"
        "Buyer Filled Details : 100w, 200x200 mm, Metals, Paper / Wood\n"
        "Requirement Type : Business Use\n"
        "Sold Out!\n"
        "I am Interested"
    )
    assert is_buyer_inquiry_block(block)
    results = DetectionEngine("test-job").evaluate(
        lead_match_text(block), [make_keyword("Laser marking machine")]
    )
    assert len(results) == 1


def test_buyer_filled_details_do_not_trigger_unrelated_keyword():
    block = (
        "Laser Marking Machine\n"
        "Saharanpur, Uttar Pradesh\n"
        "23 hrs ago\n"
        "Phone Email WhatsApp Business\n"
        "Category: Laser Marking Machine\n"
        "Power : 80 W\n"
        "Marking Area : 200x200 mm\n"
        "Buyer Filled Details : Buyer also mentioned a requirement for an "
        "automatic double cutter machine.\n"
        "Requirement Type : Business Use\n"
        "Sold Out!\n"
        "I am Interested"
    )
    match_text = lead_match_text(block)
    assert "double cutter" not in match_text.lower()
    assert "marking area" not in match_text.lower()
    assert (
        DetectionEngine("test-job").evaluate(
            match_text, [make_keyword("automatic double cutter machine")]
        )
        == []
    )
    assert len(
        DetectionEngine("test-job").evaluate(
            match_text, [make_keyword("Laser marking machine")]
        )
    ) == 1


def test_client_log_engraver_rows_do_not_match_marking_keywords():
    keywords = [
        make_keyword("Laser marking machine"),
        make_keyword("Laser welding machine"),
        make_keyword("Laser cleaning machine"),
        make_keyword("Fiber laser marker"),
    ]
    rows = (
        "Twotrees Tts-55 Pro Diode Laser Engraver\n"
        "Bengaluru, Karnataka\n"
        "3 hrs ago\n"
        "Engraving Machines > Laser Engraving Machines\n"
        "Laser Power : 10 W\n"
        "I am Interested\n"
        "CO2 Laser Engraving Machine\n"
        "Shivamogga, Karnataka\n"
        "54 mins ago\n"
        "Engraving Machines > Co2 Laser Engraving Machine\n"
        "Laser Power : 60 W\n"
        "I am Interested"
    )
    blocks = _blocks_from_body_text(rows)
    assert len(blocks) == 2
    for block in blocks:
        assert (
            DetectionEngine("test-job").evaluate(lead_match_text(block.text), keywords)
            == []
        )


def test_accepts_mumbai_marking_machine_row():
    text = (
        "30W Laser Marking Machine\n"
        "1 hr ago\n"
        "Mumbai, Maharashtra\n"
        "Sold Out!\n"
        "I am Interested"
    )
    assert is_buyer_inquiry_block(text)


def test_body_split_finds_laser_leads():
    body = (
        "Recent\nLaser Welding Machine\n4 mins ago\nKheda, Gujarat\nSold Out!\n"
        "I am Interested\n30W Laser Marking Machine\n1 hr ago\nMumbai, Maharashtra\n"
        "Sold Out!\nI am Interested"
    )
    blocks = _blocks_from_body_text(body)
    assert len(blocks) >= 2
    assert any("Laser Welding" in b.text for b in blocks)


def test_body_split_finds_jammu_kashmir_lead_with_section_header():
    body = (
        "Recommended\nLaser Welding Machine\nNo relevant BuyLeads found\n"
        "Showing other leads you may like\n"
        "1.5 kW Fiber Laser Welding Machine\n"
        "Srinagar, Jammu & Kashmir 16 mins ago\n"
        "Phone WhatsApp\n"
        "Category: Laser Welding Machine\n"
        "Laser Power : 1.5 kW\n"
        "Requirement Type : Business Use"
    )
    blocks = _blocks_from_body_text(body)
    assert len(blocks) == 1
    assert "1.5 kW Fiber Laser Welding Machine" in blocks[0].text
    assert "No relevant BuyLeads found" not in blocks[0].text
    assert _parse_address_from_text(blocks[0].text) == "Srinagar, Jammu & Kashmir"
    assert is_buyer_inquiry_block(blocks[0].text)


def test_raw_wrapper_split_keeps_irrelevant_bamboo_card_separate():
    raw = (
        "Laser Welding Machine\nCoorg, Karnataka\n3 mins ago\n"
        "Category: Laser Welding Machine\nI am Interested\n"
        "Sumit, Indore\n6 mins ago\n"
        "Bamboo Laser Cutting & Engraving Machine, Cooling System\n"
        "I am Interested"
    )
    blocks = _split_candidate_text_into_cards(raw)
    assert len(blocks) == 2
    bamboo = next(b for b in blocks if "Bamboo" in b.text)
    results = DetectionEngine("test-job").evaluate(
        lead_match_text(bamboo.text), [make_keyword("Laser welding machine")]
    )
    assert results == []


def test_detects_logged_out_seller_landing():
    body = (
        "IndiaMART\nBuy Leads\nHelp\nHow to Register\nSuccess Stories\n"
        "What can you sell\nSell for free on India's largest online B2B marketplace\n"
        "IndiaMART Advantage"
    )
    assert is_indiamart_logged_out_body(body)


def test_marketing_landing_detected():
    body = (
        "IndiaMART\nSign In\nSell on IndiaMART\nHow to Register\n"
        "Success Stories\nWhat can you sell"
    )
    assert is_indiamart_marketing_landing(body)


def test_rejects_indiamart_similar_leads_url_as_recent_feed():
    similar_url = (
        "https://seller.indiamart.com/bltxn/buyersearch/?"
        "ss=CO2+Laser+Cutting+Machine&screen=view_similar_leads"
    )
    relevant_url = "https://seller.indiamart.com/bltxn/?pref=relevant"
    recent_url = "https://seller.indiamart.com/bltxn/?pref=recent"

    assert _is_non_recent_buy_leads_url(similar_url)
    assert _is_non_recent_indiamart_feed(similar_url)
    assert _is_non_recent_buy_leads_url(relevant_url)
    assert _is_non_recent_indiamart_feed(relevant_url)
    assert not _is_non_recent_buy_leads_url(recent_url)
    assert not _is_non_recent_indiamart_feed(recent_url)


def test_page_helper_rejects_indiamart_similar_leads_url_as_recent_feed():
    assert _is_non_recent_buy_leads_url(
        "https://seller.indiamart.com/bltxn/buyersearch/?"
        "ss=CO2+Laser+Cutting+Machine&screen=view_similar_leads"
    )
    assert _is_non_recent_buy_leads_url(
        "https://seller.indiamart.com/bltxn/?pref=relevant"
    )
    assert not _is_non_recent_buy_leads_url(
        "https://seller.indiamart.com/bltxn/?pref=recent"
    )


def test_rejects_stale_detail_panel_for_different_lead_title():
    block = (
        "Laser Marking System\n"
        "Jhunjhunu, Rajasthan\n"
        "11 mins ago\n"
        "Category: Laser Marking System\n"
        "Requirement Type: Business Use"
    )
    stale_panel = (
        "Co2 Laser Engraving Machine\n"
        "Saudi Arabia, Engraving Machines\n"
        "Phone 9313310116\n"
        "NC-Scriber/Lettering Machine and Drafting Aid"
    )
    assert not _panel_matches_block(stale_panel, block)
    assert not _panel_matches_block(
        stale_panel, block, stale_panel_text=stale_panel
    )


def test_accepts_matching_detail_panel_for_clicked_lead_title():
    block = (
        "Laser Marking Machine\n"
        "Gurugram, Haryana\n"
        "2 hrs ago\n"
        "Category: Laser Marking Machine\n"
        "Power: 50 W"
    )
    panel = "Laser Marking Machine\nGurugram, Haryana\nPhone 9876543210"
    assert _panel_matches_block(panel, block)


def test_rejects_unchanged_stale_panel_after_click():
    block = (
        "Laser Marking Machine\n"
        "Gurugram, Haryana\n"
        "2 hrs ago\n"
        "Category: Laser Marking Machine\n"
        "Power: 50 W"
    )
    stale_panel = "Laser Marking Machine\nGurugram, Haryana\nPhone 9876543210"
    assert not _panel_matches_block(
        stale_panel, block, stale_panel_text=stale_panel
    )


def test_rejects_same_title_panel_for_different_city():
    block = (
        "Laser Marking Machine\n"
        "Gurugram, Haryana\n"
        "2 hrs ago\n"
        "Category: Laser Marking Machine\n"
        "Power: 50 W"
    )
    wrong_panel = "Laser Marking Machine\nMoradabad, Uttar Pradesh\nPhone 9876543210"
    assert not _panel_matches_block(wrong_panel, block)


@pytest.mark.asyncio
async def test_extract_stops_before_reveal_when_detail_panel_mismatches(monkeypatch):
    block = (
        "UV Laser Marking Machine\n"
        "Anantapur, Andhra Pradesh\n"
        "1 hr ago\n"
        "Category: UV Laser Marking Machine"
    )
    stale_shell = (
        "IndiaMART\nBuy Leads\nLead Manager\nContact Buyer\n"
        "NC-Scriber/Lettering Machine and Drafting Aid"
    )
    reveal_called = False

    async def fake_wait_for_detail_panel_after_click(*args, **kwargs):
        return stale_shell

    async def fake_reveal_contact(*args, **kwargs):
        nonlocal reveal_called
        reveal_called = True
        return True

    monkeypatch.setattr(
        indiamart_leads,
        "_wait_for_detail_panel_after_click",
        fake_wait_for_detail_panel_after_click,
    )
    monkeypatch.setattr(
        indiamart_leads,
        "reveal_indiamart_buyer_contact",
        fake_reveal_contact,
    )

    lead = await extract_buyer_details(object(), block)
    assert not reveal_called
    assert lead["contact_status_reason"] == "detail panel did not match clicked lead"
    assert "buyer_phone" not in lead


def test_accepts_fresh_contact_popup_without_product_title():
    block = (
        "CO2 Laser Cutting Machine\n"
        "Ludhiana, Punjab\n"
        "42 mins ago\n"
        "Category: CO2 Laser Cutting Machine\n"
        "Requirement Type: Business Use"
    )
    stale = "Lead Manager\nRecent Buy Leads\nCO2 Laser Cutting Machine"
    panel = (
        "Jahir\n"
        "arjh2251@gmail.com\n"
        "Member Since :\n"
        "+91-9345441416\n"
        "Hi Jahir,\n"
        "Greetings from Laser Lab (India) Private Limited."
    )
    assert _panel_matches_block(panel, block, stale_panel_text=stale)


def test_rejects_changed_stale_contact_card_without_buyer_greeting():
    block = (
        "Fiber Laser Cutting Machine\n"
        "Patna, Bihar\n"
        "57 mins ago\n"
        "Category: Fiber Laser Cutting Machine\n"
        "Requirement Type: Business Use"
    )
    stale = "Lead Manager\nRecent Buy Leads\nFiber Laser Cutting Machine"
    old_panel = (
        "Co2 Laser Engraving Machine\n"
        "Saudi Arabia, Engraving Machines\n"
        "Phone 9313310116\n"
        "NC-Scriber/Lettering Machine and Drafting Aid"
    )
    assert not _panel_matches_block(old_panel, block, stale_panel_text=stale)


def test_screenshot_style_contact_popup_extracts_buyer_details():
    block = (
        "CO2 Laser Cutting Machine\n"
        "Ludhiana, Punjab\n"
        "42 mins ago\n"
        "Category: CO2 Laser Cutting Machine\n"
        "Requirement Type: Business Use"
    )
    panel = (
        "Jahir\n"
        "arjh2251@gmail.com\n"
        "Member Since :\n"
        "+91-9345441416\n"
        "Hi Jahir,\n"
        "Greetings from Laser Lab (India) Private Limited.\n"
        "call us at 07942672646"
    )
    lead: dict[str, str] = {}
    _apply_panel_text_to_lead(lead, panel, block)
    lead = sanitize_lead_contacts(lead, block, panel)
    assert lead["buyer_name"] == "Jahir"
    assert lead["buyer_email"] == "arjh2251@gmail.com"
    assert lead["buyer_phone"] == "+919345441416"


def test_accepts_just_now_feed_row():
    text = (
        "Laser Welding Machine\n"
        "Chennai, Tamil Nadu\n"
        "Just Now\n"
        "Category: Laser Welding Machine\n"
        "I am Interested"
    )
    assert is_buyer_inquiry_block(text)


def test_accepts_hyderabad_marking_machine_just_now_card():
    text = (
        "Laser Marking Machine\n"
        "Hyderabad, Telangana\n"
        "Just Now\n"
        "Phone Email\n"
        "Category: Laser Marking Machine\n"
        "for stone craving and other materials\n"
        "Power : 60 W\n"
        "Marking Area : 200x200 mm\n"
        "Laser Source Brand : Raycus\n"
        "Requirement Type : Business Use\n"
        "Sold Out!\n"
        "I am Interested"
    )
    assert is_buyer_inquiry_block(text)
    assert _parse_address_from_text(text) == "Hyderabad, Telangana"


def test_rejects_nav_support_phone():
    assert not is_plausible_buyer_phone(
        "9716054356",
        "Laser Marking Machine\nJaipur, Rajasthan\n3 mins ago",
        "Buy Leads\nLead Manager\nTools\nSettings",
    )


def test_sanitize_buyer_name_strips_nav():
    assert sanitize_buyer_name("Tools\nSettings\nTally on") == ""
    assert sanitize_buyer_name("IndiaMART") == ""
    assert sanitize_buyer_name("Rajesh Kumar") == "Rajesh Kumar"


def test_sanitize_lead_removes_bad_phone():
    lead = sanitize_lead_contacts(
        {"buyer_phone": "9716054356", "buyer_name": "Raj"},
        "Laser Marking\nDelhi\n5 mins ago",
        "Lead Manager\nBuy Leads",
    )
    assert "buyer_phone" not in lead


def test_sanitize_lead_replaces_nav_product_and_name_from_feed_block():
    block = (
        "Laser Welding Machine\n"
        "Ahmedabad, Gujarat\n"
        "2 hrs ago\n"
        "Category: Laser Welding Machine\n"
        "I am Interested"
    )
    lead = sanitize_lead_contacts(
        {
            "buyer_phone": "9313310116",
            "buyer_name": "IndiaMART",
            "product_title": "Buy With IndiaMART",
        },
        block,
        "IndiaMART\nBuy With IndiaMART\nLead Manager\nContact Buyer",
    )
    assert lead["buyer_phone"] == "9313310116"
    assert lead["product_title"] == "Laser Welding Machine"
    assert "buyer_name" not in lead


def test_sanitize_product_title_rejects_nav_title():
    block = "Laser Marking Machine\nHyderabad, Telangana\nJust Now"
    assert sanitize_product_title("Buy With IndiaMART", block) == "Laser Marking Machine"


def test_header_sign_in_not_logged_out_when_seller_ui_present():
    body = (
        "Sign In\nSell on IndiaMART\nBuy Leads\nLead Manager\nRecent Buy Leads\n"
        "Manage Products\nSubscription"
    )
    assert not is_indiamart_logged_out_body(body)
    assert not is_indiamart_logged_out_body(
        "Laser Welding Machine\n4 mins ago\nKheda, Gujarat\nSold Out!"
    )


def test_location_first_row_extracts_product_not_state():
    block = (
        "Kolkata\n"
        ",\n"
        "West Bengal\n"
        "19 mins ago\n"
        "Laser Cutting Machines\n"
        ">\n"
        "Non Metal Laser Cutting Machine\n"
        "Working Area\n"
        ":\n"
        "A4 size\n"
        "Laser Power\n"
        ":\n"
        "50 W\n"
        "Probable Requirement Type\n"
        ":\n"
        "Business Use"
    )
    assert _lead_title_for_click(block) == "Non Metal Laser Cutting Machine"
    assert _parse_address_from_text(block) == "Kolkata, West Bengal"


def test_rejects_location_time_only_fragment_from_recent_feed():
    block = "Ghaziabad\n,\nUttar Pradesh\n44 mins ago"
    assert not is_buyer_inquiry_block(block)
    assert _lead_title_for_click(block) == ""


def test_accepts_location_first_full_recent_card():
    block = (
        "Ghaziabad\n"
        ",\n"
        "Uttar Pradesh\n"
        "44 mins ago\n"
        "Laser Rust Cleaning Machine\n"
        ">\n"
        "Laser Rust Removal Machine\n"
        "Probable Requirement Type\n"
        ":\n"
        "Business Use\n"
        "I am Interested"
    )
    assert is_buyer_inquiry_block(block)
    assert _lead_title_for_click(block) == "Laser Rust Removal Machine"
    assert _parse_address_from_text(block) == "Ghaziabad, Uttar Pradesh"

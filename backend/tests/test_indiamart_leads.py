from app.automation.indiamart_leads import (
    _blocks_from_body_text,
    _lead_title_for_click,
    _parse_address_from_text,
    is_buyer_inquiry_block,
    is_plausible_buyer_phone,
    is_weak_match_context,
    lead_fingerprint,
    lead_has_buyer_contact,
    lead_record_is_complete,
    sanitize_buyer_name,
    sanitize_lead_contacts,
    sanitize_product_title,
)
from app.automation.indiamart_page import (
    is_indiamart_logged_out_body,
    is_indiamart_marketing_landing,
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
    block = "Laser Cleaning Machine Pune"
    fp = lead_fingerprint(block, {"buyer_phone": "9876543210"})
    assert fp == "ph:9876543210"


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

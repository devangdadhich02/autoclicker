from app.automation.indiamart_leads import (
    _blocks_from_body_text,
    is_buyer_inquiry_block,
    is_weak_match_context,
    lead_record_is_complete,
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


def test_header_sign_in_not_logged_out_when_seller_ui_present():
    body = (
        "Sign In\nSell on IndiaMART\nBuy Leads\nLead Manager\nRecent Buy Leads\n"
        "Manage Products\nSubscription"
    )
    assert not is_indiamart_logged_out_body(body)
    assert not is_indiamart_logged_out_body(
        "Laser Welding Machine\n4 mins ago\nKheda, Gujarat\nSold Out!"
    )

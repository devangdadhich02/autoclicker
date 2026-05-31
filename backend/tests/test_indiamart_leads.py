from app.automation.indiamart_leads import (
    is_buyer_inquiry_block,
    is_weak_match_context,
    lead_record_is_complete,
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

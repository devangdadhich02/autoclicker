from app.core.config import settings
from app.services.lead_store import append_lead_row, load_seen_lead_fingerprints


def test_partial_lead_does_not_block_future_contact_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "LEADS_CSV_DIR", tmp_path)
    block = "Laser Welding Machine\n4 mins ago\nKheda, Gujarat\nSold Out!"

    append_lead_row(
        job_id="job-12345678",
        job_name="IndiaMART",
        event_type="lead_extracted",
        details={
            "product_title": "Laser Welding Machine",
            "context_snippet": block,
            "lead_fingerprint": "partial:pk:laser welding machine|kheda, gujarat",
            "contact_revealed": False,
        },
        context_snippet=block,
    )

    seen = load_seen_lead_fingerprints("job-12345678", "IndiaMART")

    assert "partial:pk:laser welding machine|kheda, gujarat" not in seen
    assert "pk:laser welding machine|kheda, gujarat" not in seen


def test_full_lead_uses_phone_for_restart_dedupe(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "LEADS_CSV_DIR", tmp_path)

    append_lead_row(
        job_id="job-12345678",
        job_name="IndiaMART",
        event_type="lead_extracted",
        details={
            "product_title": "Laser Welding Machine",
            "buyer_phone": "9876543210",
            "lead_fingerprint": "ph:9876543210",
            "contact_revealed": True,
        },
    )

    seen = load_seen_lead_fingerprints("job-12345678", "IndiaMART")

    assert "ph:9876543210" in seen


def test_full_lead_scopes_phone_dedupe_to_product_and_city(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "LEADS_CSV_DIR", tmp_path)
    block = "Laser Welding Machine\nKheda, Gujarat\n4 mins ago"

    append_lead_row(
        job_id="job-12345678",
        job_name="IndiaMART",
        event_type="lead_extracted",
        details={
            "product_title": "Laser Welding Machine",
            "buyer_phone": "9876543210",
            "context_snippet": block,
            "lead_fingerprint": (
                "ph:9876543210|laser welding machine|kheda, gujarat"
            ),
            "contact_revealed": True,
        },
        context_snippet=block,
    )

    seen = load_seen_lead_fingerprints("job-12345678", "IndiaMART")

    assert "ph:9876543210|laser welding machine|kheda, gujarat" in seen
    assert "ph:9876543210|laser cleaning machine|kheda, gujarat" not in seen

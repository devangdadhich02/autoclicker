from __future__ import annotations

import csv
import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.automation.indiamart_leads import lead_fingerprint
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_LOCK = threading.Lock()

_CSV_HEADERS = [
    "timestamp",
    "job_id",
    "job_name",
    "event_type",
    "keyword_matched",
    "product_title",
    "buyer_name",
    "buyer_phone",
    "buyer_email",
    "buyer_location",
    "buyer_address",
    "inquiry_message",
    "context_snippet",
    "page_url",
    "lead_fingerprint",
    "contact_revealed",
    "next_contact_retry_at",
]


def _job_csv_path(job_id: str, job_name: str) -> Path:
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_name)[:40]
    return settings.LEADS_CSV_DIR / f"{safe_name}_{job_id[:8]}_leads.csv"


def load_seen_lead_fingerprints(job_id: str, job_name: str) -> set[str]:
    """Fingerprints already saved for this job — avoids re-counting the same buyer row."""
    path = _job_csv_path(job_id, job_name)
    seen: set[str] = set()
    if not path.exists():
        return seen
    try:
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                phone = re.sub(r"\D", "", row.get("buyer_phone") or "")
                if len(phone) >= 10:
                    seen.add(f"ph:{phone[-10:]}")
                    continue
                email = (row.get("buyer_email") or "").strip().lower()
                if email:
                    seen.add(f"em:{email}")
                    continue
                snippet = row.get("context_snippet") or row.get("inquiry_message") or ""
                fp = row.get("lead_fingerprint") or (
                    lead_fingerprint(snippet, {}) if snippet else ""
                )
                contact_revealed = (row.get("contact_revealed") or "").strip().lower()
                if fp and contact_revealed != "true":
                    seen.add(fp if fp.startswith("partial:") else f"partial:{fp}")
                    continue
                if fp:
                    seen.add(fp.removeprefix("partial:"))
    except Exception as exc:
        logger.warning("Could not load lead fingerprints", path=str(path), error=str(exc))
    return seen


def append_lead_row(
    *,
    job_id: str,
    job_name: str,
    event_type: str,
    keyword_matched: str | None = None,
    message: str = "",
    page_url: str | None = None,
    details: dict[str, Any] | None = None,
    context_snippet: str | None = None,
) -> Path | None:
    """Append one lead row to per-job CSV under /data/leads (survives restarts)."""
    details = details or {}
    row = {
        "timestamp": datetime.now(UTC).isoformat(),
        "job_id": job_id,
        "job_name": job_name,
        "event_type": event_type,
        "keyword_matched": keyword_matched or "",
        "product_title": details.get("product_title", ""),
        "buyer_name": details.get("buyer_name", ""),
        "buyer_phone": details.get("buyer_phone", ""),
        "buyer_email": details.get("buyer_email", ""),
        "buyer_location": details.get("buyer_location", ""),
        "buyer_address": details.get("buyer_address", details.get("buyer_location", "")),
        "inquiry_message": details.get(
            "message",
            details.get("inquiry_message", details.get("text", message)),
        ),
        "context_snippet": context_snippet or details.get("context_snippet", ""),
        "page_url": page_url or "",
        "lead_fingerprint": details.get("lead_fingerprint", ""),
        "contact_revealed": details.get("contact_revealed", ""),
        "next_contact_retry_at": details.get("next_contact_retry_at", ""),
    }

    path = _job_csv_path(job_id, job_name)
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_header = not path.exists() or path.stat().st_size == 0
            with path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=_CSV_HEADERS)
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
        logger.info("Lead saved to CSV", job_id=job_id, path=str(path))
        return path
    except Exception as exc:
        logger.error("Failed to append lead CSV", job_id=job_id, error=str(exc))
        return None


def clear_lead_csv_files(job_id: str | None = None) -> int:
    """Remove on-disk lead CSV files (all jobs or one job prefix)."""
    removed = 0
    base = settings.LEADS_CSV_DIR
    if not base.exists():
        return 0
    suffix = f"_{job_id[:8]}_leads.csv" if job_id else "_leads.csv"
    for path in base.glob(f"*{suffix}"):
        try:
            path.unlink()
            removed += 1
        except Exception:
            pass
    return removed


def parse_details_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            if "lead" in data and isinstance(data["lead"], dict):
                return data["lead"]
            return data
    except Exception:
        pass
    return {}

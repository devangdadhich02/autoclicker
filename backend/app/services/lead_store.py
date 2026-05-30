from __future__ import annotations

import csv
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    "buyer_name",
    "buyer_phone",
    "buyer_email",
    "inquiry_message",
    "context_snippet",
    "page_url",
]


def _job_csv_path(job_id: str, job_name: str) -> Path:
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_name)[:40]
    return settings.LEADS_CSV_DIR / f"{safe_name}_{job_id[:8]}_leads.csv"


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
        "buyer_name": details.get("buyer_name", ""),
        "buyer_phone": details.get("buyer_phone", ""),
        "buyer_email": details.get("buyer_email", ""),
        "inquiry_message": details.get("message", details.get("text", message)),
        "context_snippet": context_snippet or details.get("context_snippet", ""),
        "page_url": page_url or "",
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

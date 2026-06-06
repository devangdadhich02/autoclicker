"""
Leads API endpoints - List, view, and delete captured leads.
"""
from __future__ import annotations

import csv
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.user import User

router = APIRouter()


class LeadItem(BaseModel):
    id: str  # row index + filename hash for unique ID
    timestamp: str
    job_id: str
    job_name: str
    event_type: str
    keyword_matched: str
    product_title: str
    buyer_name: str
    buyer_phone: str
    buyer_email: str
    buyer_location: str
    buyer_address: str
    inquiry_message: str
    context_snippet: str
    page_url: str
    lead_fingerprint: str
    contact_revealed: str
    next_contact_retry_at: str


class LeadsListResponse(BaseModel):
    leads: list[LeadItem]
    total: int
    page: int
    page_size: int
    total_pages: int


def _read_all_leads() -> list[dict[str, Any]]:
    """Read all leads from all CSV files in the leads directory."""
    leads_dir = settings.LEADS_CSV_DIR
    all_leads: list[dict[str, Any]] = []
    
    if not leads_dir.exists():
        return all_leads
    
    for csv_file in leads_dir.glob("*_leads.csv"):
        try:
            file_hash = hash(csv_file.name) % 100000
            with csv_file.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for idx, row in enumerate(reader):
                    # Create unique ID from file hash + row index
                    row["id"] = f"{file_hash}_{idx}"
                    row["_file"] = str(csv_file)
                    row["_row_idx"] = idx
                    all_leads.append(row)
        except Exception:
            continue
    
    # Sort by timestamp descending (newest first)
    all_leads.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return all_leads


@router.get("", response_model=LeadsListResponse)
async def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    job_id: str | None = Query(None),
    search: str | None = Query(None),
    contact_only: bool = Query(False),
    current_user: User = Depends(get_current_user),
) -> LeadsListResponse:
    """List all captured leads with pagination and filtering."""
    all_leads = _read_all_leads()
    
    # Filter by job_id if provided
    if job_id:
        all_leads = [l for l in all_leads if l.get("job_id", "").startswith(job_id)]
    
    # Filter by contact_only (has phone or email)
    if contact_only:
        all_leads = [
            l for l in all_leads 
            if l.get("buyer_phone") or l.get("buyer_email")
        ]
    
    # Search filter
    if search:
        search_lower = search.lower()
        all_leads = [
            l for l in all_leads
            if search_lower in (l.get("buyer_name") or "").lower()
            or search_lower in (l.get("buyer_phone") or "").lower()
            or search_lower in (l.get("buyer_email") or "").lower()
            or search_lower in (l.get("product_title") or "").lower()
            or search_lower in (l.get("keyword_matched") or "").lower()
            or search_lower in (l.get("buyer_location") or "").lower()
        ]
    
    total = len(all_leads)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    
    # Paginate
    start = (page - 1) * page_size
    end = start + page_size
    page_leads = all_leads[start:end]
    
    # Convert to LeadItem
    items = []
    for lead in page_leads:
        items.append(LeadItem(
            id=lead.get("id", ""),
            timestamp=lead.get("timestamp", ""),
            job_id=lead.get("job_id", ""),
            job_name=lead.get("job_name", ""),
            event_type=lead.get("event_type", ""),
            keyword_matched=lead.get("keyword_matched", ""),
            product_title=lead.get("product_title", ""),
            buyer_name=lead.get("buyer_name", ""),
            buyer_phone=lead.get("buyer_phone", ""),
            buyer_email=lead.get("buyer_email", ""),
            buyer_location=lead.get("buyer_location", ""),
            buyer_address=lead.get("buyer_address", ""),
            inquiry_message=lead.get("inquiry_message", ""),
            context_snippet=lead.get("context_snippet", ""),
            page_url=lead.get("page_url", ""),
            lead_fingerprint=lead.get("lead_fingerprint", ""),
            contact_revealed=lead.get("contact_revealed", ""),
            next_contact_retry_at=lead.get("next_contact_retry_at", ""),
        ))
    
    return LeadsListResponse(
        leads=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/stats")
async def leads_stats(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get leads statistics."""
    all_leads = _read_all_leads()
    
    total = len(all_leads)
    with_phone = sum(1 for l in all_leads if l.get("buyer_phone"))
    with_email = sum(1 for l in all_leads if l.get("buyer_email"))
    with_contact = sum(1 for l in all_leads if l.get("buyer_phone") or l.get("buyer_email"))
    partial = sum(1 for l in all_leads if l.get("contact_revealed") == "false")
    
    # Group by job
    jobs: dict[str, int] = {}
    for lead in all_leads:
        job_name = lead.get("job_name") or lead.get("job_id", "unknown")[:8]
        jobs[job_name] = jobs.get(job_name, 0) + 1
    
    return {
        "total": total,
        "with_phone": with_phone,
        "with_email": with_email,
        "with_contact": with_contact,
        "partial": partial,
        "by_job": jobs,
    }


@router.delete("/{lead_id}")
async def delete_lead(
    lead_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Delete a specific lead by ID."""
    all_leads = _read_all_leads()
    
    # Find the lead
    target_lead = None
    for lead in all_leads:
        if lead.get("id") == lead_id:
            target_lead = lead
            break
    
    if not target_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    csv_file = Path(target_lead["_file"])
    row_idx = target_lead["_row_idx"]
    
    # Read all rows, remove the target, rewrite file
    try:
        rows = []
        with csv_file.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for idx, row in enumerate(reader):
                if idx != row_idx:
                    rows.append(row)
        
        # Rewrite the file
        with csv_file.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        return {"status": "deleted", "id": lead_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete lead: {str(e)}")


@router.delete("")
async def delete_all_leads(
    job_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete all leads, optionally filtered by job_id."""
    leads_dir = settings.LEADS_CSV_DIR
    
    if not leads_dir.exists():
        return {"status": "ok", "deleted": 0}
    
    deleted = 0
    for csv_file in leads_dir.glob("*_leads.csv"):
        try:
            if job_id:
                # Only delete if job_id matches
                if job_id[:8] in csv_file.name:
                    csv_file.unlink()
                    deleted += 1
            else:
                csv_file.unlink()
                deleted += 1
        except Exception:
            continue
    
    return {"status": "ok", "deleted": deleted}

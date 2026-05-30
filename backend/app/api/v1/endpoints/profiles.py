from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.api.schemas.profile import BrowserProfileStatus
from app.services.profile_service import ProfileService

router = APIRouter()


@router.get("", response_model=list[BrowserProfileStatus])
async def list_browser_profiles(
    db: DbSession,
    current_user: CurrentUser,
) -> list[BrowserProfileStatus]:
    """List uploaded browser sessions (e.g. indiamart) and readiness for automation."""
    svc = ProfileService(db)
    return await svc.list_profiles()


@router.get("/{profile_name}", response_model=BrowserProfileStatus)
async def get_browser_profile(
    profile_name: str,
    db: DbSession,
    current_user: CurrentUser,
) -> BrowserProfileStatus:
    svc = ProfileService(db)
    return await svc.get_profile(profile_name)

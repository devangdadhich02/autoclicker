from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.profile import BrowserProfileStatus, LinkedJobSummary
from app.core.config import settings
from app.models.automation_job import AutomationJob

META_FILENAME = ".velora_session_meta.json"

_COOKIE_PATHS = (
    "Default/Cookies",
    "Default/Network/Cookies",
    "Cookies",
)


def _find_cookies_file(profile_dir: Path) -> Path | None:
    for rel in _COOKIE_PATHS:
        p = profile_dir / rel
        if p.is_file() and p.stat().st_size > 0:
            return p
    for p in profile_dir.rglob("Cookies"):
        if p.is_file() and p.stat().st_size > 0:
            return p
    return None


def _has_local_storage(profile_dir: Path) -> bool:
    for rel in ("Default/Local Storage", "Default/Session Storage", "Local Storage"):
        if (profile_dir / rel).exists():
            return True
    return any(profile_dir.rglob("Local Storage"))


def _read_meta(profile_dir: Path) -> dict:
    meta_path = profile_dir / META_FILENAME
    if not meta_path.is_file():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _inspect_profile_dir(profile_name: str, profile_dir: Path) -> BrowserProfileStatus:
    files = [f for f in profile_dir.rglob("*") if f.is_file()]
    file_count = len(files)
    size_bytes = sum(f.stat().st_size for f in files)
    last_modified_at: datetime | None = None
    if files:
        latest = max(f.stat().st_mtime for f in files)
        last_modified_at = datetime.fromtimestamp(latest, tz=UTC)

    cookies_file = _find_cookies_file(profile_dir)
    has_cookies = cookies_file is not None
    has_local_storage = _has_local_storage(profile_dir)
    meta = _read_meta(profile_dir)

    uploaded_at: datetime | None = None
    if meta.get("uploaded_at"):
        try:
            uploaded_at = datetime.fromisoformat(
                str(meta["uploaded_at"]).replace("Z", "+00:00")
            )
        except Exception:
            pass

    if uploaded_at is None and last_modified_at:
        uploaded_at = last_modified_at

    if file_count == 0:
        status, msg = "missing", "Profile folder is empty — run login.ps1 on your PC"
    elif not has_cookies and file_count < 3:
        status, msg = "incomplete", "Upload looks incomplete — run login.ps1 again"
    elif not has_cookies:
        status, msg = "incomplete", "No cookie database found — login session may be invalid"
    else:
        status, msg = "ready", "Session received and ready for automation"

    return BrowserProfileStatus(
        profile_name=profile_name,
        status=status,
        status_message=msg,
        storage_path=str(profile_dir),
        file_count=file_count,
        size_bytes=size_bytes,
        has_cookies=has_cookies,
        has_local_storage=has_local_storage,
        uploaded_at=uploaded_at,
        login_url=meta.get("login_url"),
        uploaded_from=meta.get("uploaded_from"),
        last_modified_at=last_modified_at,
        linked_jobs=[],
    )


class ProfileService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _jobs_for_profile(self, profile_name: str) -> list[LinkedJobSummary]:
        result = await self._db.execute(
            select(AutomationJob).where(
                AutomationJob.browser_profile_name == profile_name
            )
        )
        jobs = list(result.scalars().all())
        return [
            LinkedJobSummary(
                id=j.id,
                name=j.name,
                status=j.status.value if hasattr(j.status, "value") else str(j.status),
                target_url=j.target_url,
            )
            for j in jobs
        ]

    async def list_profiles(self) -> list[BrowserProfileStatus]:
        base = settings.BROWSER_PROFILE_DIR
        base.mkdir(parents=True, exist_ok=True)

        names: set[str] = set()
        if base.is_dir():
            for child in base.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    names.add(child.name)

        result = await self._db.execute(
            select(AutomationJob.browser_profile_name).where(
                AutomationJob.browser_profile_name.isnot(None)
            )
        )
        for row in result.scalars().all():
            if row:
                names.add(row)

        profiles: list[BrowserProfileStatus] = []
        for name in sorted(names):
            profile_dir = base / name
            if profile_dir.is_dir():
                status = _inspect_profile_dir(name, profile_dir)
            else:
                status = BrowserProfileStatus(
                    profile_name=name,
                    status="missing",
                    status_message="Profile not on server yet — run login.ps1 to upload",
                    storage_path=str(profile_dir),
                    file_count=0,
                    size_bytes=0,
                    has_cookies=False,
                    has_local_storage=False,
                )
            status.linked_jobs = await self._jobs_for_profile(name)
            profiles.append(status)

        return profiles

    async def get_profile(self, profile_name: str) -> BrowserProfileStatus:
        profile_dir = settings.BROWSER_PROFILE_DIR / profile_name
        if profile_dir.is_dir():
            status = _inspect_profile_dir(profile_name, profile_dir)
        else:
            status = BrowserProfileStatus(
                profile_name=profile_name,
                status="missing",
                status_message="Profile not found — run login.ps1 on your PC, then refresh",
                storage_path=str(profile_dir),
                file_count=0,
                size_bytes=0,
                has_cookies=False,
                has_local_storage=False,
            )
        status.linked_jobs = await self._jobs_for_profile(profile_name)
        return status

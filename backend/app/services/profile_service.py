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
COOKIES_JSON = ".velora_cookies.json"

_COOKIE_PATHS = (
    "Default/Cookies",
    "Default/Network/Cookies",
    "Cookies",
)


def _find_cookies_file(profile_dir: Path) -> Path | None:
    for rel in _COOKIE_PATHS:
        p = profile_dir / rel
        if p.is_file() and p.stat().st_size > 512:
            return p
    for p in profile_dir.rglob("Cookies"):
        if p.is_file() and p.stat().st_size > 512:
            return p
    return None


def _has_chromium_profile_markers(profile_dir: Path) -> bool:
    markers = (
        "Local State",
        "Default/Preferences",
        "Default/Secure Preferences",
    )
    return any((profile_dir / m).is_file() for m in markers)


def _is_auto_job_profile(profile_name: str) -> bool:
    return profile_name.startswith("job_")


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


_PROFILE_SKIP_PARTS = frozenset(
    {"Code Cache", "GPUCache", "ShaderCache", "GrShaderCache", "Cache", "blob_storage"}
)


def _profile_files(profile_dir: Path) -> list[Path]:
    out: list[Path] = []
    for f in profile_dir.rglob("*"):
        if not f.is_file():
            continue
        if any(part in _PROFILE_SKIP_PARTS for part in f.parts):
            continue
        out.append(f)
    return out


def _inspect_profile_dir(profile_name: str, profile_dir: Path) -> BrowserProfileStatus:
    files = _profile_files(profile_dir)
    file_count = len(files)
    size_bytes = 0
    mtimes: list[float] = []
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        size_bytes += st.st_size
        mtimes.append(st.st_mtime)
    last_modified_at: datetime | None = None
    if mtimes:
        latest = max(mtimes)
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

    # UI shows only the latest upload metadata (written on each login.ps1 run), not old history
    login_verified = bool(meta.get("login_verified"))
    has_markers = _has_chromium_profile_markers(profile_dir)
    has_portable = (profile_dir / COOKIES_JSON).is_file() and (
        profile_dir / COOKIES_JSON
    ).stat().st_size > 10

    if file_count == 0:
        status, msg = "missing", "No profile files on server. Run login.ps1 on your laptop."
    elif file_count < 10:
        status, msg = (
            "incomplete",
            f"Only {file_count} files found (expected many more). Re-run login.ps1 and upload again.",
        )
    elif not has_cookies and not (has_markers and login_verified and file_count >= 20):
        status, msg = (
            "incomplete",
            "Cookie database not found. Log in again via login.ps1, then press Refresh here.",
        )
    elif not has_portable:
        status, msg = (
            "incomplete",
            "Re-run login.ps1 on laptop (needs cookie export for Linux server).",
        )
    else:
        status, msg = "ready", "IndiaMART login session is on the server and ready to use."

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

    async def list_profiles(self, login_only: bool = False) -> list[BrowserProfileStatus]:
        base = settings.BROWSER_PROFILE_DIR
        base.mkdir(parents=True, exist_ok=True)

        names: set[str] = set()
        if base.is_dir():
            for child in base.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    if login_only and _is_auto_job_profile(child.name):
                        continue
                    names.add(child.name)

        if not login_only:
            result = await self._db.execute(
                select(AutomationJob.browser_profile_name).where(
                    AutomationJob.browser_profile_name.isnot(None)
                )
            )
            for row in result.scalars().all():
                if row and not (login_only and _is_auto_job_profile(row)):
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
                    status_message="Profile not on server yet. Run login.ps1 on your laptop.",
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
                status_message="Profile not found. Run login.ps1 on your laptop, then refresh this page.",
                storage_path=str(profile_dir),
                file_count=0,
                size_bytes=0,
                has_cookies=False,
                has_local_storage=False,
            )
        status.linked_jobs = await self._jobs_for_profile(profile_name)
        return status

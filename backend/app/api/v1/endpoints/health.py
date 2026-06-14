from __future__ import annotations

import platform
import time
from datetime import UTC, datetime

import psutil
from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.automation.scheduler import get_scheduler
from app.core.config import settings

router = APIRouter()

_START_TIME = time.time()


@router.get("/api/v1/health", summary="Health check")
async def health_check() -> dict:
    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}


@router.get("/api/v1/health/detailed", summary="Detailed system health")
async def detailed_health(db: DbSession) -> dict:
    # DB check
    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    # Process resources
    proc = psutil.Process()
    mem = proc.memory_info()
    cpu_percent = psutil.cpu_percent(interval=0.1)

    # Scheduler status
    scheduler = get_scheduler()
    running_jobs = scheduler.list_running()

    uptime_seconds = time.time() - _START_TIME

    return {
        "status": "ok" if db_ok else "degraded",
        "timestamp": datetime.now(UTC).isoformat(),
        "uptime_seconds": round(uptime_seconds, 1),
        "version": "1.0.0",
        "environment": settings.APP_ENV,
        "platform": platform.system(),
        "database": {"status": "ok" if db_ok else "error"},
        "memory": {
            "rss_mb": round(mem.rss / 1024 / 1024, 2),
            "vms_mb": round(mem.vms / 1024 / 1024, 2),
        },
        "cpu_percent": cpu_percent,
        "automation": {
            "running_jobs": len(running_jobs),
            "job_ids": running_jobs,
        },
    }


@router.get("/api/v1/health/ping", summary="Simple ping")
async def ping() -> dict:
    return {"pong": True}

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.v1.router import api_router
from app.automation.scheduler import get_scheduler
from app.automation.watchdog import WatchdogService
from app.core.config import settings
from app.core.exceptions import VeloraException
from app.core.logging import configure_logging, get_logger
from app.db.session import close_engine, get_engine, get_session_factory

configure_logging()
logger = get_logger(__name__)

limiter = Limiter(key_func=get_remote_address, default_limits=[f"{settings.RATE_LIMIT_PER_MINUTE}/minute"])

_watchdog_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _watchdog_task
    logger.info("Starting Velora Auto Clicker backend", env=settings.APP_ENV)

    # Ensure DB engine is ready
    get_engine()

    # Run DB migrations on startup (dev/staging only; prod should use explicit alembic)
    if settings.APP_ENV in ("development", "staging"):
        from alembic import command
        from alembic.config import Config
        alembic_cfg = Config("alembic.ini")
        import asyncio as _asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, command.upgrade, alembic_cfg, "head")

    # Seed initial admin user if not exists
    await _seed_admin()
    await _ensure_indiamart_profile_names()

    # Start automation scheduler and auto-resume active jobs
    scheduler = get_scheduler()
    await scheduler.startup_active_jobs()

    # Start watchdog
    watchdog = WatchdogService(scheduler)
    _watchdog_task = asyncio.create_task(watchdog.start(), name="watchdog")

    logger.info("Velora backend ready")
    yield

    # Graceful shutdown
    logger.info("Shutting down Velora backend")
    if _watchdog_task and not _watchdog_task.done():
        _watchdog_task.cancel()
        try:
            await _watchdog_task
        except asyncio.CancelledError:
            pass

    await scheduler.shutdown_all()
    await close_engine()
    logger.info("Velora backend shutdown complete")


async def _ensure_indiamart_profile_names() -> None:
    """Persist indiamart profile on IndiaMART jobs created before the dashboard field existed."""
    from sqlalchemy import select

    from app.automation.indiamart_page import is_indiamart_seller_url
    from app.models.automation_job import AutomationJob

    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(select(AutomationJob))
        updated = 0
        for job in result.scalars().all():
            if job.browser_profile_name:
                continue
            if job.target_url and is_indiamart_seller_url(job.target_url):
                job.browser_profile_name = "indiamart"
                updated += 1
        if updated:
            await db.commit()
            logger.info(
                "Set browser_profile_name=indiamart on IndiaMART jobs",
                count=updated,
            )


async def _seed_admin() -> None:
    from app.core.exceptions import ConflictError
    from app.services.user_service import UserService
    from app.models.user import UserRole

    factory = get_session_factory()
    async with factory() as db:
        svc = UserService(db)
        existing = await svc.get_by_email(settings.FIRST_ADMIN_EMAIL)
        if existing is None:
            try:
                await svc.create(
                    email=settings.FIRST_ADMIN_EMAIL,
                    full_name="System Administrator",
                    password=settings.FIRST_ADMIN_PASSWORD,
                    role=UserRole.admin,
                )
                await db.commit()
                logger.info("Admin user seeded", email=settings.FIRST_ADMIN_EMAIL)
            except ConflictError:
                pass


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="Background Automation & Auto Clicker Platform — Team Velora",
        version="1.0.0",
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url="/api/redoc" if not settings.is_production else None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global exception handlers
    @app.exception_handler(VeloraException)
    async def velora_exception_handler(request: Request, exc: VeloraException) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": exc.message, "code": exc.code},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal server error occurred."},
        )

    # Routers
    app.include_router(api_router)

    return app


app = create_app()

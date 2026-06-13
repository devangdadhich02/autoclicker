from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, EmailStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ─────────────────────────────────────────────────────────
    APP_NAME: str = "Velora Auto Clicker"
    APP_ENV: Literal["development", "staging", "production"] = "production"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_DEBUG: bool = False
    SECRET_KEY: str = secrets.token_hex(32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Database ────────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./velora.db"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def fix_database_url(cls, v: str) -> str:
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    # ── Redis ───────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── Browser ─────────────────────────────────────────────────────────────
    BROWSER_HEADLESS: bool = True
    BROWSER_TYPE: Literal["chromium", "firefox", "webkit"] = "chromium"
    BROWSER_PROFILE_DIR: Path = Path("/data/browser_profiles")
    SCREENSHOT_DIR: Path = Path("/data/screenshots")
    LEADS_CSV_DIR: Path = Path("/data/leads")
    BROWSER_RECYCLE_INTERVAL_HOURS: int = 6
    BROWSER_NAVIGATION_TIMEOUT_MS: int = 90_000

    # ── Automation ──────────────────────────────────────────────────────────
    MAX_CONCURRENT_JOBS: int = 5
    DEFAULT_POLL_INTERVAL_SECONDS: int = 5
    INDIAMART_FAST_SCAN_INTERVAL_SECONDS: float = 0.75
    INDIAMART_DEEP_SCAN_INTERVAL_SECONDS: int = 30
    ACTION_RETRY_ATTEMPTS: int = 3
    ACTION_RETRY_DELAY_SECONDS: float = 1.0
    WATCHDOG_CHECK_INTERVAL_SECONDS: int = 30
    HEARTBEAT_TIMEOUT_SECONDS: int = 300

    # ── Logging ─────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_DIR: Path = Path("/data/logs")
    LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB
    LOG_BACKUP_COUNT: int = 10

    # ── CORS ────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:80"

    # ── Rate Limiting ────────────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 60

    # ── Initial Admin ────────────────────────────────────────────────────────
    FIRST_ADMIN_EMAIL: EmailStr = "admin@velora.com"  # type: ignore[assignment]
    FIRST_ADMIN_PASSWORD: str = "ChangeMe!Strong1"

    @property
    def cors_origins(self) -> list[str]:
        v = self.ALLOWED_ORIGINS.strip()
        if v.startswith("["):
            import json
            return json.loads(v)
        return [o.strip() for o in v.split(",") if o.strip()]

    @field_validator("BROWSER_PROFILE_DIR", "SCREENSHOT_DIR", "LOG_DIR", "LEADS_CSV_DIR", mode="after")
    @classmethod
    def ensure_dir(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Velora Auto Clicker — Backend

FastAPI-based backend for the Velora background browser automation platform.

## Tech Stack

- Python 3.13 + FastAPI
- SQLAlchemy (async) + Alembic migrations
- Playwright (Chromium) — headless browser automation
- JWT authentication (access + refresh tokens)
- PostgreSQL (Supabase) / SQLite (dev/test)
- Structlog for structured logging
- pytest + pytest-asyncio for testing

## Quick Start (Local Dev)

```bash
pip install -e ".[dev]"
playwright install chromium
cp .env.example .env
# Edit .env — set DATABASE_URL and SECRET_KEY
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/api/docs

## Quick Start (Docker)

```bash
cp .env.docker .env
# Edit .env — set DATABASE_URL (Supabase) and SECRET_KEY
docker compose up -d --build
```

## Environment Variables

See `.env.example` for full reference. Required:

| Variable | Description |
|----------|-------------|
| SECRET_KEY | JWT signing secret (32+ chars) |
| DATABASE_URL | postgresql+asyncpg://... (Supabase URL) |
| FIRST_ADMIN_EMAIL | Admin account email |
| FIRST_ADMIN_PASSWORD | Admin account password |

## API Endpoints

Base URL: `/api/v1`

| Prefix | Description |
|--------|-------------|
| /auth | Login, refresh, profile, password change |
| /users | User management (admin only) |
| /jobs | Automation job CRUD + start/stop/restart |
| /jobs/{id}/keywords | Keyword detection rules |
| /jobs/{id}/actions | Action rules (click, navigate, screenshot) |
| /logs | Event logs, analytics, CSV export |
| /health | Health checks |
| /ws/dashboard | WebSocket live dashboard feed |
| /ws/job/{id} | WebSocket per-job live feed |

## Running Tests

```bash
pytest
```

## Project Structure

```
app/
├── api/          # REST endpoints + schemas + deps
├── automation/   # Playwright engine, scheduler, watchdog
├── core/         # Config, logging, security, exceptions
├── db/           # SQLAlchemy engine + session
├── models/       # ORM models
└── services/     # Business logic layer
```

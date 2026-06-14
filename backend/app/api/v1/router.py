from fastapi import APIRouter

from app.api.v1.endpoints import (
    action_rules,
    auth,
    health,
    jobs,
    keywords,
    leads,
    logs,
    profiles,
    users,
    ws,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
api_router.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Automation Jobs"])
api_router.include_router(
    keywords.router, prefix="/api/v1/jobs/{job_id}/keywords", tags=["Keywords"]
)
api_router.include_router(
    action_rules.router, prefix="/api/v1/jobs/{job_id}/actions", tags=["Action Rules"]
)
api_router.include_router(logs.router, prefix="/api/v1/logs", tags=["Event Logs"])
api_router.include_router(leads.router, prefix="/api/v1/leads", tags=["Leads"])
api_router.include_router(
    profiles.router, prefix="/api/v1/profiles", tags=["Browser Sessions"]
)
api_router.include_router(health.router, prefix="/api/v1/health", tags=["Health"])
api_router.include_router(ws.router, prefix="/api/v1/ws", tags=["WebSocket"])

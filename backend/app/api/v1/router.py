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
api_router.include_router(users.router, tags=["Users"])
api_router.include_router(jobs.router, tags=["Automation Jobs"])
api_router.include_router(keywords.router, tags=["Keywords"])
api_router.include_router(action_rules.router, tags=["Action Rules"])
api_router.include_router(logs.router, tags=["Event Logs"])
api_router.include_router(leads.router, tags=["Leads"])
api_router.include_router(profiles.router, tags=["Browser Sessions"])
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(ws.router, prefix="/api/v1/ws", tags=["WebSocket"])

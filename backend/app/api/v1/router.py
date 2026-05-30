from fastapi import APIRouter

from app.api.v1.endpoints import auth, users, jobs, keywords, action_rules, logs, health, ws, profiles

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["Automation Jobs"])
api_router.include_router(keywords.router, prefix="/jobs/{job_id}/keywords", tags=["Keywords"])
api_router.include_router(action_rules.router, prefix="/jobs/{job_id}/actions", tags=["Action Rules"])
api_router.include_router(logs.router, prefix="/logs", tags=["Event Logs"])
api_router.include_router(profiles.router, prefix="/profiles", tags=["Browser Sessions"])
api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(ws.router, prefix="/ws", tags=["WebSocket"])

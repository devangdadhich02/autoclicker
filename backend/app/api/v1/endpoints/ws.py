from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError

from app.automation.scheduler import get_scheduler
from app.core.logging import get_logger
from app.core.security import decode_token
from app.db.session import get_session_factory
from app.models.event_log import EventSeverity
from app.services.event_log_service import EventLogService

router = APIRouter()
logger = get_logger(__name__)


class ConnectionManager:
    """Manages WebSocket connections with broadcast support."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, client_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[client_id] = websocket
        logger.info("WebSocket connected", client_id=client_id)

    def disconnect(self, client_id: str) -> None:
        self._connections.pop(client_id, None)
        logger.info("WebSocket disconnected", client_id=client_id)

    async def send_personal(self, client_id: str, data: dict[str, Any]) -> None:
        ws = self._connections.get(client_id)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect(client_id)

    async def broadcast(self, data: dict[str, Any]) -> None:
        dead: list[str] = []
        for cid, ws in list(self._connections.items()):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self.disconnect(cid)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


def get_ws_manager() -> ConnectionManager:
    return manager


@router.websocket("/dashboard")
async def websocket_dashboard(websocket: WebSocket) -> None:
    """
    Real-time dashboard WebSocket.
    Clients authenticate via token query parameter.
    Pushes scheduler status and recent events every 3 seconds.
    """
    token = websocket.query_params.get("token")
    client_id: str | None = None

    if not token:
        await websocket.close(code=4001, reason="Missing token.")
        return

    try:
        payload = decode_token(token)
        client_id = payload.get("sub", "unknown")
    except JWTError:
        await websocket.close(code=4001, reason="Invalid token.")
        return

    await manager.connect(client_id, websocket)

    try:
        while True:
            scheduler = get_scheduler()
            running = scheduler.list_running()

            factory = get_session_factory()
            async with factory() as db:
                log_svc = EventLogService(db)
                recent_logs = await log_svc.list_logs(limit=20)
                severity_counts = await log_svc.count_by_severity()

            log_data = [
                {
                    "id": log.id,
                    "job_id": log.job_id,
                    "severity": log.severity,
                    "event_type": log.event_type,
                    "message": log.message,
                    "keyword_matched": log.keyword_matched,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                }
                for log in recent_logs
            ]

            await manager.send_personal(
                client_id,
                {
                    "type": "dashboard_update",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "running_jobs": running,
                    "running_count": len(running),
                    "recent_logs": log_data,
                    "severity_counts": severity_counts,
                },
            )

            # Wait 3s but also handle any incoming messages
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=3.0)
            except asyncio.TimeoutError:
                pass

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as exc:
        logger.error("WebSocket error", client_id=client_id, error=str(exc))
        manager.disconnect(client_id)


@router.websocket("/job/{job_id}")
async def websocket_job(websocket: WebSocket, job_id: str) -> None:
    """Per-job WebSocket for granular live updates."""
    token = websocket.query_params.get("token")
    client_id: str | None = None

    if not token:
        await websocket.close(code=4001, reason="Missing token.")
        return

    try:
        payload = decode_token(token)
        client_id = f"{payload.get('sub', 'unknown')}_{job_id}"
    except JWTError:
        await websocket.close(code=4001, reason="Invalid token.")
        return

    await manager.connect(client_id, websocket)

    try:
        while True:
            scheduler = get_scheduler()
            is_running = scheduler.is_running(job_id)

            factory = get_session_factory()
            async with factory() as db:
                log_svc = EventLogService(db)
                logs = await log_svc.list_logs(job_id=job_id, limit=10)

            await manager.send_personal(
                client_id,
                {
                    "type": "job_update",
                    "job_id": job_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "is_running": is_running,
                    "recent_logs": [
                        {
                            "id": log.id,
                            "severity": log.severity,
                            "event_type": log.event_type,
                            "message": log.message,
                            "keyword_matched": log.keyword_matched,
                            "created_at": log.created_at.isoformat() if log.created_at else None,
                        }
                        for log in logs
                    ],
                },
            )

            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=3.0)
            except asyncio.TimeoutError:
                pass

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as exc:
        logger.error("Job WebSocket error", client_id=client_id, job_id=job_id, error=str(exc))
        manager.disconnect(client_id)

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession, OperatorUser
from app.api.schemas.job import JobControlRequest, JobCreate, JobResponse, JobUpdate
from app.automation.scheduler import get_scheduler
from app.core.exceptions import AuthorizationError, NotFoundError
from app.services.job_service import JobService

router = APIRouter()


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    db: DbSession,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 50,
) -> list[JobResponse]:
    svc = JobService(db)
    from app.models.user import UserRole
    owner_id = None if current_user.role == UserRole.admin else current_user.id
    jobs = await svc.list_jobs(owner_id=owner_id, skip=skip, limit=limit)
    return [JobResponse.model_validate(j) for j in jobs]


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: JobCreate, db: DbSession, current_user: OperatorUser
) -> JobResponse:
    svc = JobService(db)
    job = await svc.create(
        owner_id=current_user.id,
        name=body.name,
        target_url=body.target_url,
        description=body.description,
        poll_interval_seconds=body.poll_interval_seconds,
        browser_profile_name=body.browser_profile_name,
        scheduler_cron=body.scheduler_cron,
    )
    return JobResponse.model_validate(job)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: DbSession, current_user: CurrentUser) -> JobResponse:
    svc = JobService(db)
    try:
        job = await svc.get_by_id_authorized(job_id, current_user)
    except (NotFoundError, AuthorizationError) as exc:
        code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_403_FORBIDDEN
        raise HTTPException(status_code=code, detail=exc.message)
    return JobResponse.model_validate(job)


@router.patch("/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: str, body: JobUpdate, db: DbSession, current_user: OperatorUser
) -> JobResponse:
    svc = JobService(db)
    try:
        job = await svc.update(job_id, current_user, **body.model_dump(exclude_unset=True))
    except (NotFoundError, AuthorizationError) as exc:
        code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_403_FORBIDDEN
        raise HTTPException(status_code=code, detail=exc.message)
    return JobResponse.model_validate(job)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(job_id: str, db: DbSession, current_user: OperatorUser) -> None:
    scheduler = get_scheduler()
    if scheduler.is_running(job_id):
        await scheduler.stop_job(job_id)
    svc = JobService(db)
    try:
        await svc.delete(job_id, current_user)
    except (NotFoundError, AuthorizationError) as exc:
        code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_403_FORBIDDEN
        raise HTTPException(status_code=code, detail=exc.message)


@router.post("/{job_id}/control", response_model=JobResponse)
async def control_job(
    job_id: str,
    body: JobControlRequest,
    db: DbSession,
    current_user: OperatorUser,
) -> JobResponse:
    svc = JobService(db)
    try:
        job = await svc.get_by_id_authorized(job_id, current_user)
    except (NotFoundError, AuthorizationError) as exc:
        code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_403_FORBIDDEN
        raise HTTPException(status_code=code, detail=exc.message)

    scheduler = get_scheduler()

    if body.action == "start":
        if not job.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Job is disabled.")
        await scheduler.start_job(job_id)
    elif body.action == "stop":
        await scheduler.stop_job(job_id)
    elif body.action == "restart":
        await scheduler.restart_job(job_id)

    job = await svc.get_by_id(job_id)
    return JobResponse.model_validate(job)


@router.get("/{job_id}/status")
async def get_job_runtime_status(
    job_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    svc = JobService(db)
    try:
        await svc.get_by_id_authorized(job_id, current_user)
    except (NotFoundError, AuthorizationError) as exc:
        code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_403_FORBIDDEN
        raise HTTPException(status_code=code, detail=exc.message)

    scheduler = get_scheduler()
    return {"job_id": job_id, "is_running": scheduler.is_running(job_id)}

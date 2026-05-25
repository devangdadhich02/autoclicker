from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession, OperatorUser
from app.api.schemas.keyword import KeywordCreate, KeywordResponse, KeywordUpdate
from app.core.exceptions import AuthorizationError, NotFoundError
from app.services.job_service import JobService
from app.services.keyword_service import KeywordService

router = APIRouter()


async def _assert_job_access(job_id: str, current_user, db) -> None:
    svc = JobService(db)
    try:
        await svc.get_by_id_authorized(job_id, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)


@router.get("", response_model=list[KeywordResponse])
async def list_keywords(job_id: str, db: DbSession, current_user: CurrentUser) -> list[KeywordResponse]:
    await _assert_job_access(job_id, current_user, db)
    svc = KeywordService(db)
    keywords = await svc.list_for_job(job_id)
    return [KeywordResponse.model_validate(k) for k in keywords]


@router.post("", response_model=KeywordResponse, status_code=status.HTTP_201_CREATED)
async def create_keyword(
    job_id: str, body: KeywordCreate, db: DbSession, current_user: OperatorUser
) -> KeywordResponse:
    await _assert_job_access(job_id, current_user, db)
    svc = KeywordService(db)
    kw = await svc.create(
        job_id=job_id,
        value=body.value,
        match_type=body.match_type,
        case_sensitive=body.case_sensitive,
        priority=body.priority,
        score=body.score,
        category=body.category,
        location_filter=body.location_filter,
        cooldown_seconds=body.cooldown_seconds,
    )
    return KeywordResponse.model_validate(kw)


@router.patch("/{keyword_id}", response_model=KeywordResponse)
async def update_keyword(
    job_id: str,
    keyword_id: str,
    body: KeywordUpdate,
    db: DbSession,
    current_user: OperatorUser,
) -> KeywordResponse:
    await _assert_job_access(job_id, current_user, db)
    svc = KeywordService(db)
    try:
        kw = await svc.update(keyword_id, **body.model_dump(exclude_unset=True))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    return KeywordResponse.model_validate(kw)


@router.delete("/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_keyword(
    job_id: str, keyword_id: str, db: DbSession, current_user: OperatorUser
) -> None:
    await _assert_job_access(job_id, current_user, db)
    svc = KeywordService(db)
    try:
        await svc.delete(keyword_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)

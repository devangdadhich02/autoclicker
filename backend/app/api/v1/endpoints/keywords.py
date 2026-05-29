from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DbSession, OperatorUser
from pydantic import BaseModel, Field

from app.api.schemas.keyword import KeywordCreate, KeywordResponse, KeywordUpdate
from app.models.keyword import MatchType
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


@router.delete("/{keyword_id}")
async def delete_keyword(
    job_id: str, keyword_id: str, db: DbSession, current_user: OperatorUser
) -> Response:
    await _assert_job_access(job_id, current_user, db)
    svc = KeywordService(db)
    try:
        await svc.delete(keyword_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class KeywordsBulkCreate(BaseModel):
    """Create multiple keywords from comma-separated string with same location filter."""
    keywords: str = Field(..., min_length=1, description="Comma-separated keywords like 'steel pipe, copper wire, pvc pipe'")
    location_filter: str | None = Field(default=None, description="Location filter like 'Bangalore, New York, Delhi'")
    match_type: MatchType = MatchType.contains
    priority: int = Field(default=5, ge=1, le=10)
    cooldown_seconds: int = Field(default=300, ge=0)


@router.post("/bulk", response_model=list[KeywordResponse], status_code=status.HTTP_201_CREATED)
async def create_keywords_bulk(
    job_id: str, body: KeywordsBulkCreate, db: DbSession, current_user: OperatorUser
) -> list[KeywordResponse]:
    """Create multiple keywords at once from comma-separated list."""
    await _assert_job_access(job_id, current_user, db)
    svc = KeywordService(db)

    # Parse comma-separated keywords
    keyword_values = [k.strip() for k in body.keywords.split(",") if k.strip()]
    if not keyword_values:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid keywords provided")

    created: list[KeywordResponse] = []
    for value in keyword_values:
        kw = await svc.create(
            job_id=job_id,
            value=value,
            match_type=body.match_type,
            case_sensitive=False,
            priority=body.priority,
            score=1.0,
            category=None,
            location_filter=body.location_filter,
            cooldown_seconds=body.cooldown_seconds,
        )
        created.append(KeywordResponse.model_validate(kw))

    return created

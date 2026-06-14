from __future__ import annotations

from sqlalchemy import select

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DbSession, OperatorUser
from app.api.schemas.action_rule import ActionRuleCreate, ActionRuleResponse, ActionRuleUpdate
from app.core.exceptions import AuthorizationError, NotFoundError
from app.models.action_rule import ActionRule
from app.services.job_service import JobService

router = APIRouter()


async def _assert_job_access(job_id: str, current_user, db) -> None:
    svc = JobService(db)
    try:
        await svc.get_by_id_authorized(job_id, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)


@router.get("/api/v1/jobs/{job_id}/actions", response_model=list[ActionRuleResponse])
async def list_action_rules(
    job_id: str, db: DbSession, current_user: CurrentUser
) -> list[ActionRuleResponse]:
    await _assert_job_access(job_id, current_user, db)
    result = await db.execute(
        select(ActionRule).where(ActionRule.job_id == job_id).order_by(ActionRule.order)
    )
    rules = list(result.scalars().all())
    return [ActionRuleResponse.model_validate(r) for r in rules]


@router.post(
    "/api/v1/jobs/{job_id}/actions",
    response_model=ActionRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_action_rule(
    job_id: str, body: ActionRuleCreate, db: DbSession, current_user: OperatorUser
) -> ActionRuleResponse:
    await _assert_job_access(job_id, current_user, db)
    rule = ActionRule(job_id=job_id, **body.model_dump())
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    return ActionRuleResponse.model_validate(rule)


@router.patch("/api/v1/jobs/{job_id}/actions/{rule_id}", response_model=ActionRuleResponse)
async def update_action_rule(
    job_id: str,
    rule_id: str,
    body: ActionRuleUpdate,
    db: DbSession,
    current_user: OperatorUser,
) -> ActionRuleResponse:
    await _assert_job_access(job_id, current_user, db)
    result = await db.execute(
        select(ActionRule).where(ActionRule.id == rule_id, ActionRule.job_id == job_id)
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ActionRule not found.")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(rule, key, value)
    await db.flush()
    await db.refresh(rule)
    return ActionRuleResponse.model_validate(rule)


@router.delete("/api/v1/jobs/{job_id}/actions/{rule_id}")
async def delete_action_rule(
    job_id: str, rule_id: str, db: DbSession, current_user: OperatorUser
) -> Response:
    await _assert_job_access(job_id, current_user, db)
    result = await db.execute(
        select(ActionRule).where(ActionRule.id == rule_id, ActionRule.job_id == job_id)
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ActionRule not found.")
    await db.delete(rule)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Modernize API — readiness, plans, spawn Build (Stitches 1 + 2)."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps.modernize_deps import require_modernize
from app.core.auth import get_current_user
from app.core.database import User, get_db
from app.services.intelligence.repo_ingestion_service import RepoIngestionService
from app.services.modernize.plan_service import PlanService
from app.services.modernize.spawn_build_service import spawn_build_project

router = APIRouter(prefix="/modernize", tags=["Modernize"])


class CreateApplicationPlansRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    playbook_id: Optional[str] = None
    skip_existing: bool = True


class CreatePlanRequest(BaseModel):
    repository_id: str
    title: Optional[str] = Field(None, max_length=200)
    playbook_id: Optional[str] = None


class UpdatePlanRequest(BaseModel):
    state: Optional[str] = None
    plan_md: Optional[str] = None
    title: Optional[str] = Field(None, max_length=200)


@router.get("/playbooks")
async def list_playbooks(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_modernize(user, db)
    return {"playbooks": PlanService(db).list_playbooks(user.tenant_id)}


@router.get("/repos/{repo_id}/readiness")
async def get_repo_readiness(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return last stored assessment only (does not compute)."""
    require_modernize(user, db)
    from app.services.modernize.assessment_service import AssessmentService

    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return AssessmentService(db).get_repo_readiness_response(repo)


@router.post("/repos/{repo_id}/assessments/run")
async def run_repo_assessment(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicitly run modernization assessment for a repository."""
    require_modernize(user, db)
    from app.services.modernize.assessment_service import AssessmentService

    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return AssessmentService(db).run_repo_assessment(repo, trigger="manual")


@router.get("/applications/{application_id}/readiness")
async def get_application_readiness(
    application_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return last stored application assessment only (does not compute)."""
    require_modernize(user, db)
    from app.services.modernize.assessment_service import AssessmentService

    payload = AssessmentService(db).get_application_readiness_response(
        user.tenant_id, application_id
    )
    if not payload:
        raise HTTPException(status_code=404, detail="Application not found")
    return payload


@router.post("/applications/{application_id}/assessments/run")
async def run_application_assessment(
    application_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run assessment across all member repositories and persist the application roll-up."""
    require_modernize(user, db)
    from app.services.modernize.assessment_service import AssessmentService

    try:
        return AssessmentService(db).run_application_assessment(
            user.tenant_id, application_id, trigger="manual"
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/applications/{application_id}/plans")
async def create_application_plans(
    application_id: str,
    request: CreateApplicationPlansRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create modernization plans for each ready repository in an application."""
    require_modernize(user, db)
    service = PlanService(db)
    try:
        return service.create_application_plans(
            user.tenant_id,
            user.id,
            application_id,
            title=request.title,
            playbook_id=request.playbook_id,
            skip_existing=request.skip_existing,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/plans")
async def create_plan(
    request: CreatePlanRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_modernize(user, db)
    service = PlanService(db)
    try:
        plan = service.create_plan(
            user.tenant_id,
            user.id,
            request.repository_id,
            title=request.title,
            playbook_id=request.playbook_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return plan


@router.get("/plans")
async def list_plans(
    state: Optional[str] = None,
    repository_id: Optional[str] = None,
    application_id: Optional[str] = None,
    bundle_id: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_modernize(user, db)
    plans = PlanService(db).list_plans(
        user.tenant_id,
        state=state,
        repository_id=repository_id,
        application_id=application_id,
        bundle_id=bundle_id,
    )
    return {"plans": plans}


@router.get("/plans/{plan_id}")
async def get_plan(
    plan_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_modernize(user, db)
    plan = PlanService(db).get_plan(user.tenant_id, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.patch("/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    request: UpdatePlanRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_modernize(user, db)
    service = PlanService(db)
    try:
        plan = service.update_plan(
            user.tenant_id,
            plan_id,
            state=request.state,
            plan_md=request.plan_md,
            title=request.title,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return plan


@router.post("/plans/{plan_id}/refresh-assessment")
async def refresh_plan_assessment(
    plan_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_modernize(user, db)
    try:
        plan = PlanService(db).refresh_assessment(user.tenant_id, plan_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return plan


@router.post("/plans/{plan_id}/spawn-build")
async def spawn_build(
    plan_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_modernize(user, db)
    try:
        result = spawn_build_project(db, user.tenant_id, user.id, plan_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result

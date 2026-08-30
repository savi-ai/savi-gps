"""Modernize API — readiness, plans, spawn Build (Stitches 1 + 2)."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps.modernize_deps import require_modernize
from app.core.auth import get_current_user
from app.core.database import User, get_db
from app.core.logger import logger
from app.services.intelligence.repo_ingestion_service import RepoIngestionService
from app.services.modernize.plan_service import PlanService
from app.services.modernize.execution_service import ExecutionService
from app.services.modernize.fix_stage_service import FixStageService
from app.services.modernize.modernize_stage_service import ModernizeStageService
from app.services.modernize.spawn_build_service import spawn_build_project

router = APIRouter(prefix="/modernize", tags=["Modernize"])


class CreateApplicationPlansRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    playbook_id: Optional[str] = None
    skip_existing: bool = True
    # W8.3: default one app-scoped modernize plan; set True for legacy N per-repo plans
    per_repository: bool = False


class CreatePlanRequest(BaseModel):
    repository_id: Optional[str] = None
    application_id: Optional[str] = None
    title: Optional[str] = Field(None, max_length=200)
    playbook_id: Optional[str] = None
    plan_type: str = Field(default="modernize", description="fix | modernize")


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
    """Create an app-scoped modernize plan (default) or legacy per-repo plans."""
    require_modernize(user, db)
    service = PlanService(db)
    try:
        if request.per_repository:
            return service.create_application_plans(
                user.tenant_id,
                user.id,
                application_id,
                title=request.title,
                playbook_id=request.playbook_id,
                skip_existing=request.skip_existing,
            )
        plan = service.create_application_modernize_plan(
            user.tenant_id,
            user.id,
            application_id,
            title=request.title,
            playbook_id=request.playbook_id,
        )
        return {
            "application_id": application_id,
            "plan": plan,
            "plans": [plan],
            "scope": "application",
        }
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
        if request.application_id and request.plan_type == "modernize" and not request.repository_id:
            plan = service.create_application_modernize_plan(
                user.tenant_id,
                user.id,
                request.application_id,
                title=request.title,
                playbook_id=request.playbook_id,
            )
        else:
            if not request.repository_id:
                raise ValueError("repository_id is required for fix plans and repo-scoped modernize plans")
            plan = service.create_plan(
                user.tenant_id,
                user.id,
                request.repository_id,
                title=request.title,
                playbook_id=request.playbook_id,
                plan_type=request.plan_type,
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
    plan_type: Optional[str] = None,
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
        plan_type=plan_type,
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


@router.delete("/plans/{plan_id}")
async def delete_plan(
    plan_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a plan that has not started execution."""
    require_modernize(user, db)
    try:
        return PlanService(db).delete_plan(user.tenant_id, plan_id)
    except ValueError as e:
        detail = str(e)
        status = 404 if detail == "Plan not found" else 400
        raise HTTPException(status_code=status, detail=detail)


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


class SpawnBuildRequest(BaseModel):
    """W5/W8: target git repo for modernization; optional for fix (defaults to source repo)."""

    target_github_url: Optional[str] = Field(
        None, min_length=8, description="GitHub URL to push/PR into (required for modernize)"
    )
    target_branch: str = Field(default="main", description="Base/working branch on the target repo")


@router.post("/plans/{plan_id}/spawn-build")
async def spawn_build(
    plan_id: str,
    request: SpawnBuildRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_modernize(user, db)
    try:
        result = spawn_build_project(
            db,
            user.tenant_id,
            user.id,
            plan_id,
            target_github_url=request.target_github_url,
            target_branch=request.target_branch,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.get("/plans/{plan_id}/execution")
async def get_plan_execution(
    plan_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return execution workspace manifest and paths for a plan (W8)."""
    require_modernize(user, db)
    from app.core.database import ModernizationPlan
    from app.services.modernize.execution_service import ExecutionService

    plan = (
        db.query(ModernizationPlan)
        .filter(ModernizationPlan.id == plan_id, ModernizationPlan.tenant_id == user.tenant_id)
        .first()
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    try:
        return ExecutionService(db).get_execution_status(user.tenant_id, plan)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/plans/{plan_id}/execution/stages/{stage}/run")
async def run_execution_stage(
    plan_id: str,
    stage: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Enqueue one Copilot-gated stage (returns immediately; poll GET …/execution)."""
    require_modernize(user, db)
    from app.core.database import ModernizationPlan
    from app.services.task_service import TaskService, TaskType

    plan = (
        db.query(ModernizationPlan)
        .filter(ModernizationPlan.id == plan_id, ModernizationPlan.tenant_id == user.tenant_id)
        .first()
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if not plan.spawned_project_id:
        raise HTTPException(
            status_code=400,
            detail="Spawn execution first so stages can run in the background",
        )

    plan_type = getattr(plan, "plan_type", None) or "modernize"
    try:
        if plan_type == "fix":
            FixStageService(db).prepare_stage(user.tenant_id, plan_id, stage)
        else:
            ModernizeStageService(db).prepare_stage(user.tenant_id, plan_id, stage)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    task_service = TaskService(db)
    task = task_service.create_task(
        project_id=plan.spawned_project_id,
        task_type=TaskType.RUN_EXECUTION_STAGE,
        input_data={
            "tenant_id": user.tenant_id,
            "plan_id": plan_id,
            "stage": stage,
            "plan_type": plan_type,
        },
        user_id=user.id,
    )
    logger.info(
        "Enqueued execution stage %s for plan %s as task %s",
        stage,
        plan_id,
        task.id,
    )
    return {
        "status": "started",
        "stage": stage,
        "task_id": task.id,
        "message": "Stage started in background. Poll execution status until completed or failed.",
    }


class RegisterTargetRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=80)
    github_url: str = Field(..., min_length=8)
    branch: str = Field(default="main")
    clone: bool = True


@router.post("/plans/{plan_id}/execution/targets")
async def register_execution_target(
    plan_id: str,
    request: RegisterTargetRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Register a new target repo URL for an architecture component (W8.4)."""
    require_modernize(user, db)
    try:
        return ModernizeStageService(db).register_target(
            user.tenant_id,
            plan_id,
            slug=request.slug,
            github_url=request.github_url,
            branch=request.branch,
            clone=request.clone,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/plans/{plan_id}/execution/retry-clone")
async def retry_execution_clone(
    plan_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-clone source/ for a fix plan when the initial clone failed."""
    require_modernize(user, db)
    try:
        return FixStageService(db).retry_source_clone(user.tenant_id, plan_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

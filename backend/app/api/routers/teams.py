"""Teams API — ADR 0007 / Savi Teammate Phase T1."""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import User, get_db
from app.core.logger import logger
from app.services.team_acl import require_savi_work_access, user_can_manage_teams
from app.services.team_service import TeamService

router = APIRouter(prefix="/teams", tags=["Teams"])


class TeamCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    member_user_ids: Optional[List[str]] = None


class TeamUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class TeamMemberRequest(BaseModel):
    user_id: str
    role: str = Field("member", description="lead | member")


class TeamApplicationRequest(BaseModel):
    application_id: str
    access: str = Field("own", description="own | share")


def _require_team_admin(user: User, db: Session) -> None:
    if not user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")
    if not user_can_manage_teams(user, db):
        raise HTTPException(status_code=403, detail="Admin permission required to manage teams")


@router.get("")
async def list_teams(
    mine: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")
    svc = TeamService(db)
    svc.ensure_default_team(user.tenant_id, created_by=user.id)
    teams = svc.list_teams(user.tenant_id)
    if mine and not user_can_manage_teams(user, db):
        my_ids = set(svc.user_team_ids(user.tenant_id, user.id))
        teams = [t for t in teams if t.id in my_ids]
    return {
        "teams": [svc.to_summary_dict(t) for t in teams],
        "count": len(teams),
    }


@router.post("")
async def create_team(
    request: TeamCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_team_admin(user, db)
    svc = TeamService(db)
    try:
        team = svc.create_team(
            user.tenant_id,
            request.name,
            description=request.description,
            created_by=user.id,
            member_user_ids=request.member_user_ids,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info("Tenant %s created team %s", user.tenant_id, team.id)
    return svc.to_detail_dict(team)


@router.get("/savi-activity")
async def list_savi_activity(
    status: Optional[str] = None,
    phase: Optional[str] = None,
    errors_only: bool = False,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin lite: Savis + last work / orchestrator status (Phase B4)."""
    _require_team_admin(user, db)
    from app.services.savi_admin_activity_service import SaviAdminActivityService

    rows = SaviAdminActivityService(db).list_activity(
        user.tenant_id,
        status_filter=status,
        phase_filter=phase,
        errors_only=errors_only,
        limit=min(limit, 500),
    )
    return {"items": rows, "count": len(rows)}


@router.post("/ensure-default")
async def ensure_default_team(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Backfill Default team + attach orphan applications."""
    _require_team_admin(user, db)
    svc = TeamService(db)
    team = svc.ensure_default_team(user.tenant_id, created_by=user.id)
    return svc.to_detail_dict(team)


@router.get("/{team_id}")
async def get_team(
    team_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")
    svc = TeamService(db)
    team = svc.get_team(user.tenant_id, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return svc.to_detail_dict(team)


@router.patch("/{team_id}")
async def update_team(
    team_id: str,
    request: TeamUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_team_admin(user, db)
    svc = TeamService(db)
    try:
        team = svc.update_team(
            user.tenant_id,
            team_id,
            name=request.name,
            description=request.description,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=404 if "not found" in str(e).lower() else 400,
            detail=str(e),
        )
    return svc.to_detail_dict(team)


@router.delete("/{team_id}")
async def delete_team(
    team_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_team_admin(user, db)
    svc = TeamService(db)
    try:
        svc.delete_team(user.tenant_id, team_id)
    except ValueError as e:
        raise HTTPException(
            status_code=404 if "not found" in str(e).lower() else 400,
            detail=str(e),
        )
    return {"deleted": True, "team_id": team_id}


@router.post("/{team_id}/members")
async def add_team_member(
    team_id: str,
    request: TeamMemberRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_team_admin(user, db)
    svc = TeamService(db)
    try:
        svc.add_member(user.tenant_id, team_id, request.user_id, role=request.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    team = svc.get_team(user.tenant_id, team_id)
    return svc.to_detail_dict(team)


@router.delete("/{team_id}/members/{member_user_id}")
async def remove_team_member(
    team_id: str,
    member_user_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_team_admin(user, db)
    svc = TeamService(db)
    try:
        svc.remove_member(user.tenant_id, team_id, member_user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"removed": True, "user_id": member_user_id}


@router.post("/{team_id}/applications")
async def attach_team_application(
    team_id: str,
    request: TeamApplicationRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_team_admin(user, db)
    svc = TeamService(db)
    try:
        svc.attach_application(
            user.tenant_id,
            team_id,
            request.application_id,
            access=request.access,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    team = svc.get_team(user.tenant_id, team_id)
    return svc.to_detail_dict(team)


@router.delete("/{team_id}/applications/{application_id}")
async def detach_team_application(
    team_id: str,
    application_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_team_admin(user, db)
    svc = TeamService(db)
    try:
        svc.detach_application(user.tenant_id, team_id, application_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"removed": True, "application_id": application_id}


class SaviRosterRequest(BaseModel):
    display_name: Optional[str] = None


@router.get("/{team_id}/savi")
async def list_team_savi(
    team_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")
    from app.services.savi_roster_service import SaviRosterService

    svc = TeamService(db)
    team = svc.get_team(user.tenant_id, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    roster = SaviRosterService(db)
    items = roster.list_for_team(user.tenant_id, team_id)
    return {
        "savi_instances": [roster.to_dict(s, team=team) for s in items],
        "count": len(items),
    }


@router.post("/{team_id}/savi")
async def roster_savi(
    team_id: str,
    request: SaviRosterRequest = SaviRosterRequest(),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Roster a Savi Teammate onto this Team (V1: one active per team)."""
    _require_team_admin(user, db)
    from app.services.savi_roster_service import SaviRosterService

    roster = SaviRosterService(db)
    try:
        instance = roster.roster(
            user.tenant_id,
            team_id,
            created_by=user.id,
            display_name=request.display_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    team = TeamService(db).get_team(user.tenant_id, team_id)
    logger.info("Tenant %s rostered Savi %s on team %s", user.tenant_id, instance.id, team_id)
    return roster.to_dict(instance, team=team)


@router.post("/{team_id}/savi/{savi_id}/disable")
async def disable_savi(
    team_id: str,
    savi_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_team_admin(user, db)
    from app.services.savi_roster_service import SaviRosterService

    roster = SaviRosterService(db)
    instance = roster.get(user.tenant_id, savi_id)
    if not instance or instance.team_id != team_id:
        raise HTTPException(status_code=404, detail="Savi instance not found")
    try:
        instance = roster.disable(user.tenant_id, savi_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    team = TeamService(db).get_team(user.tenant_id, team_id)
    return roster.to_dict(instance, team=team)


@router.post("/{team_id}/savi/{savi_id}/enable")
async def enable_savi(
    team_id: str,
    savi_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_team_admin(user, db)
    from app.services.savi_roster_service import SaviRosterService

    roster = SaviRosterService(db)
    instance = roster.get(user.tenant_id, savi_id)
    if not instance or instance.team_id != team_id:
        raise HTTPException(status_code=404, detail="Savi instance not found")
    try:
        instance = roster.enable(user.tenant_id, savi_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    team = TeamService(db).get_team(user.tenant_id, team_id)
    return roster.to_dict(instance, team=team)


@router.post("/{team_id}/savi/{savi_id}/deprovision")
async def deprovision_savi(
    team_id: str,
    savi_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_team_admin(user, db)
    from app.services.savi_roster_service import SaviRosterService

    roster = SaviRosterService(db)
    instance = roster.get(user.tenant_id, savi_id)
    if not instance or instance.team_id != team_id:
        raise HTTPException(status_code=404, detail="Savi instance not found")
    try:
        roster.deprovision(user.tenant_id, savi_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"deprovisioned": True, "savi_id": savi_id}


# --- Phase T3: per-Savi work queue ------------------------------------------


class ContextRefInput(BaseModel):
    type: str = Field("note", description="url | note | jira_text")
    label: Optional[str] = None
    value: str


class WorkEnqueueRequest(BaseModel):
    title: str
    description: Optional[str] = None
    application_id: Optional[str] = None
    source: str = Field("manual", description="manual | jira | slack")
    external_ref: Optional[str] = None
    priority: Optional[int] = Field(
        None, description="1–100, 1=highest; omit to use default or await priority"
    )
    context_refs: Optional[List[ContextRefInput]] = None
    extra_repository_ids: Optional[List[str]] = None


class WorkAnswerRequest(BaseModel):
    answers: Dict[str, str] = Field(
        ..., description="Map of question id → answer text"
    )


class WorkPriorityRequest(BaseModel):
    priority: int = Field(..., ge=1, le=100, description="1 = highest priority")


class WorkTransitionRequest(BaseModel):
    state: str


@router.get("/{team_id}/savi/{savi_id}/work")
async def list_savi_work(
    team_id: str,
    savi_id: str,
    include_done: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    from app.services.savi_work_queue_service import SaviWorkQueueService

    q = SaviWorkQueueService(db)
    try:
        items = q.list_for_savi(
            user.tenant_id, team_id, savi_id, include_done=include_done
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "team_id": team_id,
        "savi_instance_id": savi_id,
        "work_items": [q.to_dict(i) for i in items],
        "count": len(items),
        "in_progress_id": next(
            (i.id for i in items if i.state == "in_progress"), None
        ),
    }


@router.post("/{team_id}/savi/{savi_id}/work")
async def enqueue_savi_work(
    team_id: str,
    savi_id: str,
    request: WorkEnqueueRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    from app.services.savi_context_assembly_service import SaviContextAssemblyService
    from app.services.savi_work_queue_service import SaviWorkQueueService

    q = SaviWorkQueueService(db)
    try:
        item = q.enqueue(
            user.tenant_id,
            team_id,
            savi_id,
            title=request.title,
            description=request.description,
            application_id=request.application_id,
            source=request.source,
            external_ref=request.external_ref,
            assigned_by=user.id,
            priority=request.priority,
            context_refs=[r.model_dump() for r in (request.context_refs or [])],
            extra_repository_ids=request.extra_repository_ids,
        )
        item = await SaviContextAssemblyService(db).assemble_if_queued(
            user.tenant_id, team_id, savi_id, item
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info(
        "User %s enqueued work %s on team %s savi %s",
        user.id,
        item.id,
        team_id,
        savi_id,
    )
    return q.to_dict(item)


@router.post("/{team_id}/savi/{savi_id}/work/start-next")
async def start_next_savi_work(
    team_id: str,
    savi_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Move the highest-priority queued item to in_progress (max one per Savi)."""
    require_savi_work_access(db, user, team_id)
    from app.services.savi_work_queue_service import SaviWorkQueueService

    q = SaviWorkQueueService(db)
    try:
        item = q.start_next(user.tenant_id, team_id, savi_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not item:
        return {"started": False, "work_item": None}
    return {"started": True, "work_item": q.to_dict(item)}


@router.get("/{team_id}/savi/{savi_id}/work/{item_id}")
async def get_savi_work_item(
    team_id: str,
    savi_id: str,
    item_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    from app.services.savi_work_queue_service import SaviWorkQueueService

    q = SaviWorkQueueService(db)
    item = q.get(user.tenant_id, team_id, savi_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Work item not found")
    return q.to_dict(item)


@router.post("/{team_id}/savi/{savi_id}/work/{item_id}/answer")
async def answer_savi_work(
    team_id: str,
    savi_id: str,
    item_id: str,
    request: WorkAnswerRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    from app.services.savi_context_assembly_service import SaviContextAssemblyService
    from app.services.savi_work_queue_service import SaviWorkQueueService

    q = SaviWorkQueueService(db)
    try:
        item = q.answer_clarification(
            user.tenant_id, team_id, savi_id, item_id, request.answers
        )
        item = await SaviContextAssemblyService(db).assemble_if_queued(
            user.tenant_id, team_id, savi_id, item
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return q.to_dict(item)


@router.post("/{team_id}/savi/{savi_id}/work/{item_id}/priority")
async def set_savi_work_priority(
    team_id: str,
    savi_id: str,
    item_id: str,
    request: WorkPriorityRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    from app.services.savi_context_assembly_service import SaviContextAssemblyService
    from app.services.savi_work_queue_service import SaviWorkQueueService

    q = SaviWorkQueueService(db)
    try:
        item = q.set_priority(
            user.tenant_id, team_id, savi_id, item_id, request.priority
        )
        item = await SaviContextAssemblyService(db).assemble_if_queued(
            user.tenant_id, team_id, savi_id, item
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return q.to_dict(item)


@router.post("/{team_id}/savi/{savi_id}/work/{item_id}/assemble-context")
async def assemble_savi_work_context(
    team_id: str,
    savi_id: str,
    item_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Build or replace the context pack (T4). Manual re-run from inbox."""
    require_savi_work_access(db, user, team_id)
    from app.services.savi_context_assembly_service import SaviContextAssemblyService
    from app.services.savi_work_queue_service import SaviWorkQueueService

    q = SaviWorkQueueService(db)
    try:
        item = await SaviContextAssemblyService(db).assemble(
            user.tenant_id, team_id, savi_id, item_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return q.to_dict(item)


@router.post("/{team_id}/savi/{savi_id}/work/{item_id}/transition")
async def transition_savi_work(
    team_id: str,
    savi_id: str,
    item_id: str,
    request: WorkTransitionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    from app.services.savi_work_queue_service import SaviWorkQueueService

    q = SaviWorkQueueService(db)
    try:
        item = q.transition(
            user.tenant_id, team_id, savi_id, item_id, request.state
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return q.to_dict(item)

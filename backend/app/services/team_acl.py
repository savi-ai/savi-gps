"""Team-scoped ACL helpers (ADR 0007)."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.auth import has_permission
from app.core.config import settings
from app.core.database import User
from app.services.team_service import TeamService


def team_acl_enforced() -> bool:
    return bool(settings.TEAM_ACL_ENFORCED)


def user_can_manage_teams(user: User, db: Session) -> bool:
    return has_permission(user, "can_manage_teams", db) or has_permission(
        user, "can_manage_tenant_config", db
    )


def user_can_modify_application(
    db: Session, user: User, application_id: str
) -> bool:
    """
    When TEAM_ACL_ENFORCED is false, any intelligence user may mutate (Alpha).
    When true: tenant admins always; else must share a Team that links the Application.
    """
    if not user.tenant_id:
        return False
    if user_can_manage_teams(user, db):
        return True
    if not team_acl_enforced():
        return True

    svc = TeamService(db)
    user_teams = set(svc.user_team_ids(user.tenant_id, user.id))
    if not user_teams:
        # Soft path: ensure default team exists and user is lead if they're creating chaos
        return False
    app_teams = set(svc.application_team_ids(user.tenant_id, application_id))
    return bool(user_teams & app_teams)


def user_can_assign_savi_work(
    db: Session, user: User, team_id: str
) -> bool:
    """Team members or tenant team admins can enqueue / manage that Team's Savi queue."""
    if not user.tenant_id:
        return False
    if user_can_manage_teams(user, db):
        return True
    svc = TeamService(db)
    return team_id in svc.user_team_ids(user.tenant_id, user.id)


def require_savi_work_access(db: Session, user: User, team_id: str) -> None:
    if user_can_assign_savi_work(db, user, team_id):
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "You must be a member of this Team (or a tenant admin) "
            "to view or assign Savi work."
        ),
    )

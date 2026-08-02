"""Team inventory + membership (ADR 0007 / Savi Teammate Phase T1)."""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import Application, Team, TeamApplication, TeamMember, User
from app.core.logger import logger

TEAM_MEMBER_ROLES = ("lead", "member")
TEAM_APP_ACCESS = ("own", "share")


def _slugify(name: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return raw or "team"


class TeamService:
    def __init__(self, db: Session):
        self.db = db

    def list_teams(self, tenant_id: str) -> List[Team]:
        return (
            self.db.query(Team)
            .filter(Team.tenant_id == tenant_id)
            .order_by(Team.name.asc())
            .all()
        )

    def get_team(self, tenant_id: str, team_id: str) -> Optional[Team]:
        return (
            self.db.query(Team)
            .filter(Team.id == team_id, Team.tenant_id == tenant_id)
            .first()
        )

    def get_default_team(self, tenant_id: str) -> Optional[Team]:
        return (
            self.db.query(Team)
            .filter(Team.tenant_id == tenant_id, Team.is_default == True)  # noqa: E712
            .first()
        )

    def ensure_default_team(
        self, tenant_id: str, *, created_by: Optional[str] = None
    ) -> Team:
        """Create Default team and attach orphan Applications (ADR 0007 backfill)."""
        existing = self.get_default_team(tenant_id)
        if existing:
            self._attach_orphan_applications(tenant_id, existing.id)
            return existing

        team = self.create_team(
            tenant_id,
            name="Default",
            description="Auto-created team for existing estate inventory",
            created_by=created_by,
            is_default=True,
        )
        self._attach_orphan_applications(tenant_id, team.id)
        logger.info("Created default team %s for tenant %s", team.id, tenant_id)
        return team

    def _attach_orphan_applications(self, tenant_id: str, team_id: str) -> int:
        apps = (
            self.db.query(Application)
            .filter(Application.tenant_id == tenant_id)
            .all()
        )
        linked = {
            row.application_id
            for row in self.db.query(TeamApplication.application_id)
            .join(Team, TeamApplication.team_id == Team.id)
            .filter(Team.tenant_id == tenant_id)
            .all()
        }
        added = 0
        for app in apps:
            if app.id in linked:
                continue
            self.db.add(
                TeamApplication(
                    id=str(uuid.uuid4()),
                    team_id=team_id,
                    application_id=app.id,
                    access="own",
                )
            )
            added += 1
        if added:
            self.db.commit()
        return added

    def create_team(
        self,
        tenant_id: str,
        name: str,
        description: Optional[str] = None,
        created_by: Optional[str] = None,
        is_default: bool = False,
        member_user_ids: Optional[List[str]] = None,
    ) -> Team:
        name = (name or "").strip()
        if not name:
            raise ValueError("Team name is required")

        clash = (
            self.db.query(Team)
            .filter(Team.tenant_id == tenant_id, Team.name == name)
            .first()
        )
        if clash:
            raise ValueError(f"Team '{name}' already exists")

        slug = _slugify(name)
        slug_base = slug
        n = 2
        while (
            self.db.query(Team)
            .filter(Team.tenant_id == tenant_id, Team.slug == slug)
            .first()
        ):
            slug = f"{slug_base}-{n}"
            n += 1

        if is_default:
            # Only one default per tenant
            for t in self.list_teams(tenant_id):
                if t.is_default:
                    t.is_default = False

        team = Team(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=name,
            slug=slug,
            description=description,
            is_default=is_default,
            created_by=created_by,
        )
        self.db.add(team)
        self.db.flush()

        # Creator becomes lead
        if created_by:
            self.db.add(
                TeamMember(
                    id=str(uuid.uuid4()),
                    team_id=team.id,
                    user_id=created_by,
                    role="lead",
                )
            )

        for uid in member_user_ids or []:
            if created_by and uid == created_by:
                continue
            self.add_member(tenant_id, team.id, uid, role="member", commit=False)

        self.db.commit()
        self.db.refresh(team)
        return team

    def update_team(
        self,
        tenant_id: str,
        team_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Team:
        team = self.get_team(tenant_id, team_id)
        if not team:
            raise ValueError("Team not found")
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("Team name cannot be empty")
            clash = (
                self.db.query(Team)
                .filter(
                    Team.tenant_id == tenant_id,
                    Team.name == name,
                    Team.id != team_id,
                )
                .first()
            )
            if clash:
                raise ValueError(f"Team '{name}' already exists")
            team.name = name
        if description is not None:
            team.description = description
        self.db.commit()
        self.db.refresh(team)
        return team

    def delete_team(self, tenant_id: str, team_id: str) -> None:
        team = self.get_team(tenant_id, team_id)
        if not team:
            raise ValueError("Team not found")
        if team.is_default:
            raise ValueError("Cannot delete the default team")
        self.db.delete(team)
        self.db.commit()

    def add_member(
        self,
        tenant_id: str,
        team_id: str,
        user_id: str,
        role: str = "member",
        *,
        commit: bool = True,
    ) -> TeamMember:
        team = self.get_team(tenant_id, team_id)
        if not team:
            raise ValueError("Team not found")
        role = (role or "member").lower()
        if role not in TEAM_MEMBER_ROLES:
            raise ValueError(f"role must be one of: {', '.join(TEAM_MEMBER_ROLES)}")

        user = (
            self.db.query(User)
            .filter(User.id == user_id, User.tenant_id == tenant_id)
            .first()
        )
        if not user:
            raise ValueError("User not found in this tenant")

        existing = (
            self.db.query(TeamMember)
            .filter(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
            .first()
        )
        if existing:
            existing.role = role
            if commit:
                self.db.commit()
                self.db.refresh(existing)
            return existing

        membership = TeamMember(
            id=str(uuid.uuid4()),
            team_id=team_id,
            user_id=user_id,
            role=role,
        )
        self.db.add(membership)
        if commit:
            self.db.commit()
            self.db.refresh(membership)
        return membership

    def remove_member(self, tenant_id: str, team_id: str, user_id: str) -> None:
        team = self.get_team(tenant_id, team_id)
        if not team:
            raise ValueError("Team not found")
        row = (
            self.db.query(TeamMember)
            .filter(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
            .first()
        )
        if not row:
            raise ValueError("Member not found")
        self.db.delete(row)
        self.db.commit()

    def attach_application(
        self,
        tenant_id: str,
        team_id: str,
        application_id: str,
        access: str = "own",
    ) -> TeamApplication:
        team = self.get_team(tenant_id, team_id)
        if not team:
            raise ValueError("Team not found")
        app = (
            self.db.query(Application)
            .filter(Application.id == application_id, Application.tenant_id == tenant_id)
            .first()
        )
        if not app:
            raise ValueError("Application not found")
        access = (access or "own").lower()
        if access not in TEAM_APP_ACCESS:
            raise ValueError(f"access must be one of: {', '.join(TEAM_APP_ACCESS)}")

        existing = (
            self.db.query(TeamApplication)
            .filter(
                TeamApplication.team_id == team_id,
                TeamApplication.application_id == application_id,
            )
            .first()
        )
        if existing:
            existing.access = access
            self.db.commit()
            self.db.refresh(existing)
            return existing

        link = TeamApplication(
            id=str(uuid.uuid4()),
            team_id=team_id,
            application_id=application_id,
            access=access,
        )
        self.db.add(link)
        self.db.commit()
        self.db.refresh(link)
        return link

    def detach_application(
        self, tenant_id: str, team_id: str, application_id: str
    ) -> None:
        team = self.get_team(tenant_id, team_id)
        if not team:
            raise ValueError("Team not found")
        row = (
            self.db.query(TeamApplication)
            .filter(
                TeamApplication.team_id == team_id,
                TeamApplication.application_id == application_id,
            )
            .first()
        )
        if not row:
            raise ValueError("Application is not linked to this team")
        self.db.delete(row)
        self.db.commit()

    def user_team_ids(self, tenant_id: str, user_id: str) -> List[str]:
        rows = (
            self.db.query(TeamMember.team_id)
            .join(Team, TeamMember.team_id == Team.id)
            .filter(Team.tenant_id == tenant_id, TeamMember.user_id == user_id)
            .all()
        )
        return [r[0] for r in rows]

    def application_team_ids(self, tenant_id: str, application_id: str) -> List[str]:
        rows = (
            self.db.query(TeamApplication.team_id)
            .join(Team, TeamApplication.team_id == Team.id)
            .filter(
                Team.tenant_id == tenant_id,
                TeamApplication.application_id == application_id,
            )
            .all()
        )
        return [r[0] for r in rows]

    def to_summary_dict(self, team: Team) -> Dict[str, Any]:
        member_count = (
            self.db.query(TeamMember).filter(TeamMember.team_id == team.id).count()
        )
        app_count = (
            self.db.query(TeamApplication)
            .filter(TeamApplication.team_id == team.id)
            .count()
        )
        return {
            "id": team.id,
            "name": team.name,
            "slug": team.slug,
            "description": team.description,
            "is_default": bool(team.is_default),
            "business_unit_id": team.business_unit_id,
            "member_count": member_count,
            "application_count": app_count,
            "created_at": team.created_at.isoformat() if team.created_at else None,
            "updated_at": team.updated_at.isoformat() if team.updated_at else None,
        }

    def to_detail_dict(self, team: Team) -> Dict[str, Any]:
        data = self.to_summary_dict(team)
        members = (
            self.db.query(TeamMember, User)
            .join(User, TeamMember.user_id == User.id)
            .filter(TeamMember.team_id == team.id)
            .all()
        )
        data["members"] = [
            {
                "user_id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "email": user.email,
                "role": membership.role,
            }
            for membership, user in members
        ]
        links = (
            self.db.query(TeamApplication, Application)
            .join(Application, TeamApplication.application_id == Application.id)
            .filter(TeamApplication.team_id == team.id)
            .order_by(Application.name.asc())
            .all()
        )
        data["applications"] = [
            {
                "id": app.id,
                "name": app.name,
                "access": link.access,
                "origin": getattr(app, "origin", None) or "imported",
            }
            for link, app in links
        ]
        from app.services.savi_roster_service import SaviRosterService

        roster = SaviRosterService(self.db)
        data["savi_instances"] = [
            roster.to_dict(s, team=team) for s in roster.list_for_team(team.tenant_id, team.id)
        ]
        return data

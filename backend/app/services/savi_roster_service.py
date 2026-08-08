"""Savi Teammate roster — Phase T2 (ADR 0007 / 0008).

A Savi is an identity + queue placeholder on a Team. Execution sandboxes
are ephemeral (ADR 0008); this service only provisions/deprovisions the instance.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.auth import get_password_hash
from app.core.database import Role, SaviInstance, Team, User, UserRole
from app.core.logger import logger
from app.services.team_service import TeamService

MACHINE_EMAIL_DOMAIN = "savi.machine.local"
SAVI_STATUSES = ("pending", "active", "disabled")


class SaviRosterService:
    def __init__(self, db: Session):
        self.db = db

    def list_for_team(self, tenant_id: str, team_id: str) -> List[SaviInstance]:
        return (
            self.db.query(SaviInstance)
            .filter(
                SaviInstance.tenant_id == tenant_id,
                SaviInstance.team_id == team_id,
            )
            .order_by(SaviInstance.created_at.asc())
            .all()
        )

    def get(self, tenant_id: str, savi_id: str) -> Optional[SaviInstance]:
        return (
            self.db.query(SaviInstance)
            .filter(SaviInstance.id == savi_id, SaviInstance.tenant_id == tenant_id)
            .first()
        )

    def active_for_team(self, tenant_id: str, team_id: str) -> Optional[SaviInstance]:
        return (
            self.db.query(SaviInstance)
            .filter(
                SaviInstance.tenant_id == tenant_id,
                SaviInstance.team_id == team_id,
                SaviInstance.status == "active",
            )
            .first()
        )

    def roster(
        self,
        tenant_id: str,
        team_id: str,
        *,
        created_by: Optional[str] = None,
        display_name: Optional[str] = None,
        allow_multiple: bool = False,
    ) -> SaviInstance:
        """
        Roster one Savi onto a Team (V1: at most one active/pending per team).
        Mints a machine User for audit attribution (login password is random / unused).
        """
        team = TeamService(self.db).get_team(tenant_id, team_id)
        if not team:
            raise ValueError("Team not found")

        if not allow_multiple:
            existing = (
                self.db.query(SaviInstance)
                .filter(
                    SaviInstance.tenant_id == tenant_id,
                    SaviInstance.team_id == team_id,
                    SaviInstance.status.in_(("active", "pending")),
                )
                .first()
            )
            if existing:
                raise ValueError(
                    f"Team already has a rostered Savi ({existing.slug}). "
                    "Deprovision or disable it before rostering another (V1)."
                )

        name = (display_name or f"Savi ({team.name})").strip()
        slug = f"savi-{team.slug}"
        # Ensure unique slug in tenant
        base = slug
        n = 2
        while (
            self.db.query(SaviInstance)
            .filter(SaviInstance.tenant_id == tenant_id, SaviInstance.slug == slug)
            .first()
        ):
            slug = f"{base}-{n}"
            n += 1

        machine_user = self._ensure_machine_user(
            tenant_id, username=slug, display_name=name
        )

        instance = SaviInstance(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            team_id=team_id,
            name=name,
            slug=slug,
            status="active",
            machine_user_id=machine_user.id,
            created_by=created_by,
        )
        self.db.add(instance)
        self.db.commit()
        self.db.refresh(instance)
        logger.info(
            "Rostered Savi %s on team %s (machine_user=%s)",
            instance.id,
            team_id,
            machine_user.id,
        )
        return instance

    def disable(self, tenant_id: str, savi_id: str) -> SaviInstance:
        instance = self.get(tenant_id, savi_id)
        if not instance:
            raise ValueError("Savi instance not found")
        instance.status = "disabled"
        instance.updated_at = datetime.now()
        if instance.machine_user_id:
            user = self.db.query(User).filter(User.id == instance.machine_user_id).first()
            if user:
                user.is_active = False
        self.db.commit()
        self.db.refresh(instance)
        return instance

    def enable(self, tenant_id: str, savi_id: str) -> SaviInstance:
        instance = self.get(tenant_id, savi_id)
        if not instance:
            raise ValueError("Savi instance not found")
        # V1: only one active Savi per team
        other = (
            self.db.query(SaviInstance)
            .filter(
                SaviInstance.tenant_id == tenant_id,
                SaviInstance.team_id == instance.team_id,
                SaviInstance.status == "active",
                SaviInstance.id != savi_id,
            )
            .first()
        )
        if other:
            raise ValueError(
                f"Another Savi is already active on this team ({other.slug})"
            )
        instance.status = "active"
        instance.updated_at = datetime.now()
        if instance.machine_user_id:
            user = self.db.query(User).filter(User.id == instance.machine_user_id).first()
            if user:
                user.is_active = True
        self.db.commit()
        self.db.refresh(instance)
        return instance

    def deprovision(self, tenant_id: str, savi_id: str) -> None:
        """Disable Savi, seat, external identity, connectors; deactivate machine user."""
        instance = self.get(tenant_id, savi_id)
        if not instance:
            raise ValueError("Savi instance not found")
        instance.status = "disabled"
        instance.updated_at = datetime.now()
        instance.external_identity_provider = None
        instance.external_identity_subject = None
        instance.external_identity_display = None
        instance.external_identity_metadata = None
        instance.external_identity_linked_at = None
        instance.external_identity_linked_by = None
        if instance.machine_user_id:
            user = self.db.query(User).filter(User.id == instance.machine_user_id).first()
            if user:
                user.is_active = False
        from app.core.database import SaviCodingAgentSeat
        from app.services.connectors.binding_service import SaviConnectorBindingService

        seat = (
            self.db.query(SaviCodingAgentSeat)
            .filter(SaviCodingAgentSeat.savi_instance_id == savi_id)
            .first()
        )
        if seat:
            seat.status = "disabled"
            seat.updated_at = datetime.now()

        # B1: revoke connector bindings (no commit until end)
        SaviConnectorBindingService(self.db).disable_all_for_savi(
            tenant_id, instance.team_id, savi_id, commit=False
        )
        self.db.commit()
        logger.info("Deprovisioned Savi %s (connectors revoked)", savi_id)

    def _ensure_machine_user(
        self, tenant_id: str, *, username: str, display_name: str
    ) -> User:
        email = f"{username}@{MACHINE_EMAIL_DOMAIN}"
        existing = (
            self.db.query(User)
            .filter(User.tenant_id == tenant_id, User.username == username)
            .first()
        )
        if existing:
            existing.is_active = True
            existing.full_name = display_name
            self.db.commit()
            self.db.refresh(existing)
            return existing

        # Unusable random password — human login not intended
        password = secrets.token_urlsafe(48)
        user = User(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            username=username,
            email=email,
            password_hash=get_password_hash(password),
            full_name=display_name,
            is_active=True,
        )
        self.db.add(user)
        self.db.flush()

        # Developer role: can use intelligence context as attribution principal
        role = self.db.query(Role).filter(Role.name == "developer").first()
        if role:
            self.db.add(
                UserRole(
                    id=str(uuid.uuid4()),
                    user_id=user.id,
                    role_id=role.id,
                )
            )
        self.db.commit()
        self.db.refresh(user)
        return user

    def to_dict(self, instance: SaviInstance, team: Optional[Team] = None) -> Dict[str, Any]:
        machine = None
        if instance.machine_user_id:
            user = self.db.query(User).filter(User.id == instance.machine_user_id).first()
            if user:
                machine = {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "is_active": user.is_active,
                }
        from app.services.savi_identity_seat_service import SaviIdentitySeatService

        id_svc = SaviIdentitySeatService(self.db)
        seat = id_svc.get_seat(instance.tenant_id, instance.team_id, instance.id)
        return {
            "id": instance.id,
            "team_id": instance.team_id,
            "team_name": team.name if team else None,
            "name": instance.name,
            "slug": instance.slug,
            "status": instance.status,
            "machine_user": machine,
            "external_identity": id_svc.external_identity_dict(instance),
            "coding_agent_seat": id_svc.seat_to_dict(seat) if seat else None,
            "created_by": instance.created_by,
            "created_at": instance.created_at.isoformat() if instance.created_at else None,
            "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
            "execution_model": "ephemeral_sandbox",  # ADR 0008
        }

"""Savi external identity + coding-agent seat bindings (T7 / ADR 0009)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import SaviCodingAgentSeat, SaviInstance
from app.services.intelligence.token_cipher import decrypt_token, encrypt_token
from app.services.savi_roster_service import SaviRosterService
from app.services.team_service import TeamService

EXTERNAL_PROVIDERS = ("entra", "okta", "google", "github", "custom")
AGENT_TYPES = (
    "github_copilot",
    "cursor",
    "kiro",
    "claude_code",
    "custom",
)
EXECUTION_MODES = (
    "cli",
    "claude_cli",
    "copilot_cli",
    "kiro_cli",
    "api",
    "remote_runner",
    "llm",
    "heuristic",
)
SEAT_STATUSES = ("pending_license", "active", "disabled")

# When seat.execution_mode == "cli", map agent_type → concrete adapter mode
_CLI_MODE_BY_AGENT = {
    "claude_code": "claude_cli",
    "github_copilot": "copilot_cli",
    "kiro": "kiro_cli",
    "cursor": "llm",  # no first-party CLI wiring yet
    "custom": "llm",
}


class SaviIdentitySeatService:
    def __init__(self, db: Session):
        self.db = db

    def _require_savi(
        self, tenant_id: str, team_id: str, savi_id: str
    ) -> SaviInstance:
        team = TeamService(self.db).get_team(tenant_id, team_id)
        if not team:
            raise ValueError("Team not found")
        savi = SaviRosterService(self.db).get(tenant_id, savi_id)
        if not savi or savi.team_id != team_id:
            raise ValueError("Savi instance not found on this team")
        return savi

    # --- External identity -------------------------------------------------

    def attach_external_identity(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        *,
        provider: str,
        subject: str,
        display_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        linked_by: Optional[str] = None,
    ) -> SaviInstance:
        savi = self._require_savi(tenant_id, team_id, savi_id)
        provider = (provider or "").lower().strip()
        if provider not in EXTERNAL_PROVIDERS:
            raise ValueError(
                f"provider must be one of: {', '.join(EXTERNAL_PROVIDERS)}"
            )
        subject = (subject or "").strip()
        if not subject:
            raise ValueError("external identity subject is required")

        savi.external_identity_provider = provider
        savi.external_identity_subject = subject
        savi.external_identity_display = (display_name or subject).strip()
        savi.external_identity_metadata = metadata or {}
        savi.external_identity_linked_at = datetime.now()
        savi.external_identity_linked_by = linked_by
        savi.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(savi)
        return savi

    def detach_external_identity(
        self, tenant_id: str, team_id: str, savi_id: str
    ) -> SaviInstance:
        savi = self._require_savi(tenant_id, team_id, savi_id)
        savi.external_identity_provider = None
        savi.external_identity_subject = None
        savi.external_identity_display = None
        savi.external_identity_metadata = None
        savi.external_identity_linked_at = None
        savi.external_identity_linked_by = None
        savi.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(savi)
        return savi

    # --- Coding agent seat -------------------------------------------------

    def get_seat(
        self, tenant_id: str, team_id: str, savi_id: str
    ) -> Optional[SaviCodingAgentSeat]:
        self._require_savi(tenant_id, team_id, savi_id)
        return (
            self.db.query(SaviCodingAgentSeat)
            .filter(
                SaviCodingAgentSeat.tenant_id == tenant_id,
                SaviCodingAgentSeat.savi_instance_id == savi_id,
            )
            .first()
        )

    def upsert_seat(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        *,
        agent_type: str,
        execution_mode: str = "cli",
        status: str = "pending_license",
        external_seat_ref: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        secret: Optional[str] = None,
        clear_secret: bool = False,
        created_by: Optional[str] = None,
    ) -> SaviCodingAgentSeat:
        self._require_savi(tenant_id, team_id, savi_id)
        agent_type = (agent_type or "").lower().strip()
        if agent_type not in AGENT_TYPES:
            raise ValueError(f"agent_type must be one of: {', '.join(AGENT_TYPES)}")
        execution_mode = (execution_mode or "cli").lower().strip()
        if execution_mode not in EXECUTION_MODES:
            raise ValueError(
                f"execution_mode must be one of: {', '.join(EXECUTION_MODES)}"
            )
        status = (status or "pending_license").lower().strip()
        if status not in SEAT_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(SEAT_STATUSES)}")

        seat = self.get_seat(tenant_id, team_id, savi_id)
        if seat:
            seat.agent_type = agent_type
            seat.execution_mode = execution_mode
            seat.status = status
            seat.external_seat_ref = (external_seat_ref or "").strip() or None
            seat.config_json = {**(seat.config_json or {}), **(config or {})}
            seat.updated_at = datetime.now()
            if secret:
                seat.secret_encrypted = encrypt_token(secret)
            elif clear_secret:
                seat.secret_encrypted = None
            self.db.commit()
            self.db.refresh(seat)
            return seat

        seat = SaviCodingAgentSeat(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            team_id=team_id,
            savi_instance_id=savi_id,
            agent_type=agent_type,
            execution_mode=execution_mode,
            status=status,
            external_seat_ref=(external_seat_ref or "").strip() or None,
            config_json=config or {},
            secret_encrypted=encrypt_token(secret) if secret else None,
            created_by=created_by,
        )
        self.db.add(seat)
        self.db.commit()
        self.db.refresh(seat)
        return seat

    def disable_seat(
        self, tenant_id: str, team_id: str, savi_id: str
    ) -> Optional[SaviCodingAgentSeat]:
        seat = self.get_seat(tenant_id, team_id, savi_id)
        if not seat:
            return None
        seat.status = "disabled"
        seat.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(seat)
        return seat

    def get_secret(self, seat: SaviCodingAgentSeat) -> Optional[str]:
        if not seat.secret_encrypted:
            return None
        return decrypt_token(seat.secret_encrypted)

    def resolve_execution_mode(
        self, tenant_id: str, team_id: str, savi_id: str
    ) -> str:
        """Prefer active seat execution_mode; else tenant code-gen; else env."""
        from app.core.config import settings
        from app.services.llm_routing import resolve_code_generation

        seat = self.get_seat(tenant_id, team_id, savi_id)
        if seat and seat.status == "active" and seat.execution_mode:
            mode = (seat.execution_mode or "").lower().strip()
            if mode == "cli":
                return _CLI_MODE_BY_AGENT.get(
                    (seat.agent_type or "").lower(), "heuristic"
                )
            return mode

        code = resolve_code_generation(self.db, tenant_id)
        if code.get("provider") in ("claude", "github_copilot"):
            return code["execution_mode"]

        return (settings.SAVI_CODING_AGENT or "heuristic").lower()

    def seat_to_dict(self, seat: SaviCodingAgentSeat) -> Dict[str, Any]:
        return {
            "id": seat.id,
            "savi_instance_id": seat.savi_instance_id,
            "agent_type": seat.agent_type,
            "status": seat.status,
            "external_seat_ref": seat.external_seat_ref,
            "execution_mode": seat.execution_mode,
            "config": seat.config_json or {},
            "has_secret": bool(seat.secret_encrypted),
            "created_at": seat.created_at.isoformat() if seat.created_at else None,
            "updated_at": seat.updated_at.isoformat() if seat.updated_at else None,
        }

    def external_identity_dict(self, savi: SaviInstance) -> Optional[Dict[str, Any]]:
        if not savi.external_identity_subject:
            return None
        return {
            "provider": savi.external_identity_provider,
            "subject": savi.external_identity_subject,
            "display_name": savi.external_identity_display,
            "metadata": savi.external_identity_metadata or {},
            "linked_at": savi.external_identity_linked_at.isoformat()
            if savi.external_identity_linked_at
            else None,
            "linked_by": savi.external_identity_linked_by,
        }

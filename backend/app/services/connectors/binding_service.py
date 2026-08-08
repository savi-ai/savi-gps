"""CRUD for per-Savi connector bindings (T5)."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import SaviConnectorBinding
from app.services.connectors.base import CONNECTOR_TYPES
from app.services.intelligence.token_cipher import decrypt_token, encrypt_token
from app.services.savi_roster_service import SaviRosterService
from app.services.team_service import TeamService


class SaviConnectorBindingService:
    def __init__(self, db: Session):
        self.db = db

    def list_for_savi(
        self, tenant_id: str, team_id: str, savi_id: str
    ) -> List[SaviConnectorBinding]:
        self._require_savi(tenant_id, team_id, savi_id)
        return (
            self.db.query(SaviConnectorBinding)
            .filter(
                SaviConnectorBinding.tenant_id == tenant_id,
                SaviConnectorBinding.team_id == team_id,
                SaviConnectorBinding.savi_instance_id == savi_id,
            )
            .order_by(SaviConnectorBinding.connector_type.asc())
            .all()
        )

    def get(
        self, tenant_id: str, binding_id: str
    ) -> Optional[SaviConnectorBinding]:
        return (
            self.db.query(SaviConnectorBinding)
            .filter(
                SaviConnectorBinding.id == binding_id,
                SaviConnectorBinding.tenant_id == tenant_id,
            )
            .first()
        )

    def get_active(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        connector_type: str,
    ) -> Optional[SaviConnectorBinding]:
        return (
            self.db.query(SaviConnectorBinding)
            .filter(
                SaviConnectorBinding.tenant_id == tenant_id,
                SaviConnectorBinding.team_id == team_id,
                SaviConnectorBinding.savi_instance_id == savi_id,
                SaviConnectorBinding.connector_type == connector_type,
                SaviConnectorBinding.status == "active",
            )
            .first()
        )

    def upsert(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        connector_type: str,
        *,
        config: Optional[Dict[str, Any]] = None,
        secret: Optional[str] = None,
        clear_secret: bool = False,
        status: str = "active",
        created_by: Optional[str] = None,
    ) -> SaviConnectorBinding:
        self._require_savi(tenant_id, team_id, savi_id)
        ctype = (connector_type or "").lower()
        if ctype not in CONNECTOR_TYPES:
            raise ValueError(
                f"connector_type must be one of: {', '.join(CONNECTOR_TYPES)}"
            )
        if status not in ("active", "disabled"):
            raise ValueError("status must be active or disabled")

        config = dict(config or {})
        # Ensure webhook secret for inbound connectors
        if ctype in ("jira", "slack") and not config.get("webhook_token"):
            config["webhook_token"] = secrets.token_urlsafe(24)

        existing = (
            self.db.query(SaviConnectorBinding)
            .filter(
                SaviConnectorBinding.savi_instance_id == savi_id,
                SaviConnectorBinding.connector_type == ctype,
            )
            .first()
        )
        if existing:
            if existing.tenant_id != tenant_id or existing.team_id != team_id:
                raise ValueError("Connector binding mismatch")
            existing.config_json = {**(existing.config_json or {}), **config}
            existing.status = status
            existing.updated_at = datetime.now()
            if secret:
                existing.secret_encrypted = encrypt_token(secret)
            elif clear_secret:
                existing.secret_encrypted = None
            self.db.commit()
            self.db.refresh(existing)
            return existing

        binding = SaviConnectorBinding(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            team_id=team_id,
            savi_instance_id=savi_id,
            connector_type=ctype,
            status=status,
            config_json=config,
            secret_encrypted=encrypt_token(secret) if secret else None,
            created_by=created_by,
        )
        self.db.add(binding)
        self.db.commit()
        self.db.refresh(binding)
        return binding

    def disable_all_for_savi(
        self, tenant_id: str, team_id: str, savi_id: str, *, commit: bool = True
    ) -> int:
        """Disable every connector binding for a Savi (deprovision / revoke)."""
        self._require_savi(tenant_id, team_id, savi_id)
        rows = (
            self.db.query(SaviConnectorBinding)
            .filter(
                SaviConnectorBinding.tenant_id == tenant_id,
                SaviConnectorBinding.savi_instance_id == savi_id,
            )
            .all()
        )
        n = 0
        for binding in rows:
            if binding.status != "disabled":
                binding.status = "disabled"
                n += 1
            cfg = dict(binding.config_json or {})
            # Rotate webhook token so inbound hooks stop matching
            if "webhook_token" in cfg:
                cfg["webhook_token"] = secrets.token_urlsafe(24)
                cfg["revoked_at_deprovision"] = True
            binding.config_json = cfg
            binding.updated_at = datetime.now()
            # Drop stored secrets on revoke
            binding.secret_encrypted = None
        if commit:
            self.db.commit()
        return n

    def disable(self, tenant_id: str, binding_id: str) -> SaviConnectorBinding:
        binding = self.get(tenant_id, binding_id)
        if not binding:
            raise ValueError("Connector binding not found")
        binding.status = "disabled"
        binding.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(binding)
        return binding

    def get_secret(self, binding: SaviConnectorBinding) -> Optional[str]:
        if not binding.secret_encrypted:
            return None
        return decrypt_token(binding.secret_encrypted)

    def to_dict(self, binding: SaviConnectorBinding) -> Dict[str, Any]:
        cfg = dict(binding.config_json or {})
        # Never expose encrypted blob; hint if secret present
        return {
            "id": binding.id,
            "team_id": binding.team_id,
            "savi_instance_id": binding.savi_instance_id,
            "connector_type": binding.connector_type,
            "status": binding.status,
            "config": cfg,
            "has_secret": bool(binding.secret_encrypted),
            "created_at": binding.created_at.isoformat() if binding.created_at else None,
            "updated_at": binding.updated_at.isoformat() if binding.updated_at else None,
        }

    def _require_savi(self, tenant_id: str, team_id: str, savi_id: str) -> None:
        team = TeamService(self.db).get_team(tenant_id, team_id)
        if not team:
            raise ValueError("Team not found")
        savi = SaviRosterService(self.db).get(tenant_id, savi_id)
        if not savi or savi.team_id != team_id:
            raise ValueError("Savi instance not found on this team")

"""Capability guards for Portfolio pillar (Phase 1+)."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.database import User
from app.core.auth import has_permission
from app.services.tenant_config_service import TenantConfigService


def require_portfolio(user: User, db: Session) -> None:
    if not user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")
    caps = TenantConfigService(db).get_capabilities(user.tenant_id)
    if not caps.get("portfolio"):
        raise HTTPException(status_code=403, detail="Portfolio is not enabled for this tenant")
    if not has_permission(user, "can_view_portfolio", db):
        raise HTTPException(status_code=403, detail="Permission denied: cannot view portfolio")

"""Shared Intelligence API dependencies."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.auth import has_permission
from app.core.database import User
from app.services.tenant_config_service import TenantConfigService


def require_intelligence(user: User, db: Session) -> None:
    if not user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")
    caps = TenantConfigService(db).get_capabilities(user.tenant_id)
    if not caps.get("intelligence"):
        raise HTTPException(status_code=403, detail="Intelligence is not enabled for this tenant")
    if not has_permission(user, "can_use_intelligence", db):
        raise HTTPException(status_code=403, detail="Permission denied")

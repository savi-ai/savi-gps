"""Tenant capability and onboarding configuration API."""
from typing import Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db, User
from app.core.auth import get_current_user, has_permission
from app.services.tenant_config_service import (
    TenantConfigService,
    ONBOARDING_PATHS,
)
from app.core.logger import logger

router = APIRouter(prefix="/tenant-config", tags=["Tenant Config"])


class OnboardingRequest(BaseModel):
    path: str = Field(..., description="wiki_only | modernization | full")


class CapabilitiesUpdateRequest(BaseModel):
    build: Optional[bool] = None
    intelligence: Optional[bool] = None
    fleet: Optional[bool] = None
    modernize: Optional[bool] = None
    portfolio: Optional[bool] = None


class AssessmentSettingsUpdateRequest(BaseModel):
    auto_assess_on_repo_index: Optional[bool] = None
    auto_assess_on_application_analysis: Optional[bool] = None


@router.get("/me")
async def get_my_tenant_config(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")
    service = TenantConfigService(db)
    config = service.get_or_create(user.tenant_id)
    return service.to_dict(config)


@router.patch("/assessment-settings")
async def update_assessment_settings(
    request: AssessmentSettingsUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Toggle whether assessment auto-runs after repo / application analysis."""
    if not user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")
    if not has_permission(user, "can_manage_tenant_config", db):
        raise HTTPException(status_code=403, detail="Admin permission required")

    updates = {}
    if request.auto_assess_on_repo_index is not None:
        updates["auto_assess_on_repo_index"] = request.auto_assess_on_repo_index
    if request.auto_assess_on_application_analysis is not None:
        updates["auto_assess_on_application_analysis"] = (
            request.auto_assess_on_application_analysis
        )
    service = TenantConfigService(db)
    config = service.update_assessment_settings(user.tenant_id, updates)
    return service.to_dict(config)


@router.post("/onboarding")
async def complete_onboarding(
    request: OnboardingRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")
    if not has_permission(user, "can_manage_tenant_config", db):
        raise HTTPException(status_code=403, detail="Admin permission required")

    if request.path not in ONBOARDING_PATHS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid path. Choose one of: {', '.join(ONBOARDING_PATHS)}",
        )

    service = TenantConfigService(db)
    try:
        config = service.set_onboarding_path(user.tenant_id, request.path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(f"Tenant {user.tenant_id} onboarding set to {request.path}")
    return service.to_dict(config)


@router.patch("/capabilities")
async def update_capabilities(
    request: CapabilitiesUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")
    if not has_permission(user, "can_manage_tenant_config", db):
        raise HTTPException(status_code=403, detail="Admin permission required")

    updates: Dict[str, bool] = {}
    if request.build is not None:
        updates["build"] = request.build
    if request.intelligence is not None:
        updates["intelligence"] = request.intelligence
    if request.fleet is not None:
        updates["fleet"] = request.fleet
    if request.modernize is not None:
        updates["modernize"] = request.modernize
    if request.portfolio is not None:
        updates["portfolio"] = request.portfolio

    service = TenantConfigService(db)
    config = service.update_capabilities(user.tenant_id, updates)
    return service.to_dict(config)

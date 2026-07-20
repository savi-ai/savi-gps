"""SOP API endpoints"""
from fastapi import APIRouter, Query, HTTPException, Depends
from typing import List, Optional
from sqlalchemy.orm import Session
from app.core.models import (
    SOP, SOPValidationRequest, SOPValidationResponse,
    SOPCategory, ArtifactType
)
from app.services.sop_service import sop_service
from app.services.sop_agent import sop_agent
from app.core.auth import get_current_user, has_permission
from app.core.database import get_db, User
from app.core.logger import logger

router = APIRouter(prefix="/sops", tags=["SOPs"])


@router.get("", response_model=List[SOP])
async def list_sops(
    category: Optional[SOPCategory] = Query(None),
    applies_to: Optional[ArtifactType] = Query(None),
    tags: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all SOPs, optionally filtered by category, applies_to, or tags
    
    Accessible to all authenticated users
    """
    tag_list = tags.split(",") if tags else None
    sops = sop_service.filter_sops(
        category=category,
        applies_to=applies_to,
        tags=tag_list
    )
    return sops


@router.get("/{sop_id}", response_model=SOP)
async def get_sop(
    sop_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific SOP by ID
    
    Accessible to all authenticated users
    """
    sop = sop_service.get_sop(sop_id)
    if not sop:
        raise HTTPException(status_code=404, detail=f"SOP {sop_id} not found")
    return sop


@router.post("/validate", response_model=SOPValidationResponse)
async def validate_artifact(
    request: SOPValidationRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Validate an artifact against applicable SOPs
    
    Accessible to all authenticated users
    """
    try:
        result = await sop_agent.validate(request)
        return result
    except Exception as e:
        logger.error(f"Error validating artifact: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reload")
async def reload_sops(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reload SOPs from directory (admin only)"""
    if not has_permission(user, "can_manage_policies", db):
        raise HTTPException(status_code=403, detail="Permission denied. Admin access required.")
    
    try:
        sop_service.reload_sops()
        return {"message": "SOPs reloaded successfully", "count": len(sop_service.get_all_sops())}
    except Exception as e:
        logger.error(f"Error reloading SOPs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

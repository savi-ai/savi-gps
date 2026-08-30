"""Analysis attribute configuration and fleet-wide search API."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps.intelligence_deps import require_intelligence
from app.core.auth import get_current_user, has_permission
from app.core.database import User, get_db
from app.services.intelligence.analysis_config_service import AnalysisConfigService
from app.services.intelligence.repo_ingestion_service import RepoIngestionService

router = APIRouter(prefix="/intelligence/analysis-config", tags=["Analysis Config"])


class CreateAttributeRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="general", max_length=50)
    data_type: str = Field(default="string", max_length=20)
    extraction_hint: Optional[str] = Field(None, max_length=2000)
    description: Optional[str] = None
    use_in_assessment: bool = False
    assessment_weight: int = Field(default=1, ge=1, le=5)
    assessment_rules: Optional[dict] = None
    recommendation_template: Optional[str] = Field(None, max_length=2000)
    remediation_scope: Optional[str] = Field(
        default="either",
        pattern=r"^(simple_fix|modernization|either)$",
    )


class UpdateAttributeRequest(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    data_type: Optional[str] = None
    extraction_hint: Optional[str] = None
    is_active: Optional[bool] = None
    is_searchable: Optional[bool] = None
    use_in_assessment: Optional[bool] = None
    assessment_weight: Optional[int] = Field(None, ge=1, le=5)
    assessment_rules: Optional[dict] = None
    recommendation_template: Optional[str] = Field(None, max_length=2000)
    remediation_scope: Optional[str] = Field(
        None,
        pattern=r"^(simple_fix|modernization|either)$",
    )


def _require_admin_config(user: User, db: Session) -> None:
    if not has_permission(user, "can_manage_tenant_config", db):
        raise HTTPException(status_code=403, detail="Admin permission required")


@router.get("/definitions")
async def list_definitions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    active_only: bool = True,
):
    require_intelligence(user, db)
    svc = AnalysisConfigService(db)
    svc.seed_defaults(user.tenant_id)
    return {"definitions": svc.list_definitions(user.tenant_id, active_only=active_only)}


@router.post("/definitions")
async def create_definition(
    request: CreateAttributeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    _require_admin_config(user, db)
    svc = AnalysisConfigService(db)
    try:
        defn = svc.create_definition(
            tenant_id=user.tenant_id,
            key=request.key,
            label=request.label,
            category=request.category,
            data_type=request.data_type,
            extraction_hint=request.extraction_hint,
            description=request.description,
            use_in_assessment=request.use_in_assessment,
            assessment_weight=request.assessment_weight,
            assessment_rules=request.assessment_rules,
            recommendation_template=request.recommendation_template,
            remediation_scope=request.remediation_scope,
            created_by=user.id,
        )
        return defn
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/assessment-definitions")
async def list_assessment_definitions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Definitions flagged for modernization assessment signals."""
    require_intelligence(user, db)
    svc = AnalysisConfigService(db)
    return {"definitions": svc.list_assessment_definitions(user.tenant_id)}


@router.patch("/definitions/{definition_id}")
async def update_definition(
    definition_id: str,
    request: UpdateAttributeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    _require_admin_config(user, db)
    svc = AnalysisConfigService(db)
    try:
        return svc.update_definition(
            user.tenant_id, definition_id, request.model_dump(exclude_unset=True)
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/definitions/seed-defaults")
async def seed_defaults(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    _require_admin_config(user, db)
    count = AnalysisConfigService(db).seed_defaults(user.tenant_id, created_by=user.id)
    return {"created": count}


@router.get("/search")
async def search_fleet_attributes(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    attribute_key: Optional[str] = Query(None),
    value_contains: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    require_intelligence(user, db)
    results = AnalysisConfigService(db).search_repositories(
        user.tenant_id,
        attribute_key=attribute_key,
        value_contains=value_contains,
        limit=limit,
    )
    return {"results": results, "count": len(results)}


@router.get("/repos/{repo_id}/attributes")
async def list_repo_attributes(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    if not ingestion.get_repository(user.tenant_id, repo_id):
        raise HTTPException(status_code=404, detail="Repository not found")
    attrs = AnalysisConfigService(db).list_repository_attributes(user.tenant_id, repo_id)
    return {"attributes": attrs}

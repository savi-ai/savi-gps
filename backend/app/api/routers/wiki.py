"""Wiki governance API — citation verification and draft→live approval."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps.intelligence_deps import require_intelligence
from app.core.auth import get_current_user, has_permission
from app.core.database import User, get_db
from app.services.intelligence.repo_ingestion_service import RepoIngestionService
from app.services.intelligence.wiki_governance_service import WikiGovernanceService

router = APIRouter(prefix="/intelligence", tags=["Wiki Governance"])


class WikiReviewRequest(BaseModel):
    notes: Optional[str] = Field(None, max_length=2000)


class WikiRejectRequest(BaseModel):
    feedback: Optional[str] = Field(None, max_length=2000)


def _require_wiki_approve(user: User, db: Session) -> None:
    if not has_permission(user, "can_approve_wiki", db):
        raise HTTPException(status_code=403, detail="Wiki approval permission required")


def _get_repo_or_404(db: Session, tenant_id: str, repo_id: str):
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.get("/repos/{repo_id}/wiki-quality")
async def wiki_quality_summary(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    _get_repo_or_404(db, user.tenant_id, repo_id)
    return WikiGovernanceService(db).repo_quality_summary(repo_id)


@router.get("/repos/{repo_id}/pages/{slug}/claims")
async def list_wiki_claims(
    repo_id: str,
    slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    _get_repo_or_404(db, user.tenant_id, repo_id)
    gov = WikiGovernanceService(db)
    page = gov._get_page(repo_id, slug)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    return {"claims": gov.list_claims(page.id)}


@router.post("/repos/{repo_id}/pages/{slug}/verify")
async def verify_wiki_citations(
    repo_id: str,
    slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    _get_repo_or_404(db, user.tenant_id, repo_id)
    gov = WikiGovernanceService(db)
    try:
        return gov.verify_page_citations(repo_id, slug)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/repos/{repo_id}/pages/{slug}/approve")
async def approve_wiki_page(
    repo_id: str,
    slug: str,
    request: WikiReviewRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    _require_wiki_approve(user, db)
    _get_repo_or_404(db, user.tenant_id, repo_id)
    gov = WikiGovernanceService(db)
    try:
        return gov.approve_page(repo_id, slug, user.id, request.notes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/repos/{repo_id}/pages/{slug}/reject")
async def reject_wiki_page(
    repo_id: str,
    slug: str,
    request: WikiRejectRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    _require_wiki_approve(user, db)
    _get_repo_or_404(db, user.tenant_id, repo_id)
    gov = WikiGovernanceService(db)
    try:
        return gov.reject_page(repo_id, slug, user.id, request.feedback)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

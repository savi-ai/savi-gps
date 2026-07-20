"""GitHub discovery and bulk import for Intelligence."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, has_permission
from app.core.database import User, get_db
from app.services.intelligence.github_client import GitHubClient, GitHubApiError, PERSONAL_ORG_KEY
from app.services.intelligence.github_credential_service import GitHubCredentialService
from app.services.intelligence.indexer_service import IndexerService
from app.services.intelligence.repo_ingestion_service import RepoIngestionService
from app.services.tenant_config_service import TenantConfigService
from app.api.deps.intelligence_deps import require_intelligence

router = APIRouter(prefix="/intelligence/github", tags=["Intelligence — GitHub"])


class ValidateTokenRequest(BaseModel):
    token: str = Field(..., min_length=10)


class SaveCredentialRequest(BaseModel):
    token: str = Field(..., min_length=10)
    label: str = Field(default="GitHub PAT", max_length=100)


class DiscoverRequest(BaseModel):
    token: Optional[str] = Field(None, min_length=10)
    credential_id: Optional[str] = None
    orgs: List[str] = Field(default_factory=list, description="Org logins to list repos from")
    include_personal: bool = True


class RepoSelection(BaseModel):
    owner: str
    name: str
    full_name: Optional[str] = None
    org: Optional[str] = None
    default_branch: str = "main"
    html_url: Optional[str] = None
    clone_url: Optional[str] = None


class ImportReposRequest(BaseModel):
    token: Optional[str] = Field(None, min_length=10)
    credential_id: Optional[str] = None
    save_credential: bool = False
    credential_label: str = Field(default="GitHub PAT", max_length=100)
    repos: List[RepoSelection] = Field(..., min_length=1)
    auto_index: bool = True
    application_id: Optional[str] = None
    application_name: Optional[str] = Field(
        None,
        max_length=200,
        description="Create a new application and assign imported repos",
    )


async def _client_from_request(
    db: Session,
    tenant_id: str,
    token: Optional[str],
    credential_id: Optional[str],
) -> GitHubClient:
    if credential_id:
        cred_svc = GitHubCredentialService(db)
        cred = cred_svc.get_credential(tenant_id, credential_id)
        if not cred:
            raise HTTPException(status_code=404, detail="GitHub credential not found")
        return await cred_svc.client_for_credential(cred)
    if token:
        return GitHubClient(token)
    raise HTTPException(status_code=400, detail="Provide token or credential_id")


@router.post("/validate-token")
async def validate_token(
    request: ValidateTokenRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    client = GitHubClient(request.token)
    try:
        info = await client.validate_token()
        orgs = await client.list_orgs()
    except GitHubApiError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return {
        "valid": True,
        "user": info,
        "orgs": orgs,
        "personal_key": PERSONAL_ORG_KEY,
    }


@router.get("/credentials")
async def list_credentials(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    svc = GitHubCredentialService(db)
    creds = svc.list_credentials(user.tenant_id)
    return {"credentials": [svc.to_dict(c) for c in creds]}


@router.post("/credentials")
async def save_credential(
    request: SaveCredentialRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    if not has_permission(user, "can_manage_tenant_config", db):
        raise HTTPException(status_code=403, detail="Admin permission required to save credentials")
    svc = GitHubCredentialService(db)
    try:
        cred = await svc.validate_and_store(
            user.tenant_id, request.token, request.label, user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return svc.to_dict(cred)


@router.delete("/credentials/{credential_id}")
async def delete_credential(
    credential_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    if not has_permission(user, "can_manage_tenant_config", db):
        raise HTTPException(status_code=403, detail="Admin permission required")
    svc = GitHubCredentialService(db)
    if not svc.deactivate(user.tenant_id, credential_id):
        raise HTTPException(status_code=404, detail="Credential not found")
    return {"status": "deactivated"}


@router.get("/credentials/{credential_id}/orgs")
async def list_orgs_for_credential(
    credential_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    cred_svc = GitHubCredentialService(db)
    cred = cred_svc.get_credential(user.tenant_id, credential_id)
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    client = await cred_svc.client_for_credential(cred)
    orgs = await client.list_orgs()
    return {"orgs": orgs, "personal_key": PERSONAL_ORG_KEY}


@router.post("/discover")
async def discover_repos(
    request: DiscoverRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List repos for selected orgs (supports multiple orgs + personal namespace)."""
    require_intelligence(user, db)
    client = await _client_from_request(
        db, user.tenant_id, request.token, request.credential_id
    )
    orgs = request.orgs
    if not orgs and not request.include_personal:
        raise HTTPException(status_code=400, detail="Select at least one org or enable personal repos")

    try:
        groups = await client.discover_repos_for_orgs(orgs, request.include_personal)
        total = sum(len(g["repos"]) for g in groups)
    except GitHubApiError as e:
        raise HTTPException(status_code=400, detail=e.message)

    return {"groups": groups, "total_repos": total}


@router.post("/import")
async def import_repos(
    request: ImportReposRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bulk connect selected repos; optionally save PAT and auto-start indexing."""
    require_intelligence(user, db)

    credential_id = request.credential_id

    # Store PAT when provided so private repo clones work during indexing
    if request.token and not credential_id:
        cred_svc = GitHubCredentialService(db)
        try:
            cred = await cred_svc.validate_and_store(
                user.tenant_id,
                request.token,
                request.credential_label or "GitHub import",
                user.id,
            )
            credential_id = cred.id
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif request.save_credential and request.token and not credential_id:
        pass  # handled above

    ingestion = RepoIngestionService(db)
    selections = []
    for r in request.repos:
        full_name = r.full_name or f"{r.owner}/{r.name}"
        selections.append(
            {
                "owner": r.owner,
                "name": r.name,
                "full_name": full_name,
                "org": r.org,
                "default_branch": r.default_branch,
                "html_url": r.html_url or f"https://github.com/{full_name}",
            }
        )

    result = ingestion.bulk_import_github_repos(
        user.tenant_id,
        selections,
        credential_id,
        user.id,
    )

    if request.application_id or request.application_name:
        from app.services.intelligence.application_service import ApplicationService

        created_ids = [r["id"] for r in result.get("created", [])]
        if created_ids:
            try:
                app = ApplicationService(db).assign_repositories_to_application(
                    user.tenant_id,
                    created_ids,
                    application_id=request.application_id,
                    application_name=request.application_name,
                    created_by=user.id,
                )
                if app:
                    result["application"] = {
                        "id": app.id,
                        "name": app.name,
                    }
            except ValueError as e:
                result["application_error"] = str(e)

    index_runs = []
    if request.auto_index:
        indexer = IndexerService(db)
        for repo_dict in result["created"]:
            repo = ingestion.get_repository(user.tenant_id, repo_dict["id"])
            if repo:
                run = indexer.start_index(repo)
                index_runs.append({"repository_id": repo.id, "index_run_id": run.id})

    result["index_runs"] = index_runs
    result["credential_id"] = credential_id
    return result

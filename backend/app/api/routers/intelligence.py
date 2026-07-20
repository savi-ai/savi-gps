"""Savi GPS Intelligence API — repositories, indexing, wiki."""
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps.intelligence_deps import require_intelligence
from app.core.auth import get_current_user
from app.core.database import User, get_db
from app.services.intelligence.indexer_service import IndexerService
from app.services.intelligence.repo_ingestion_service import RepoIngestionService
from fastapi.responses import HTMLResponse

from app.services.intelligence.analysis_storage import load_analysis_artifacts, resolve_analysis_dir
from app.services.intelligence.wiki_agent_service import WikiAgentService
from app.services.intelligence.wiki_chat_service import WikiChatService
from app.services.intelligence.wiki_generation_service import WikiGenerationService
from app.services.intelligence.wiki_governance_service import WikiGovernanceService
from app.services.tenant_config_service import TenantConfigService

router = APIRouter(prefix="/intelligence", tags=["Intelligence"])


class ConnectRepositoryRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., min_length=1)
    provider: str = "github"
    default_branch: str = "main"
    include_globs: Optional[List[str]] = None
    exclude_globs: Optional[List[str]] = None
    application_id: Optional[str] = None


class ApplicationCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    domain: Optional[str] = None
    repository_ids: Optional[List[str]] = None


class ApplicationUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    domain: Optional[str] = None


class ApplicationRepoRequest(BaseModel):
    repository_id: str
    role: Optional[str] = None


class WikiChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1)


class WikiChatRequest(BaseModel):
    messages: List[WikiChatMessage] = Field(..., min_length=1)
    top_k: int = Field(default=8, ge=1, le=20)
    page_context: Optional[str] = Field(
        default=None,
        description="Optional current wiki page markdown for extra context",
    )


@router.get("/status")
async def intelligence_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    caps = TenantConfigService(db).get_capabilities(user.tenant_id) if user.tenant_id else {}
    return {
        "module": "intelligence",
        "phase": "2",
        "enabled": bool(caps.get("intelligence")),
        "features": [
            "github_multi_org_import",
            "indexing",
            "wiki_draft",
            "citation_verification",
            "wiki_approval",
            "drift_detection",
            "wiki_agent",
            "analysis_attributes",
            "wiki_chat",
            "hybrid_search",
            "call_graph",
            "kiro_specs",
            "applications",
            "application_scoped_chat",
            "application_scoped_search",
        ],
    }


@router.get("/repos")
async def list_repositories(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    service = RepoIngestionService(db)
    repos = service.list_repositories(user.tenant_id)
    return {
        "repositories": [
            service.to_dict(r, include_index_run=True, include_application=True)
            for r in repos
        ],
    }


@router.post("/repos")
async def connect_repository(
    request: ConnectRepositoryRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    service = RepoIngestionService(db)
    repo = service.connect_repository(
        tenant_id=user.tenant_id,
        name=request.name,
        url=request.url,
        provider=request.provider,
        default_branch=request.default_branch,
        include_globs=request.include_globs,
        exclude_globs=request.exclude_globs,
        created_by=user.id,
    )
    if request.application_id:
        from app.services.intelligence.application_service import ApplicationService

        try:
            ApplicationService(db).add_repository(
                user.tenant_id, request.application_id, repo.id
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return service.to_dict(repo, include_application=True)


@router.get("/repos/{repo_id}")
async def get_repository(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    service = RepoIngestionService(db)
    repo = service.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return service.to_dict(repo, include_application=True)


@router.get("/repos/{repo_id}/connections")
async def get_repository_connections(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cross-pillar links: applications, modernization plans, and Build projects."""
    require_intelligence(user, db)
    service = RepoIngestionService(db)
    if not service.get_repository(user.tenant_id, repo_id):
        raise HTTPException(status_code=404, detail="Repository not found")
    from app.services.intelligence.repository_connections_service import (
        get_repository_connections as build_connections,
    )

    return build_connections(db, user.tenant_id, repo_id)


@router.delete("/repos/{repo_id}")
async def delete_repository(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    service = RepoIngestionService(db)
    try:
        counts = service.delete_repository(user.tenant_id, repo_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "deleted": True,
        "repository_id": repo_id,
        "removed": counts,
    }


@router.post("/repos/{repo_id}/index")
async def start_index(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    indexer = IndexerService(db)
    run = indexer.start_index(repo)
    return indexer.to_status_dict(repo, run)


@router.get("/repos/{repo_id}/index-status")
async def index_status(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    indexer = IndexerService(db)
    run = indexer.get_latest_run(repo_id)
    return indexer.to_status_dict(repo, run)


@router.get("/repos/{repo_id}/pages")
async def list_wiki_pages(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    wiki = WikiGenerationService(db)
    gov = WikiGovernanceService(db)
    raw_pages = wiki.list_pages_for_repo(repo_id)
    summary = gov.repo_quality_summary(repo_id)
    by_slug = {p["slug"]: p for p in summary.get("pages", [])}
    pages = [{**p, **by_slug.get(p["slug"], {})} for p in raw_pages]
    return {"pages": pages}


@router.get("/repos/{repo_id}/pages/{slug}")
async def get_wiki_page(
    repo_id: str,
    slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    gov = WikiGovernanceService(db)
    page = gov.get_page_with_quality(repo_id, slug)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    return page


@router.get("/repos/{repo_id}/wiki-site")
async def get_wiki_site_meta(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    site = WikiAgentService(db).get_wiki_site(repo_id)
    analysis_dir = resolve_analysis_dir(repo)
    disk_artifacts = load_analysis_artifacts(analysis_dir)
    if not site and not disk_artifacts:
        raise HTTPException(status_code=404, detail="Wiki site not generated yet — run indexing")

    storage_meta = (site.summary_json or {}).get("_storage", {}) if site else {}
    return {
        "id": site.id if site else None,
        "repository_id": repo_id,
        "title": site.title if site else f"{repo.name} Wiki",
        "state": site.state if site else "unknown",
        "version": site.version if site else None,
        "generated_by": site.generated_by if site else disk_artifacts.get("meta", {}).get("generation_source"),
        "index_run_id": site.index_run_id if site else None,
        "created_at": site.created_at.isoformat() if site and site.created_at else None,
        "has_html": bool(site and site.html_content) or bool(disk_artifacts and disk_artifacts.get("wiki_html")),
        "analysis_dir": str(analysis_dir),
        "artifacts_on_disk": disk_artifacts is not None,
        "shell_succeeded": storage_meta.get("shell_succeeded"),
        "generation_source": storage_meta.get("generation_source") or (site.generated_by if site else None),
    }


@router.get("/repos/{repo_id}/wiki-site/html", response_class=HTMLResponse)
async def get_wiki_site_html(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    site = WikiAgentService(db).get_wiki_site(repo_id)
    if not site or not site.html_content:
        raise HTTPException(status_code=404, detail="Wiki HTML not available")
    return HTMLResponse(content=site.html_content)


@router.post("/repos/{repo_id}/chat")
async def wiki_chat(
    repo_id: str,
    request: WikiChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Grounded Q&A over indexed code chunks and wiki pages."""
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if repo.status not in ("ready", "error", "indexing"):
        raise HTTPException(
            status_code=400,
            detail="Repository must be indexed before chat. Run indexing first.",
        )

    chat_svc = WikiChatService(db)
    try:
        result = await chat_svc.ask(
            repo,
            [m.model_dump() for m in request.messages],
            top_k=request.top_k,
            page_context=request.page_context,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Chat failed: {str(e)[:500]}")

    return {
        "repository_id": repo_id,
        "repository_name": repo.name,
        **result,
    }


@router.get("/search")
async def hybrid_search(
    q: str,
    repository_id: Optional[str] = None,
    application_id: Optional[str] = None,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hybrid code + wiki search with RRF fusion."""
    require_intelligence(user, db)
    from app.services.intelligence.hybrid_search_service import HybridSearchService

    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter q is required")
    if repository_id and application_id:
        raise HTTPException(
            status_code=400,
            detail="Specify repository_id or application_id, not both",
        )
    limit = min(max(limit, 1), 50)
    try:
        return await HybridSearchService(db).search(
            user.tenant_id,
            q,
            repository_id=repository_id,
            application_id=application_id,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/repos/{repo_id}/graph/stats")
async def graph_stats(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    from app.services.intelligence.graph_query_service import GraphQueryService

    return GraphQueryService(db).get_graph_stats(repo)


@router.get("/repos/{repo_id}/graph/symbols")
async def graph_symbol_search(
    repo_id: str,
    q: str,
    limit: int = 25,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    from app.services.intelligence.graph_query_service import GraphQueryService

    return {
        "symbols": GraphQueryService(db).search_symbols(repo, q, limit=min(limit, 50)),
    }


@router.get("/repos/{repo_id}/analysis/domain-graph")
async def repo_domain_graph(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    from app.services.intelligence.domain_graph_service import DomainGraphService

    return DomainGraphService(db).get(repo)


@router.get("/repos/{repo_id}/graph/callees")
async def graph_callees(
    repo_id: str,
    symbol: str,
    limit: int = 30,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    from app.services.intelligence.graph_query_service import GraphQueryService

    return {
        "symbol": symbol,
        "callees": GraphQueryService(db).find_callees(repo, symbol, limit=min(limit, 50)),
    }


@router.get("/repos/{repo_id}/graph/blast-radius")
async def graph_blast_radius(
    repo_id: str,
    symbol: str,
    hops: int = 1,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    from app.services.intelligence.blast_radius_service import BlastRadiusService

    return BlastRadiusService(db).compute(
        repo,
        symbol,
        hops=min(max(hops, 1), 2),
    )


@router.get("/repos/{repo_id}/graph/blast-radius/anchors")
async def graph_blast_radius_anchors(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    from app.services.intelligence.blast_radius_service import BlastRadiusService

    return {"anchors": BlastRadiusService(db).list_anchors(repo)}


@router.get("/repos/{repo_id}/graph/callers")
async def graph_callers(
    repo_id: str,
    symbol: str,
    limit: int = 30,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    from app.services.intelligence.graph_query_service import GraphQueryService

    return {
        "symbol": symbol,
        "callers": GraphQueryService(db).find_callers(repo, symbol, limit=min(limit, 50)),
    }


@router.get("/specs")
async def list_tenant_specs(
    repository_id: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    from app.services.intelligence.spec_drift_service import SpecDriftService

    specs = SpecDriftService(db).list_specs_for_tenant(user.tenant_id, repository_id)
    return {"specs": specs, "count": len(specs)}


@router.get("/repos/{repo_id}/specs/drift")
async def repo_spec_drift(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    from app.services.intelligence.spec_drift_service import SpecDriftService

    return SpecDriftService(db).drift_summary(repo)


@router.post("/repos/{repo_id}/graph/rebuild")
async def rebuild_graph(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-clone and rebuild static call graph (no full wiki re-index)."""
    require_intelligence(user, db)
    ingestion = RepoIngestionService(db)
    repo = ingestion.get_repository(user.tenant_id, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    from app.services.intelligence.repo_clone_service import RepoCloneService
    from app.services.intelligence.indexer_service import IndexerService
    from app.services.intelligence.analysis_storage import get_analysis_dir, persist_graph_index
    from app.services.intelligence.structural_extractor import (
        build_graph_index,
        format_call_graph_for_wiki,
    )
    from app.services.intelligence.neo4j_graph_writer import sync_graph_to_neo4j
    from app.services.intelligence.spec_drift_service import persist_specs_index, scan_kiro_specs

    clone_svc = RepoCloneService()
    indexer = IndexerService(db)
    clone_path = None
    try:
        token = indexer._resolve_clone_token(repo)
        clone_path = clone_svc.shallow_clone(repo.url, repo.default_branch, token=token)
        graph = build_graph_index(clone_path)
        analysis_dir = get_analysis_dir(repo)
        persist_graph_index(analysis_dir, graph.to_dict())
        run = indexer.get_latest_run(repo.id)
        if run:
            sync_graph_to_neo4j(repo, run.id, graph)
        specs = scan_kiro_specs(clone_path)
        if specs:
            persist_specs_index(analysis_dir, specs)
        call_graph_md = format_call_graph_for_wiki(graph)
        if call_graph_md:
            (analysis_dir / "call_graph_context.md").write_text(call_graph_md, encoding="utf-8")
        return {"ok": True, "stats": graph.stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:500])
    finally:
        if clone_path:
            clone_svc.cleanup(clone_path)


# --- Cross-pillar next actions (S0) ---


@router.get("/next-actions")
async def list_next_actions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    from app.services.portfolio.next_actions_service import build_next_actions

    return {"next_actions": build_next_actions(db, user.tenant_id)}


# --- Estate Applications (multi-repo inventory) ---


@router.get("/applications")
async def list_applications(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    from app.services.intelligence.application_service import ApplicationService

    svc = ApplicationService(db)
    apps = svc.list_applications(user.tenant_id)
    return {
        "applications": [svc.to_summary_dict(a) for a in apps],
        "count": len(apps),
    }


@router.post("/applications")
async def create_application(
    request: ApplicationCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    from app.services.intelligence.application_service import ApplicationService

    try:
        app = ApplicationService(db).create_application(
            user.tenant_id,
            request.name,
            description=request.description,
            domain=request.domain,
            created_by=user.id,
            repository_ids=request.repository_ids,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApplicationService(db).to_detail_dict(app)


@router.get("/applications/{application_id}")
async def get_application(
    application_id: str,
    hub: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    from app.services.intelligence.application_hub_service import build_application_hub
    from app.services.intelligence.application_service import ApplicationService

    if hub:
        payload = build_application_hub(db, user.tenant_id, application_id)
        if not payload:
            raise HTTPException(status_code=404, detail="Application not found")
        return payload

    svc = ApplicationService(db)
    app = svc.get_application(user.tenant_id, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return svc.to_detail_dict(app)


@router.patch("/applications/{application_id}")
async def update_application(
    application_id: str,
    request: ApplicationUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    from app.services.intelligence.application_service import ApplicationService

    try:
        app = ApplicationService(db).update_application(
            user.tenant_id,
            application_id,
            name=request.name,
            description=request.description,
            domain=request.domain,
        )
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))
    return ApplicationService(db).to_detail_dict(app)


@router.delete("/applications/{application_id}")
async def delete_application(
    application_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    from app.services.intelligence.application_service import ApplicationService

    try:
        ApplicationService(db).delete_application(user.tenant_id, application_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"deleted": True, "application_id": application_id}


@router.post("/applications/{application_id}/repositories")
async def add_repository_to_application(
    application_id: str,
    request: ApplicationRepoRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    from app.services.intelligence.application_service import ApplicationService

    try:
        ApplicationService(db).add_repository(
            user.tenant_id,
            application_id,
            request.repository_id,
            role=request.role,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    app = ApplicationService(db).get_application(user.tenant_id, application_id)
    return ApplicationService(db).to_detail_dict(app)


@router.delete("/applications/{application_id}/repositories/{repository_id}")
async def remove_repository_from_application(
    application_id: str,
    repository_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    from app.services.intelligence.application_service import ApplicationService

    try:
        ApplicationService(db).remove_repository(
            user.tenant_id, application_id, repository_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"removed": True, "repository_id": repository_id}


@router.post("/applications/{application_id}/chat")
async def application_wiki_chat(
    application_id: str,
    request: WikiChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Grounded Q&A across all repositories in an application."""
    require_intelligence(user, db)
    from app.services.intelligence.application_service import ApplicationService
    from app.services.intelligence.chat_scope import ChatScope
    from app.services.intelligence.wiki_chat_service import WikiChatService

    if not ApplicationService(db).get_application(user.tenant_id, application_id):
        raise HTTPException(status_code=404, detail="Application not found")

    scope = ChatScope.application(application_id, user.tenant_id)
    chat_svc = WikiChatService(db)
    try:
        result = await chat_svc.ask_scope(
            scope,
            [m.model_dump() for m in request.messages],
            top_k=request.top_k,
            page_context=request.page_context,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Chat failed: {str(e)[:500]}")

    return {
        "application_id": application_id,
        **result,
    }


@router.get("/applications/{application_id}/analysis/service-map")
async def application_service_map(
    application_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    from app.services.intelligence.application_graph_service import ApplicationGraphService

    return ApplicationGraphService(db).compute_service_map(
        user.tenant_id, application_id
    )


@router.get("/applications/{application_id}/analysis/blast-radius")
async def application_blast_radius(
    application_id: str,
    repo_id: str,
    symbol: str,
    hops: int = 1,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    from app.services.intelligence.application_graph_service import ApplicationGraphService

    return ApplicationGraphService(db).application_blast_radius(
        user.tenant_id,
        application_id,
        repo_id,
        symbol,
        hops=min(max(hops, 1), 2),
    )


@router.get("/applications/{application_id}/wiki")
async def application_wiki(
    application_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Synthesized application wiki composed from member repository wikis."""
    require_intelligence(user, db)
    from app.services.intelligence.application_synthesizer import synthesize_application_wiki

    payload = synthesize_application_wiki(db, user.tenant_id, application_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Application not found")
    return payload


@router.get("/applications/{application_id}/wiki-site")
async def application_wiki_site_meta(
    application_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    from app.services.intelligence.application_synthesizer import synthesize_application_wiki

    payload = synthesize_application_wiki(db, user.tenant_id, application_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Application not found")
    return {
        "application_id": application_id,
        "title": f"{payload['application_name']} — Application Wiki",
        "repository_count": payload["repository_count"],
        "has_html": True,
        "cached": payload.get("cached", False),
        "members": payload.get("members", []),
    }


@router.get("/applications/{application_id}/wiki-site/html", response_class=HTMLResponse)
async def application_wiki_site_html(
    application_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_intelligence(user, db)
    from app.services.intelligence.application_synthesizer import synthesize_application_wiki_html

    html_doc = synthesize_application_wiki_html(db, user.tenant_id, application_id)
    if not html_doc:
        raise HTTPException(status_code=404, detail="Application not found")
    return HTMLResponse(content=html_doc)


@router.post("/tenant/chat")
async def tenant_wiki_chat(
    request: WikiChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Grounded Q&A across all indexed repositories in the tenant (capped)."""
    require_intelligence(user, db)
    from app.services.intelligence.chat_scope import ChatScope
    from app.services.intelligence.wiki_chat_service import WikiChatService

    scope = ChatScope.tenant(user.tenant_id)
    chat_svc = WikiChatService(db)
    try:
        result = await chat_svc.ask_scope(
            scope,
            [m.model_dump() for m in request.messages],
            top_k=request.top_k,
            page_context=request.page_context,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Chat failed: {str(e)[:500]}")

    return {"tenant_id": user.tenant_id, **result}

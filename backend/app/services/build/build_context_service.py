"""Resolve Intelligence substrate context for Build projects (Stitch 3)."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import (
    Project,
    Repository,
    RepositoryAnalysisAttribute,
    RepositoryProjectLink,
    RepositoryWikiSite,
)
from app.services.intelligence.analysis_storage import load_analysis_artifacts, resolve_analysis_dir
from app.services.intelligence.retrieval_service import RetrievalService


def attach_repositories(
    db: Session,
    tenant_id: str,
    project_id: str,
    repository_ids: List[str],
    link_type: str = "context",
) -> List[Dict[str, str]]:
    """Create repository links after validating tenant scope."""
    if not repository_ids:
        return []

    linked: List[Dict[str, str]] = []
    seen = set()
    for repo_id in repository_ids:
        if repo_id in seen:
            continue
        seen.add(repo_id)

        repo = (
            db.query(Repository)
            .filter(Repository.id == repo_id, Repository.tenant_id == tenant_id)
            .first()
        )
        if not repo:
            raise ValueError(f"Repository not found: {repo_id}")

        existing = (
            db.query(RepositoryProjectLink)
            .filter(
                RepositoryProjectLink.project_id == project_id,
                RepositoryProjectLink.repository_id == repo_id,
            )
            .first()
        )
        if existing:
            linked.append(
                {
                    "repository_id": repo_id,
                    "link_type": existing.link_type,
                    "id": existing.id,
                }
            )
            continue

        link = RepositoryProjectLink(
            id=str(uuid.uuid4()),
            repository_id=repo_id,
            project_id=project_id,
            link_type=link_type,
        )
        db.add(link)
        linked.append({"repository_id": repo_id, "link_type": link_type, "id": link.id})

    return linked


def _load_wiki_json(db: Session, repo: Repository) -> Optional[Dict[str, Any]]:
    artifacts = load_analysis_artifacts(resolve_analysis_dir(repo))
    if artifacts and artifacts.get("wiki_json"):
        return artifacts["wiki_json"]
    site = (
        db.query(RepositoryWikiSite)
        .filter(RepositoryWikiSite.repository_id == repo.id)
        .order_by(RepositoryWikiSite.updated_at.desc())
        .first()
    )
    if site and site.summary_json:
        return site.summary_json
    return None


def _repo_summary_dict(
    db: Session,
    repo: Repository,
    link_type: str,
    wiki_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    attrs = (
        db.query(RepositoryAnalysisAttribute)
        .filter(RepositoryAnalysisAttribute.repository_id == repo.id)
        .limit(20)
        .all()
    )
    diagrams = (wiki_json or {}).get("diagrams") or {}
    pages = (wiki_json or {}).get("pages") or {}
    overview = (wiki_json or {}).get("overview") or {}

    api_surface = (wiki_json or {}).get("api_surface")
    if isinstance(api_surface, list):
        api_text = "\n".join(
            f"- {item.get('method', 'GET')} {item.get('path', item.get('endpoint', ''))}: {item.get('description', '')}"
            for item in api_surface[:15]
            if isinstance(item, dict)
        )
    elif isinstance(api_surface, str):
        api_text = api_surface
    else:
        api_page = pages.get("api_surface") if isinstance(pages, dict) else None
        api_text = api_page if isinstance(api_page, str) else ""

    return {
        "id": repo.id,
        "name": repo.name,
        "github_full_name": repo.github_full_name,
        "url": repo.url,
        "link_type": link_type,
        "status": repo.status,
        "last_indexed_at": repo.last_indexed_at.isoformat() if repo.last_indexed_at else None,
        "overview": overview.get("description"),
        "tech_stack": (wiki_json or {}).get("tech_stack") or [],
        "business_logic_summary": (wiki_json or {}).get("business_logic_layer", {}).get("summary"),
        "analysis_attributes": [
            {
                "key": a.attribute_key,
                "label": a.attribute_label,
                "value": a.value_text,
            }
            for a in attrs
        ],
        "architecture_mermaid": diagrams.get("high_level_mermaid"),
        "api_surface": api_text[:4000] if api_text else None,
    }


class BuildContextService:
    def __init__(self, db: Session):
        self.db = db
        self.retrieval = RetrievalService(db)

    def get_project_links(self, project_id: str, tenant_id: str) -> List[RepositoryProjectLink]:
        return (
            self.db.query(RepositoryProjectLink)
            .join(Project, RepositoryProjectLink.project_id == Project.id)
            .join(Repository, RepositoryProjectLink.repository_id == Repository.id)
            .filter(
                RepositoryProjectLink.project_id == project_id,
                Project.tenant_id == tenant_id,
                Repository.tenant_id == tenant_id,
            )
            .all()
        )

    def get_linked_repositories(self, project_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        links = self.get_project_links(project_id, tenant_id)
        results: List[Dict[str, Any]] = []
        for link in links:
            repo = link.repository
            if not repo:
                continue
            wiki_json = _load_wiki_json(self.db, repo)
            results.append(_repo_summary_dict(self.db, repo, link.link_type, wiki_json))
        return results

    def preview_repositories_context(
        self, tenant_id: str, repository_ids: List[str]
    ) -> Dict[str, Any]:
        """Summarize wiki + index stats for repos before a project is created."""
        if not repository_ids:
            return {"repositories": [], "totals": {"wiki_sections": 0, "symbols": 0, "specs": 0}}

        from app.core.database import CodeChunk, WikiPage
        from app.services.intelligence.spec_drift_service import SpecDriftService

        repos_out: List[Dict[str, Any]] = []
        total_wiki = 0
        total_symbols = 0
        total_specs = 0
        spec_svc = SpecDriftService(self.db)

        for repo_id in repository_ids:
            repo = (
                self.db.query(Repository)
                .filter(Repository.id == repo_id, Repository.tenant_id == tenant_id)
                .first()
            )
            if not repo:
                continue

            wiki_json = _load_wiki_json(self.db, repo)
            summary = _repo_summary_dict(self.db, repo, "context", wiki_json)
            pages = (
                self.db.query(WikiPage)
                .filter(WikiPage.repository_id == repo_id)
                .count()
            )
            chunks = (
                self.db.query(CodeChunk)
                .filter(CodeChunk.repository_id == repo_id)
                .count()
            )
            drift = spec_svc.drift_summary(repo)
            spec_count = drift.get("spec_count") or 0

            overview = (summary.get("overview") or "")[:280]
            tech = summary.get("tech_stack") or []
            if isinstance(tech, list):
                tech_preview = ", ".join(str(t) for t in tech[:5])
            else:
                tech_preview = str(tech)[:120]

            symbol_estimate = chunks  # proxy until graph stats wired per-repo here

            repos_out.append(
                {
                    "id": repo.id,
                    "name": repo.github_full_name or repo.name,
                    "status": repo.status,
                    "overview_excerpt": overview,
                    "tech_stack_preview": tech_preview,
                    "wiki_page_count": pages,
                    "indexed_chunk_count": chunks,
                    "symbol_count": symbol_estimate,
                    "spec_count": spec_count,
                }
            )
            total_wiki += pages
            total_symbols += symbol_estimate
            total_specs += spec_count

        return {
            "repositories": repos_out,
            "totals": {
                "wiki_sections": total_wiki,
                "symbols": total_symbols,
                "specs": total_specs,
            },
        }

    async def build_query_context(
        self,
        project_id: str,
        tenant_id: str,
        query: str,
        *,
        top_k: int = 6,
    ) -> Dict[str, Any]:
        """Wiki summary + retrieved chunks for all linked repos (idea chat / agents)."""
        links = self.get_project_links(project_id, tenant_id)
        if not links:
            return {"repositories": [], "context_block": "", "sources": []}

        repos_out: List[Dict[str, Any]] = []
        all_sources: List[Dict[str, Any]] = []
        context_parts: List[str] = []

        for link in links:
            repo = link.repository
            if not repo:
                continue
            wiki_json = _load_wiki_json(self.db, repo)
            summary = _repo_summary_dict(self.db, repo, link.link_type, wiki_json)

            sources = await self.retrieval.retrieve(repo.id, query, top_k=top_k)
            wiki_summary = self.retrieval.get_wiki_summary_context(repo.id)
            source_dicts = RetrievalService.sources_to_dicts(sources)
            for s in source_dicts:
                s["repository_id"] = repo.id
                s["repository_name"] = repo.name
            all_sources.extend(source_dicts)

            summary["retrieved_sources"] = source_dicts
            repos_out.append(summary)

            block = [f"## Repository: {repo.github_full_name or repo.name} (link: {link.link_type})"]
            if wiki_summary:
                block.append(wiki_summary)
            if summary.get("api_surface"):
                block.append(f"### API surface\n{summary['api_surface']}")
            bl = summary.get("business_logic_summary")
            if bl:
                block.append(f"### Business logic\n{bl}")
            for src in sources[:top_k]:
                if src.source_type == "wiki":
                    block.append(f"### Wiki `{src.file_path}`\n{src.excerpt[:1500]}")
                else:
                    loc = f":{src.start_line}" if src.start_line else ""
                    block.append(f"### Code `{src.file_path}{loc}`\n{src.excerpt[:1200]}")
            context_parts.append("\n".join(block))

        context_block = "\n\n".join(context_parts)[:24000]
        return {
            "repositories": repos_out,
            "context_block": context_block,
            "sources": all_sources,
        }

    def get_architecture_context(self, project_id: str, tenant_id: str) -> str:
        """Static wiki excerpts for architecture generation (mermaid + API surface)."""
        links = self.get_project_links(project_id, tenant_id)
        if not links:
            return ""

        parts: List[str] = [
            "The Build project is linked to existing repositories. "
            "Align new architecture with these systems where relevant."
        ]
        for link in links:
            repo = link.repository
            if not repo:
                continue
            wiki_json = _load_wiki_json(self.db, repo)
            summary = _repo_summary_dict(self.db, repo, link.link_type, wiki_json)
            parts.append(f"\n## Existing system: {repo.github_full_name or repo.name}")
            if summary.get("overview"):
                parts.append(summary["overview"])
            if summary.get("architecture_mermaid"):
                parts.append(f"### High-level architecture (Mermaid)\n```mermaid\n{summary['architecture_mermaid']}\n```")
            if summary.get("api_surface"):
                parts.append(f"### API surface\n{summary['api_surface']}")
            bl = summary.get("business_logic_summary")
            if bl:
                parts.append(f"### Business logic\n{bl}")
        return "\n".join(parts)[:16000]

    def get_project_context_payload(self, project_id: str, tenant_id: str) -> Dict[str, Any]:
        project = (
            self.db.query(Project)
            .filter(Project.id == project_id, Project.tenant_id == tenant_id)
            .first()
        )
        if not project:
            raise ValueError("Project not found")
        repos = self.get_linked_repositories(project_id, tenant_id)
        return {
            "project_id": project_id,
            "pillar": project.pillar or "build",
            "repositories": repos,
            "repository_count": len(repos),
        }

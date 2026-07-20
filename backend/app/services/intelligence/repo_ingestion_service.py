"""Repository connection, bulk GitHub import, and deduplication."""
from __future__ import annotations

import shutil
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy.orm import Session

from app.core.database import (
    ApplicationRepository,
    CodeChunk,
    IndexRun,
    RepoAnalysisView,
    Repository,
    RepositoryAnalysisAttribute,
    RepositoryProjectLink,
    RepositoryWikiSite,
    WikiClaim,
    WikiPage,
)
from app.core.logger import logger
from app.services.intelligence.github_client import PERSONAL_ORG_KEY
from app.services.intelligence.analysis_storage import get_analysis_dir, get_legacy_analysis_dir
from app.services.intelligence.indexer_service import IndexerService

DEFAULT_EXCLUDES = [
    "node_modules/**",
    "dist/**",
    "build/**",
    ".git/**",
    "vendor/**",
    "**/.env*",
    "**/*.lock",
    "**/package-lock.json",
    "**/yarn.lock",
    "**/__pycache__/**",
    "**/.venv/**",
    "**/venv/**",
]


class RepoIngestionService:
    def __init__(self, db: Session):
        self.db = db

    def find_by_github_full_name(
        self, tenant_id: str, full_name: str
    ) -> Optional[Repository]:
        return (
            self.db.query(Repository)
            .filter(
                Repository.tenant_id == tenant_id,
                Repository.github_full_name == full_name,
            )
            .first()
        )

    def connect_repository(
        self,
        tenant_id: str,
        name: str,
        url: str,
        provider: str = "github",
        default_branch: str = "main",
        include_globs: Optional[List[str]] = None,
        exclude_globs: Optional[List[str]] = None,
        created_by: Optional[str] = None,
        github_owner: Optional[str] = None,
        github_repo: Optional[str] = None,
        github_org: Optional[str] = None,
        github_full_name: Optional[str] = None,
        github_credential_id: Optional[str] = None,
    ) -> Repository:
        if github_full_name:
            existing = self.find_by_github_full_name(tenant_id, github_full_name)
            if existing:
                logger.info(f"Repository {github_full_name} already connected — returning existing")
                return existing

        repo = Repository(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=name,
            provider=provider,
            url=url,
            github_owner=github_owner,
            github_repo=github_repo,
            github_org=github_org,
            github_full_name=github_full_name,
            github_credential_id=github_credential_id,
            default_branch=default_branch,
            include_globs=include_globs,
            exclude_globs=exclude_globs or list(DEFAULT_EXCLUDES),
            status="pending",
            created_by=created_by,
        )
        self.db.add(repo)
        self.db.commit()
        self.db.refresh(repo)
        logger.info(f"Connected repository {repo.id} ({name}) for tenant {tenant_id}")
        return repo

    def connect_from_github_selection(
        self,
        tenant_id: str,
        repo_data: Dict[str, Any],
        credential_id: Optional[str],
        created_by: Optional[str],
    ) -> Tuple[Repository, bool]:
        """Connect one GitHub repo. Returns (repository, was_created)."""
        full_name = repo_data.get("full_name") or f"{repo_data['owner']}/{repo_data['name']}"
        existing = self.find_by_github_full_name(tenant_id, full_name)
        if existing:
            return existing, False

        org = repo_data.get("org")
        github_org = None if org == PERSONAL_ORG_KEY else org

        repo = self.connect_repository(
            tenant_id=tenant_id,
            name=repo_data.get("name") or full_name.split("/")[-1],
            url=repo_data.get("html_url") or f"https://github.com/{full_name}",
            default_branch=repo_data.get("default_branch") or "main",
            created_by=created_by,
            github_owner=repo_data.get("owner"),
            github_repo=repo_data.get("name"),
            github_org=github_org,
            github_full_name=full_name,
            github_credential_id=credential_id,
        )
        return repo, True

    def bulk_import_github_repos(
        self,
        tenant_id: str,
        selections: List[Dict[str, Any]],
        credential_id: Optional[str],
        created_by: Optional[str],
    ) -> Dict[str, Any]:
        created: List[Repository] = []
        skipped: List[str] = []
        errors: List[Dict[str, str]] = []

        for item in selections:
            try:
                repo, was_created = self.connect_from_github_selection(
                    tenant_id, item, credential_id, created_by
                )
                if was_created:
                    created.append(repo)
                else:
                    skipped.append(repo.github_full_name or repo.name)
            except Exception as e:
                fn = item.get("full_name") or item.get("name") or "unknown"
                errors.append({"repo": fn, "error": str(e)})

        return {
            "created": [self.to_dict(r) for r in created],
            "skipped": skipped,
            "errors": errors,
            "created_count": len(created),
            "skipped_count": len(skipped),
        }

    def list_repositories(self, tenant_id: str) -> List[Repository]:
        return (
            self.db.query(Repository)
            .filter(Repository.tenant_id == tenant_id)
            .order_by(Repository.created_at.desc())
            .all()
        )

    def get_repository(self, tenant_id: str, repo_id: str) -> Optional[Repository]:
        return (
            self.db.query(Repository)
            .filter(Repository.id == repo_id, Repository.tenant_id == tenant_id)
            .first()
        )

    def delete_repository(self, tenant_id: str, repo_id: str) -> Dict[str, int]:
        """Remove a connected repository and all intelligence data (wiki, chunks, analysis)."""
        repo = self.get_repository(tenant_id, repo_id)
        if not repo:
            raise ValueError("Repository not found")

        counts: Dict[str, int] = {}

        page_ids = [
            row[0]
            for row in self.db.query(WikiPage.id)
            .filter(WikiPage.repository_id == repo_id)
            .all()
        ]
        if page_ids:
            counts["wiki_claims"] = (
                self.db.query(WikiClaim)
                .filter(WikiClaim.page_id.in_(page_ids))
                .delete(synchronize_session=False)
            )
        counts["wiki_pages"] = (
            self.db.query(WikiPage)
            .filter(WikiPage.repository_id == repo_id)
            .delete(synchronize_session=False)
        )
        counts["wiki_sites"] = (
            self.db.query(RepositoryWikiSite)
            .filter(RepositoryWikiSite.repository_id == repo_id)
            .delete(synchronize_session=False)
        )
        counts["analysis_attributes"] = (
            self.db.query(RepositoryAnalysisAttribute)
            .filter(RepositoryAnalysisAttribute.repository_id == repo_id)
            .delete(synchronize_session=False)
        )
        counts["analysis_views"] = (
            self.db.query(RepoAnalysisView)
            .filter(RepoAnalysisView.repository_id == repo_id)
            .delete(synchronize_session=False)
        )
        counts["code_chunks"] = (
            self.db.query(CodeChunk)
            .filter(CodeChunk.repository_id == repo_id)
            .delete(synchronize_session=False)
        )
        counts["index_runs"] = (
            self.db.query(IndexRun)
            .filter(IndexRun.repository_id == repo_id)
            .delete(synchronize_session=False)
        )
        counts["project_links"] = (
            self.db.query(RepositoryProjectLink)
            .filter(RepositoryProjectLink.repository_id == repo_id)
            .delete(synchronize_session=False)
        )
        counts["application_links"] = (
            self.db.query(ApplicationRepository)
            .filter(ApplicationRepository.repository_id == repo_id)
            .delete(synchronize_session=False)
        )

        for analysis_dir in (get_analysis_dir(repo), get_legacy_analysis_dir(repo)):
            if analysis_dir.is_dir():
                shutil.rmtree(analysis_dir, ignore_errors=True)
                counts["analysis_dir_removed"] = counts.get("analysis_dir_removed", 0) + 1
                logger.info(f"Removed analysis directory {analysis_dir}")

        self.db.delete(repo)
        self.db.commit()

        logger.info(
            f"Deleted repository {repo_id} for tenant {tenant_id}: "
            f"{counts.get('wiki_pages', 0)} wiki pages, "
            f"{counts.get('analysis_attributes', 0)} analysis attributes, "
            f"{counts.get('code_chunks', 0)} chunks"
        )
        return counts

    def _index_run_dict(self, run: Optional[IndexRun]) -> Optional[Dict[str, Any]]:
        if not run:
            return None
        return {
            "id": run.id,
            "status": run.status,
            "progress": run.progress,
            "error": run.error,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    def to_dict(
        self,
        repo: Repository,
        include_index_run: bool = False,
        include_application: bool = False,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": repo.id,
            "tenant_id": repo.tenant_id,
            "name": repo.name,
            "provider": repo.provider,
            "url": repo.url,
            "github_owner": repo.github_owner,
            "github_repo": repo.github_repo,
            "github_org": repo.github_org,
            "github_full_name": repo.github_full_name,
            "github_credential_id": repo.github_credential_id,
            "default_branch": repo.default_branch,
            "include_globs": repo.include_globs,
            "exclude_globs": repo.exclude_globs,
            "status": repo.status,
            "last_indexed_at": repo.last_indexed_at.isoformat() if repo.last_indexed_at else None,
            "last_index_error": repo.last_index_error,
            "spec_layer_enabled": repo.spec_layer_enabled,
            "agent_enabled": repo.agent_enabled,
            "created_at": repo.created_at.isoformat() if repo.created_at else None,
        }
        if include_index_run:
            run = IndexerService(self.db).get_latest_run(repo.id)
            if run and (repo.status == "indexing" or run.status in ("pending", "running")):
                data["index_run"] = self._index_run_dict(run)
        if include_application:
            from app.services.intelligence.application_service import ApplicationService

            data["application"] = ApplicationService(self.db).repository_application_dict(
                repo.tenant_id, repo.id
            )
        return data

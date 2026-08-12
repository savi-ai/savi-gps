"""Orchestrates multi-repo Wiki Agent generation for an Application."""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import (
    Application,
    ApplicationRepository,
    ApplicationWikiSite,
    IndexRun,
    Repository,
    RepositoryWikiSite,
)
from app.core.logger import logger
from app.core.secret_redaction import redact_secrets
from app.services.agents.wiki_agent import WikiAgent
from app.services.intelligence.analysis_storage import (
    get_application_analysis_dir,
    get_application_wiki_status,
    get_application_workspace_dir,
    get_application_workspace_repos_dir,
    mark_failed,
    sanitize_path_segment,
)
from app.services.intelligence.github_credential_service import GitHubCredentialService
from app.services.intelligence.repo_clone_service import RepoCloneService
from app.services.intelligence.wiki_generation_settings import resolve_wiki_generation_settings


class ApplicationWikiAgentService:
    def __init__(self, db: Session):
        self.db = db

    def get_wiki_site(self, application_id: str) -> Optional[ApplicationWikiSite]:
        return (
            self.db.query(ApplicationWikiSite)
            .filter(ApplicationWikiSite.application_id == application_id)
            .order_by(ApplicationWikiSite.updated_at.desc())
            .first()
        )

    def get_status(self, tenant_id: str, application_id: str) -> Dict[str, Any]:
        site = self.get_wiki_site(application_id)
        disk = get_application_wiki_status(tenant_id, application_id)
        readiness = self.member_wiki_readiness(tenant_id, application_id)
        return {
            **disk,
            "has_persisted_site": site is not None,
            "site_version": site.version if site else None,
            "site_updated_at": site.updated_at.isoformat() if site and site.updated_at else None,
            "generated_by": site.generated_by if site else None,
            "member_readiness": readiness,
        }

    def member_wiki_readiness(
        self, tenant_id: str, application_id: str
    ) -> Dict[str, Any]:
        """Per-member repo status + wiki-site presence for app wiki gating."""
        app = (
            self.db.query(Application)
            .filter(Application.id == application_id, Application.tenant_id == tenant_id)
            .first()
        )
        if not app:
            return {
                "all_ready": False,
                "ready_count": 0,
                "total_count": 0,
                "incomplete_count": 0,
                "members": [],
            }

        rows = (
            self.db.query(ApplicationRepository, Repository)
            .join(Repository, ApplicationRepository.repository_id == Repository.id)
            .filter(ApplicationRepository.application_id == app.id)
            .order_by(Repository.name.asc())
            .all()
        )
        members: List[Dict[str, Any]] = []
        ready_count = 0
        for membership, repo in rows:
            site = (
                self.db.query(RepositoryWikiSite)
                .filter(RepositoryWikiSite.repository_id == repo.id)
                .first()
            )
            run = (
                self.db.query(IndexRun)
                .filter(IndexRun.repository_id == repo.id)
                .order_by(IndexRun.created_at.desc())
                .first()
            )
            has_wiki = site is not None
            wiki_ready = repo.status == "ready" and has_wiki
            if wiki_ready:
                ready_count += 1
            members.append({
                "repository_id": repo.id,
                "name": repo.github_full_name or repo.name,
                "role": membership.role,
                "repo_status": repo.status,
                "has_wiki_site": has_wiki,
                "wiki_ready": wiki_ready,
                "index_run_status": run.status if run else None,
                "index_progress": run.progress if run else None,
                "last_error": (run.error if run and run.status == "failed" else None)
                or repo.last_index_error,
            })

        total = len(members)
        return {
            "all_ready": total > 0 and ready_count == total,
            "ready_count": ready_count,
            "total_count": total,
            "incomplete_count": total - ready_count,
            "members": members,
        }

    def start_incomplete_member_indexes(
        self, tenant_id: str, application_id: str
    ) -> Dict[str, Any]:
        """Queue re-index for members that are not wiki-ready.

        Skips repos already pending/running. When the last member finishes
        successfully, IndexerService auto-enqueues the application wiki.
        """
        from app.services.intelligence.indexer_service import IndexerService

        readiness = self.member_wiki_readiness(tenant_id, application_id)
        indexer = IndexerService(self.db)
        started: List[Dict[str, str]] = []
        skipped: List[Dict[str, str]] = []

        for member in readiness["members"]:
            if member["wiki_ready"]:
                skipped.append({
                    "repository_id": member["repository_id"],
                    "name": member["name"],
                    "reason": "already_ready",
                })
                continue
            if member["index_run_status"] in ("pending", "running"):
                skipped.append({
                    "repository_id": member["repository_id"],
                    "name": member["name"],
                    "reason": "already_indexing",
                })
                continue
            repo = (
                self.db.query(Repository)
                .filter(
                    Repository.id == member["repository_id"],
                    Repository.tenant_id == tenant_id,
                )
                .first()
            )
            if not repo:
                continue
            run = indexer.start_index(repo)
            started.append({
                "repository_id": repo.id,
                "name": member["name"],
                "index_run_id": run.id,
            })

        return {
            "all_ready": readiness["all_ready"],
            "started": started,
            "skipped": skipped,
            "ready_count": readiness["ready_count"],
            "total_count": readiness["total_count"],
            "incomplete_count": readiness["incomplete_count"],
        }

    def _load_application(
        self, tenant_id: str, application_id: str
    ) -> Tuple[Application, List[Tuple[ApplicationRepository, Repository]]]:
        app = (
            self.db.query(Application)
            .filter(Application.id == application_id, Application.tenant_id == tenant_id)
            .first()
        )
        if not app:
            raise ValueError("Application not found")
        rows = (
            self.db.query(ApplicationRepository, Repository)
            .join(Repository, ApplicationRepository.repository_id == Repository.id)
            .filter(ApplicationRepository.application_id == app.id)
            .order_by(Repository.name.asc())
            .all()
        )
        if not rows:
            raise ValueError("Application has no member repositories")
        return app, rows

    def _resolve_clone_token(self, repository: Repository) -> Optional[str]:
        if not repository.github_credential_id:
            return None
        cred_svc = GitHubCredentialService(self.db)
        cred = cred_svc.get_credential(repository.tenant_id, repository.github_credential_id)
        if not cred:
            return None
        return cred_svc.get_token(cred)

    def _member_slug(self, repo: Repository, used: Dict[str, int]) -> str:
        base = sanitize_path_segment(
            (repo.github_repo or repo.name or repo.id)[:80]
        ) or "repo"
        if base not in used:
            used[base] = 0
            return base
        used[base] += 1
        return f"{base}_{used[base]}"

    def build_workspace(
        self,
        tenant_id: str,
        application_id: str,
        *,
        rows: Optional[List[Tuple[ApplicationRepository, Repository]]] = None,
    ) -> Dict[str, Any]:
        """Clone all member repos into the application workspace and write MANIFEST.json."""
        if rows is None:
            _, rows = self._load_application(tenant_id, application_id)

        workspace = get_application_workspace_dir(tenant_id, application_id)
        repos_dir = get_application_workspace_repos_dir(tenant_id, application_id)
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)
        repos_dir.mkdir(parents=True, exist_ok=True)

        clone_svc = RepoCloneService()
        used_slugs: Dict[str, int] = {}
        members: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []

        for membership, repo in rows:
            slug = self._member_slug(repo, used_slugs)
            target = repos_dir / slug
            try:
                token = self._resolve_clone_token(repo)
                clone_svc.shallow_clone(
                    repo.url,
                    repo.default_branch or "main",
                    token=token,
                    target_dir=str(target),
                )
                head = clone_svc.get_head_sha(str(target))
                members.append({
                    "repository_id": repo.id,
                    "name": repo.github_full_name or repo.name,
                    "slug": slug,
                    "role": membership.role,
                    "relative_path": f"repos/{slug}",
                    "default_branch": repo.default_branch or "main",
                    "head_sha": head,
                    "status": repo.status,
                })
            except Exception as e:
                err = redact_secrets(str(e))[:500]
                logger.warning(
                    "Application wiki: failed to clone %s: %s",
                    repo.id,
                    err,
                )
                errors.append({"repository_id": repo.id, "error": err})

        if not members:
            raise RuntimeError(
                "Could not clone any member repositories for application wiki: "
                + "; ".join(e["error"] for e in errors[:3])
            )

        manifest = {
            "application_id": application_id,
            "tenant_id": tenant_id,
            "built_at": datetime.now().isoformat(),
            "members": members,
            "clone_errors": errors,
        }
        (workspace / "MANIFEST.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        return {
            "workspace_path": str(workspace),
            "repos_dir": str(repos_dir),
            "manifest": manifest,
        }

    def _service_map_mermaid(self, tenant_id: str, application_id: str) -> str:
        try:
            from app.services.intelligence.application_graph_service import (
                ApplicationGraphService,
            )

            sm = ApplicationGraphService(self.db).compute_service_map(
                tenant_id, application_id
            )
            return (sm or {}).get("mermaid") or ""
        except Exception as e:
            logger.warning("Could not load service map for app wiki: %s", e)
            return ""

    def members_ready_for_app_wiki(
        self, tenant_id: str, application_id: str
    ) -> bool:
        """True when every member is ready and has a repository wiki site."""
        try:
            _, rows = self._load_application(tenant_id, application_id)
        except ValueError:
            return False
        if not rows:
            return False
        for _, repo in rows:
            if repo.status != "ready":
                return False
            site = (
                self.db.query(RepositoryWikiSite)
                .filter(RepositoryWikiSite.repository_id == repo.id)
                .first()
            )
            if not site:
                return False
        return True

    async def generate_for_application(
        self,
        tenant_id: str,
        application_id: str,
    ) -> Dict[str, Any]:
        app, rows = self._load_application(tenant_id, application_id)
        analysis_dir = get_application_analysis_dir(tenant_id, application_id)
        analysis_dir.mkdir(parents=True, exist_ok=True)

        started = analysis_dir / "WIKI_STARTED"
        if started.is_file() and not (analysis_dir / "WIKI_FAILED").is_file():
            try:
                age = datetime.now().timestamp() - started.stat().st_mtime
                if age < 7200:
                    return {
                        "ok": False,
                        "skipped": True,
                        "reason": "already_running",
                        "status": self.get_status(tenant_id, application_id),
                    }
            except OSError:
                pass

        workspace_info: Optional[Dict[str, Any]] = None
        try:
            import asyncio

            workspace_info = await asyncio.to_thread(
                lambda: self.build_workspace(tenant_id, application_id, rows=rows)
            )
            gen_settings = resolve_wiki_generation_settings(self.db, tenant_id)
            service_map = self._service_map_mermaid(tenant_id, application_id)

            agent = WikiAgent()
            state = await agent.process_application({
                "application": {
                    "name": app.name,
                    "description": app.description,
                    "domain": app.domain,
                },
                "application_id": application_id,
                "tenant_id": tenant_id,
                "workspace_path": workspace_info["workspace_path"],
                "output_dir": analysis_dir,
                "manifest": workspace_info["manifest"],
                "service_map_mermaid": service_map,
                "wiki_generation_settings": gen_settings,
            })

            site = self._upsert_site(
                application=app,
                wiki_html=state.get("wiki_html") or "",
                wiki_json=state.get("wiki_json") or {},
                generation_source=state.get("generation_source") or "wiki_agent_application",
            )
            self.db.commit()

            export_result = None
            try:
                from app.services.intelligence.wiki_github_export_service import (
                    WikiGitHubExportService,
                )

                export_result = await WikiGitHubExportService(
                    self.db
                ).maybe_export_application_wiki_to_members(
                    tenant_id=tenant_id,
                    application_id=application_id,
                    application_name=app.name,
                    analysis_dir=analysis_dir,
                    wiki_md=state.get("wiki_md"),
                    sections_md=state.get("sections_md")
                    if isinstance(state.get("sections_md"), dict)
                    else None,
                )
            except Exception as export_err:
                logger.warning(
                    "Application wiki fan-out export failed for %s: %s",
                    application_id,
                    export_err,
                )

            result = {
                "ok": True,
                "wiki_site_id": site.id,
                "analysis_dir": str(analysis_dir),
                "generation_source": state.get("generation_source"),
                "member_count": len(workspace_info["manifest"].get("members") or []),
                "status": self.get_status(tenant_id, application_id),
            }
            if export_result is not None:
                result["github_export"] = export_result
            return result
        except Exception as e:
            err = redact_secrets(str(e))[:4000]
            mark_failed(analysis_dir, err)
            logger.exception("Application wiki generation failed for %s", application_id)
            raise
        finally:
            if not settings.WIKI_APP_KEEP_WORKSPACE and workspace_info:
                ws = Path(workspace_info["workspace_path"])
                if ws.exists():
                    shutil.rmtree(ws, ignore_errors=True)

    def _upsert_site(
        self,
        *,
        application: Application,
        wiki_html: str,
        wiki_json: Dict[str, Any],
        generation_source: str,
    ) -> ApplicationWikiSite:
        site = self.get_wiki_site(application.id)
        title = f"{application.name} — Application Wiki"
        if site:
            site.html_content = wiki_html
            site.summary_json = wiki_json
            site.generated_by = generation_source
            site.version = (site.version or 1) + 1
            site.state = "draft"
            site.title = title
            site.updated_at = datetime.now()
        else:
            site = ApplicationWikiSite(
                id=str(uuid.uuid4()),
                application_id=application.id,
                title=title,
                html_content=wiki_html,
                summary_json=wiki_json,
                state="draft",
                version=1,
                generated_by=generation_source,
            )
            self.db.add(site)
        self.db.flush()
        return site

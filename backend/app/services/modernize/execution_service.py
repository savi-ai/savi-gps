"""Initialize and inspect fix / modernization execution workspaces (W8)."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import ModernizationPlan, Repository
from app.core.logger import logger
from app.services.intelligence.repo_clone_service import RepoCloneService
from app.services.modernize.execution_storage import (
    FIX_STAGES,
    FIX_SUBDIRS,
    MODERNIZE_STAGES,
    MODERNIZE_SUBDIRS,
    ensure_subdirs,
    get_fix_execution_root,
    get_modernize_execution_root,
    read_manifest,
    write_manifest,
)


def _resolve_clone_token(db: Session, repository: Repository) -> Optional[str]:
    try:
        from app.services.intelligence.indexer_service import IndexerService

        return IndexerService(db)._resolve_clone_token(repository)
    except Exception:
        return None


def resolve_execution_root(plan: ModernizationPlan) -> Optional[str]:
    """Return execution root path from plan type and FKs, or None if underspecified."""
    plan_type = getattr(plan, "plan_type", None) or "modernize"
    if plan_type == "fix":
        if not plan.repository_id:
            return None
        return str(get_fix_execution_root(plan.tenant_id, plan.repository_id, plan.id))
    if plan.source_application_id:
        return str(
            get_modernize_execution_root(
                plan.tenant_id, plan.source_application_id, plan.id
            )
        )
    return None


class ExecutionService:
    def __init__(self, db: Session):
        self.db = db
        self._clone = RepoCloneService()

    def get_execution_status(
        self, tenant_id: str, plan: ModernizationPlan
    ) -> Dict[str, Any]:
        if plan.tenant_id != tenant_id:
            raise ValueError("Plan not found")

        root_path = resolve_execution_root(plan)
        if not root_path:
            return {
                "plan_id": plan.id,
                "plan_type": getattr(plan, "plan_type", None) or "modernize",
                "initialized": False,
                "execution_root": None,
                "manifest": None,
            }

        from pathlib import Path

        root = Path(root_path)
        manifest = read_manifest(root)
        return {
            "plan_id": plan.id,
            "plan_type": getattr(plan, "plan_type", None) or "modernize",
            "assessment_run_id": getattr(plan, "assessment_run_id", None),
            "initialized": manifest is not None,
            "execution_root": str(root),
            "manifest": manifest,
            "spawned_project_id": plan.spawned_project_id,
        }

    def initialize_on_spawn(
        self,
        plan: ModernizationPlan,
        *,
        project_id: str,
        repo: Optional[Repository],
        application_id: Optional[str],
        target_github_url: Optional[str] = None,
        target_branch: str = "main",
    ) -> Dict[str, Any]:
        plan_type = getattr(plan, "plan_type", None) or "modernize"
        if plan_type == "fix":
            if not repo:
                raise ValueError("Fix execution requires a repository")
            return self._initialize_fix(
                plan,
                project_id=project_id,
                repo=repo,
                target_branch=target_branch,
            )
        return self._initialize_modernize(
            plan,
            project_id=project_id,
            repo=repo,
            application_id=application_id,
            target_github_url=target_github_url,
            target_branch=target_branch,
        )

    def _initialize_fix(
        self,
        plan: ModernizationPlan,
        *,
        project_id: str,
        repo: Repository,
        target_branch: str,
    ) -> Dict[str, Any]:
        root = get_fix_execution_root(plan.tenant_id, plan.repository_id, plan.id)
        paths = ensure_subdirs(root, FIX_SUBDIRS)

        assessment = plan.assessment_json or {}
        from app.services.modernize.fix_plan_builder import assessment_to_findings

        findings = assessment_to_findings(assessment)
        brief_dir = root / "brief"
        brief_dir.mkdir(parents=True, exist_ok=True)
        (brief_dir / "findings.json").write_text(
            json.dumps(findings, indent=2),
            encoding="utf-8",
        )
        # Agent-facing plan — same markdown created at plan create from findings
        plan_text = (plan.plan_md or "").strip()
        if not plan_text:
            from app.services.modernize.fix_plan_builder import render_fix_plan_md

            plan_text = render_fix_plan_md(plan.title or "Fix plan", findings, assessment=assessment)
        (brief_dir / "plan.md").write_text(plan_text, encoding="utf-8")

        clone_status = "skipped"
        clone_error: Optional[str] = None
        if repo.url:
            token = _resolve_clone_token(self.db, repo)
            branch = repo.default_branch or target_branch or "main"
            try:
                self._clone.shallow_clone(
                    repo.url,
                    branch,
                    token=token,
                    target_dir=str(root / "source"),
                )
                clone_status = "ready"
            except Exception as exc:
                clone_status = "failed"
                clone_error = str(exc)[:500]
                logger.warning("Fix execution source clone failed for plan %s: %s", plan.id, exc)

        manifest = {
            "plan_id": plan.id,
            "plan_type": "fix",
            "project_id": project_id,
            "assessment_run_id": getattr(plan, "assessment_run_id", None),
            "repository_id": repo.id,
            "repository_name": repo.github_full_name or repo.name,
            "source": {
                "github_url": repo.url,
                "branch": repo.default_branch or target_branch,
                "local_path": paths["source"],
                "clone_status": clone_status,
                "clone_error": clone_error,
            },
            "target": {
                "github_url": repo.url,
                "branch": target_branch,
                "same_repo": True,
            },
            "stages": list(FIX_STAGES),
            "stage_state": {s: "pending" for s in FIX_STAGES},
            "paths": paths,
        }
        write_manifest(root, manifest)
        return {"execution_root": str(root), "manifest": manifest}

    def _initialize_modernize(
        self,
        plan: ModernizationPlan,
        *,
        project_id: str,
        repo: Optional[Repository],
        application_id: Optional[str],
        target_github_url: Optional[str],
        target_branch: str,
    ) -> Dict[str, Any]:
        app_id = application_id or plan.source_application_id
        if not app_id:
            raise ValueError(
                "Modernization execution requires an application id (source_application_id)"
            )

        root = get_modernize_execution_root(plan.tenant_id, app_id, plan.id)
        paths = ensure_subdirs(root, MODERNIZE_SUBDIRS)

        assessment = plan.assessment_json or {}
        context_assessment = root / "context" / "assessment.json"
        context_assessment.write_text(json.dumps(assessment, indent=2), encoding="utf-8")

        # Member repos = read-only context (W8.3)
        members: List[Dict[str, Any]] = []
        try:
            from app.core.database import ApplicationRepository

            rows = (
                self.db.query(Repository, ApplicationRepository)
                .join(
                    ApplicationRepository,
                    ApplicationRepository.repository_id == Repository.id,
                )
                .filter(ApplicationRepository.application_id == app_id)
                .all()
            )
            for member_repo, membership in rows:
                members.append(
                    {
                        "repository_id": member_repo.id,
                        "name": member_repo.github_full_name or member_repo.name,
                        "role": membership.role,
                        "status": member_repo.status,
                        "url": member_repo.url,
                    }
                )
        except Exception as exc:
            logger.warning("Could not list application members for context: %s", exc)

        members_path = root / "context" / "members.json"
        members_path.write_text(json.dumps({"members": members}, indent=2), encoding="utf-8")

        targets: List[Dict[str, Any]] = []
        if target_github_url:
            slug = "primary"
            target_dir = root / "targets" / slug
            target_dir.mkdir(parents=True, exist_ok=True)
            targets.append(
                {
                    "slug": slug,
                    "github_url": target_github_url,
                    "branch": target_branch,
                    "local_path": str(target_dir),
                    "clone_status": "pending",
                    "source": "spawn",
                }
            )

        manifest = {
            "plan_id": plan.id,
            "plan_type": "modernize",
            "project_id": project_id,
            "assessment_run_id": getattr(plan, "assessment_run_id", None),
            "application_id": app_id,
            "context_repository_id": repo.id if repo else None,
            "context_repository_name": (
                (repo.github_full_name or repo.name) if repo else None
            ),
            "context_members": members,
            "stages": list(MODERNIZE_STAGES),
            "stage_state": {s: "pending" for s in MODERNIZE_STAGES},
            "targets": targets,
            "paths": paths,
        }
        write_manifest(root, manifest)
        return {"execution_root": str(root), "manifest": manifest}

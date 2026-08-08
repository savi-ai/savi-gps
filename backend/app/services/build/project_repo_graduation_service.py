"""Graduate Build GitHub repos into Intelligence inventory (ADR 0006 P3)."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.core.database import Project, Repository
from app.core.logger import logger
from app.services.build.build_context_service import attach_repositories
from app.services.intelligence.application_service import ApplicationService
from app.services.intelligence.github_credential_service import GitHubCredentialService
from app.services.intelligence.indexer_service import IndexerService
from app.services.intelligence.repo_ingestion_service import RepoIngestionService


_SSH_RE = re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", re.I)


def parse_github_repo_url(url: str) -> Dict[str, str]:
    """
    Parse a GitHub clone/browse URL into owner / repo / full_name / https url.
    Raises ValueError on invalid input.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("GitHub repository URL is required")

    owner: Optional[str] = None
    repo: Optional[str] = None

    ssh = _SSH_RE.match(raw)
    if ssh:
        owner = ssh.group("owner")
        repo = ssh.group("repo")
    else:
        normalized = raw
        if normalized.startswith("github.com/"):
            normalized = "https://" + normalized
        parsed = urlparse(normalized)
        if "github.com" not in (parsed.netloc or "").lower():
            raise ValueError("URL must be a github.com repository")
        parts = [p for p in (parsed.path or "").strip("/").split("/") if p]
        if len(parts) < 2:
            raise ValueError("GitHub URL must include owner and repository name")
        owner, repo = parts[0], parts[1]
        if repo.endswith(".git"):
            repo = repo[:-4]

    if not owner or not repo:
        raise ValueError("Could not parse owner/repository from GitHub URL")

    full_name = f"{owner}/{repo}"
    https_url = f"https://github.com/{full_name}"
    return {
        "owner": owner,
        "repo": repo,
        "full_name": full_name,
        "url": https_url,
    }


def _pick_credential_id(db: Session, tenant_id: str) -> Optional[str]:
    creds = GitHubCredentialService(db).list_credentials(tenant_id)
    return creds[0].id if creds else None


def graduate_project_github_repo(
    db: Session,
    project: Project,
    *,
    github_repo_url: Optional[str] = None,
    created_by: Optional[str] = None,
    start_index: bool = False,
    default_branch: str = "main",
) -> Dict[str, Any]:
    """
    Ensure the project's GitHub URL is an Intelligence Repository, attached to the
    target Application, linked to the Project, and optionally queued for indexing.
    """
    if not project.tenant_id:
        raise ValueError("Project has no tenant")

    url = (github_repo_url or project.github_repo_url or "").strip()
    if not url:
        raise ValueError("GitHub repository URL not configured for this project")

    parsed = parse_github_repo_url(url)
    tenant_id = project.tenant_id
    ingestion = RepoIngestionService(db)

    existing = ingestion.find_by_github_full_name(tenant_id, parsed["full_name"])
    created = False
    if existing:
        repository = existing
    else:
        credential_id = _pick_credential_id(db, tenant_id)
        repository = ingestion.connect_repository(
            tenant_id=tenant_id,
            name=parsed["repo"],
            url=parsed["url"],
            default_branch=default_branch,
            created_by=created_by,
            github_owner=parsed["owner"],
            github_repo=parsed["repo"],
            github_org=parsed["owner"],
            github_full_name=parsed["full_name"],
            github_credential_id=credential_id,
        )
        created = True

    # Keep project URL in canonical https form
    project.github_repo_url = parsed["url"]

    application_id = project.source_application_id
    application_attached = False
    application_origin = None
    if application_id:
        app_svc = ApplicationService(db)
        app = app_svc.get_application(tenant_id, application_id)
        if app:
            application_origin = getattr(app, "origin", None) or "imported"
            try:
                app_svc.add_repository(tenant_id, application_id, repository.id)
                application_attached = True
            except ValueError as e:
                msg = str(e).lower()
                if "already assigned" in msg:
                    application_attached = False
                    logger.warning(
                        "Graduation: repo %s belongs to another application (%s)",
                        repository.id,
                        e,
                    )
                else:
                    logger.warning("Graduation: could not attach repo to application: %s", e)
            # Generated apps with real repos remain generated; extend intent → hybrid
            if (
                application_attached
                and (getattr(project, "mode", None) or "") == "extend"
                and application_origin == "imported"
            ):
                app.origin = "hybrid"
                db.commit()
                application_origin = "hybrid"

    link_type = "modernization" if (project.pillar or "build") == "modernize" else "context"
    attach_repositories(
        db,
        tenant_id,
        project.id,
        [repository.id],
        link_type=link_type,
    )

    index_run_id = None
    if start_index:
        latest = IndexerService(db).get_latest_run(repository.id)
        if latest and latest.status in ("pending", "running"):
            index_run_id = latest.id
        else:
            run = IndexerService(db).start_index(repository)
            index_run_id = run.id

    db.commit()
    db.refresh(repository)

    logger.info(
        "Graduated GitHub repo %s → Intelligence repository %s (created=%s, app=%s, index=%s)",
        parsed["full_name"],
        repository.id,
        created,
        application_id,
        index_run_id,
    )

    return {
        "created": created,
        "repository": {
            "id": repository.id,
            "name": repository.name,
            "github_full_name": repository.github_full_name,
            "url": repository.url,
            "status": repository.status,
        },
        "application_id": application_id,
        "application_attached": application_attached,
        "application_origin": application_origin,
        "project_id": project.id,
        "index_run_id": index_run_id,
        "github_repo_url": parsed["url"],
    }

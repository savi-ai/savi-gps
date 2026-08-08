"""Resolve repository IDs for Build projects from application + explicit picks."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.services.intelligence.application_service import ApplicationService


def resolve_project_repository_ids(
    db: Session,
    tenant_id: str,
    repository_ids: Optional[List[str]] = None,
    application_id: Optional[str] = None,
) -> List[str]:
    """Merge explicit repo picks with all repos from an application (deduped)."""
    resolved: List[str] = []
    seen = set()

    if application_id:
        app_svc = ApplicationService(db)
        for repo_id in app_svc.list_repository_ids(tenant_id, application_id):
            if repo_id not in seen:
                seen.add(repo_id)
                resolved.append(repo_id)

    for repo_id in repository_ids or []:
        if repo_id not in seen:
            seen.add(repo_id)
            resolved.append(repo_id)

    return resolved

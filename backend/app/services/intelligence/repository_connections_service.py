"""Cross-pillar connections for a repository (Stitch hub)."""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.core.database import (
    Application,
    ApplicationRepository,
    ModernizationPlan,
    Project,
    Repository,
    RepositoryProjectLink,
)


def get_repository_connections(
    db: Session, tenant_id: str, repository_id: str
) -> Dict[str, Any]:
    repo = (
        db.query(Repository)
        .filter(Repository.id == repository_id, Repository.tenant_id == tenant_id)
        .first()
    )
    if not repo:
        return {}

    applications: List[Dict[str, Any]] = []
    app_rows = (
        db.query(Application, ApplicationRepository.role)
        .join(ApplicationRepository, ApplicationRepository.application_id == Application.id)
        .filter(
            ApplicationRepository.repository_id == repository_id,
            Application.tenant_id == tenant_id,
        )
        .all()
    )
    for app, role in app_rows:
        applications.append({"id": app.id, "name": app.name, "role": role})

    plans: List[Dict[str, Any]] = []
    plan_rows = (
        db.query(ModernizationPlan)
        .filter(
            ModernizationPlan.repository_id == repository_id,
            ModernizationPlan.tenant_id == tenant_id,
        )
        .order_by(ModernizationPlan.updated_at.desc())
        .limit(20)
        .all()
    )
    for plan in plan_rows:
        plans.append(
            {
                "id": plan.id,
                "title": plan.title,
                "state": plan.state,
                "spawned_project_id": plan.spawned_project_id,
            }
        )

    projects: List[Dict[str, Any]] = []
    project_rows = (
        db.query(Project, RepositoryProjectLink.link_type)
        .join(RepositoryProjectLink, RepositoryProjectLink.project_id == Project.id)
        .filter(
            RepositoryProjectLink.repository_id == repository_id,
            Project.tenant_id == tenant_id,
        )
        .order_by(Project.updated_at.desc())
        .limit(20)
        .all()
    )
    for project, link_type in project_rows:
        projects.append(
            {
                "id": project.id,
                "name": project.name,
                "current_step": project.current_step,
                "pillar": project.pillar or "build",
                "source_plan_id": project.source_plan_id,
                "link_type": link_type,
            }
        )

    return {
        "repository_id": repository_id,
        "applications": applications,
        "modernization_plans": plans,
        "build_projects": projects,
    }

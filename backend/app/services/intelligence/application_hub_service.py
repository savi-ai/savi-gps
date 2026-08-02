"""Application hub — aggregate readiness, plans, and projects for S0 stitching."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import ModernizationPlan, Project, Repository, RepositoryProjectLink
from app.services.intelligence.application_service import ApplicationService
from app.services.modernize.assessment_service import AssessmentService


def _readiness_level_score(level: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(level, 0)


def build_application_hub(db: Session, tenant_id: str, application_id: str) -> Optional[Dict[str, Any]]:
    app_svc = ApplicationService(db)
    app = app_svc.get_application(tenant_id, application_id)
    if not app:
        return None

    detail = app_svc.to_detail_dict(app)
    repo_ids = [r["id"] for r in detail.get("repositories", [])]
    assessment_svc = AssessmentService(db)

    readiness_rows: List[Dict[str, Any]] = []
    assessed_levels: List[str] = []
    assessed_scores: List[int] = []
    any_assessed = False

    for repo_dict in detail.get("repositories", []):
        repo = db.query(Repository).filter(Repository.id == repo_dict["id"]).first()
        if not repo:
            continue
        stored = assessment_svc.load_repo_assessment(repo) if repo.status == "ready" else None
        if repo.status != "ready":
            readiness_rows.append(
                {
                    "repository_id": repo.id,
                    "repository_name": repo.github_full_name or repo.name,
                    "role": repo_dict.get("role"),
                    "indexed": False,
                    "assessed": False,
                    "overall_score": None,
                    "readiness_level": None,
                    "status": repo.status,
                }
            )
            continue
        if not stored:
            readiness_rows.append(
                {
                    "repository_id": repo.id,
                    "repository_name": repo.github_full_name or repo.name,
                    "role": repo_dict.get("role"),
                    "indexed": True,
                    "assessed": False,
                    "overall_score": None,
                    "readiness_level": None,
                    "status": repo.status,
                }
            )
            continue
        any_assessed = True
        level = stored.get("readiness_level") or "medium"
        score = stored.get("overall_score")
        assessed_levels.append(level)
        assessed_scores.append(int(score or 0))
        readiness_rows.append(
            {
                "repository_id": repo.id,
                "repository_name": repo.github_full_name or repo.name,
                "role": repo_dict.get("role"),
                "indexed": True,
                "assessed": True,
                "overall_score": score,
                "readiness_level": level,
                "status": repo.status,
            }
        )

    app_stored = assessment_svc.load_application_assessment(tenant_id, application_id)
    if app_stored and app_stored.get("assessed", True):
        aggregate_level = app_stored.get("readiness_level")
        aggregate_score = app_stored.get("overall_score")
    elif any_assessed and assessed_scores:
        aggregate_score = round(sum(assessed_scores) / len(assessed_scores))
        aggregate_level = min(assessed_levels, key=_readiness_level_score)
    else:
        aggregate_level = None
        aggregate_score = None

    plans: List[Dict[str, Any]] = []
    if repo_ids:
        rows = (
            db.query(ModernizationPlan, Repository)
            .join(Repository, ModernizationPlan.repository_id == Repository.id)
            .filter(
                ModernizationPlan.tenant_id == tenant_id,
                ModernizationPlan.repository_id.in_(repo_ids),
            )
            .order_by(ModernizationPlan.updated_at.desc())
            .all()
        )
        for plan, repo in rows:
            plans.append(
                {
                    "id": plan.id,
                    "title": plan.title,
                    "state": plan.state,
                    "repository_id": plan.repository_id,
                    "repository_name": repo.github_full_name or repo.name,
                    "spawned_project_id": plan.spawned_project_id,
                    "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
                }
            )

    projects_by_app = (
        db.query(Project)
        .filter(Project.tenant_id == tenant_id, Project.source_application_id == application_id)
        .order_by(Project.updated_at.desc())
        .all()
    )
    project_ids_seen = {p.id for p in projects_by_app}
    linked_projects: List[Project] = []
    if repo_ids:
        linked_rows = (
            db.query(Project)
            .join(RepositoryProjectLink, RepositoryProjectLink.project_id == Project.id)
            .filter(
                Project.tenant_id == tenant_id,
                RepositoryProjectLink.repository_id.in_(repo_ids),
            )
            .distinct()
            .all()
        )
        for p in linked_rows:
            if p.id not in project_ids_seen:
                linked_projects.append(p)
                project_ids_seen.add(p.id)

    all_projects = list(projects_by_app) + linked_projects
    projects_payload = [
        {
            "id": p.id,
            "name": p.name,
            "pillar": p.pillar or "build",
            "mode": getattr(p, "mode", None),
            "current_step": p.current_step,
            "source_application_id": p.source_application_id,
            "target_application_id": p.source_application_id,
            "source_plan_id": p.source_plan_id,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }
        for p in sorted(all_projects, key=lambda x: x.updated_at or x.created_at, reverse=True)
    ]

    indexed_pct = (
        round(
            sum(1 for r in detail["repositories"] if r.get("status") == "ready")
            / len(detail["repositories"])
            * 100
        )
        if detail["repositories"]
        else 0
    )

    detail["hub"] = {
        "indexed_pct": indexed_pct,
        "aggregate_readiness_level": aggregate_level,
        "aggregate_readiness_score": aggregate_score,
        "assessment_available": any_assessed or bool(app_stored),
        "readiness": readiness_rows,
        "plans": plans,
        "projects": projects_payload,
        "active_plan_count": sum(1 for p in plans if p["state"] not in ("complete", "cancelled")),
        "active_project_count": len(projects_payload),
    }
    return detail

"""Actionable next steps for dashboard — stitches pillars into guided journeys."""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.core.database import (
    Application,
    ApplicationRepository,
    ModernizationPlan,
    Project,
    Repository,
    WikiPage,
)
from app.services.portfolio import metrics_service as metrics


def build_next_actions(db: Session, tenant_id: str) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []

    repo_ids = metrics.list_tenant_repository_ids(db, tenant_id)
    if not repo_ids:
        actions.append({
            "id": "connect-repo",
            "priority": "high",
            "title": "Connect your first repository",
            "description": "Index code to unlock wiki, search, and modernization readiness.",
            "href": "/dashboard/intelligence/repositories/new",
            "pillar": "intelligence",
        })
        return actions

    assigned_repo_ids = {
        row[0]
        for row in db.query(ApplicationRepository.repository_id)
        .join(Application, ApplicationRepository.application_id == Application.id)
        .filter(Application.tenant_id == tenant_id)
        .all()
    }
    ungrouped = [rid for rid in repo_ids if rid not in assigned_repo_ids]
    if ungrouped:
        actions.append({
            "id": "group-repos",
            "priority": "medium",
            "title": f"{len(ungrouped)} repositor{'ies' if len(ungrouped) != 1 else 'y'} not in an application",
            "description": "Group repos into applications so Intelligence and Modernize work at product level.",
            "href": "/dashboard/intelligence/applications",
            "pillar": "intelligence",
        })

    stale = metrics.stale_repository_count(db, tenant_id)
    if stale > 0:
        actions.append({
            "id": "stale-repos",
            "priority": "medium",
            "title": f"{stale} repositor{'ies' if stale != 1 else 'y'} stale (30+ days since index)",
            "description": "Re-index to refresh wiki and readiness signals.",
            "href": "/dashboard/intelligence/repositories",
            "pillar": "intelligence",
        })

    draft_wiki_count = (
        db.query(WikiPage)
        .join(Repository, WikiPage.repository_id == Repository.id)
        .filter(Repository.tenant_id == tenant_id, WikiPage.state == "draft")
        .count()
    )
    if draft_wiki_count > 0:
        actions.append({
            "id": "wiki-review",
            "priority": "medium",
            "title": f"{draft_wiki_count} wiki page{'s' if draft_wiki_count != 1 else ''} pending review",
            "description": "Approve documentation so Portfolio reflects live coverage.",
            "href": "/dashboard/intelligence/wiki-review",
            "pillar": "intelligence",
        })

    ready_to_spawn = (
        db.query(ModernizationPlan)
        .filter(
            ModernizationPlan.tenant_id == tenant_id,
            ModernizationPlan.state == "planned",
            ModernizationPlan.spawned_project_id.is_(None),
        )
        .count()
    )
    if ready_to_spawn > 0:
        actions.append({
            "id": "spawn-build",
            "priority": "high",
            "title": f"{ready_to_spawn} modernization plan{'s' if ready_to_spawn != 1 else ''} ready to spawn Build",
            "description": "Launch execution with wiki-derived project context.",
            "href": "/dashboard/modernize/plans",
            "pillar": "modernize",
        })

    active_plans = (
        db.query(ModernizationPlan)
        .filter(
            ModernizationPlan.tenant_id == tenant_id,
            ModernizationPlan.state.in_(("assessing", "planned", "executing", "verifying")),
        )
        .count()
    )
    if active_plans == 0 and len(repo_ids) > 0:
        ready_repos = (
            db.query(Repository)
            .filter(Repository.tenant_id == tenant_id, Repository.status == "ready")
            .count()
        )
        if ready_repos > 0:
            actions.append({
                "id": "start-modernize",
                "priority": "low",
                "title": "Start a modernization assessment",
                "description": "Review readiness on an indexed repository and create a plan.",
                "href": "/dashboard/modernize/assessments",
                "pillar": "modernize",
            })

    modernize_projects = (
        db.query(Project)
        .filter(Project.tenant_id == tenant_id, Project.pillar == "modernize")
        .filter(Project.current_step.in_(("idea", "features", "architecture")))
        .count()
    )
    if modernize_projects > 0:
        actions.append({
            "id": "modernize-build",
            "priority": "medium",
            "title": f"{modernize_projects} modernization Build project{'s' if modernize_projects != 1 else ''} in early stages",
            "description": "Continue the golden-path workflow for in-flight modernization.",
            "href": "/dashboard/projects?pillar=modernize",
            "pillar": "build",
        })

    return actions[:8]

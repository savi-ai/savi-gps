"""Aggregate estate health metrics for Portfolio (Stitch 4)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.services.portfolio import metrics_service as metrics
from app.services.portfolio.next_actions_service import build_next_actions


def _health_score(
    repo_total: int,
    ready_count: int,
    wiki_coverage_pct: int,
    failed_runs: int,
    stale_count: int,
) -> int:
    if repo_total == 0:
        return 0
    ready_ratio = ready_count / repo_total
    wiki_ratio = wiki_coverage_pct / 100
    failure_penalty = min(0.3, failed_runs * 0.05)
    stale_penalty = min(0.3, (stale_count / repo_total) * 0.5)
    raw = (ready_ratio * 0.45) + (wiki_ratio * 0.35) + 0.2 - failure_penalty - stale_penalty
    return max(0, min(100, round(raw * 100)))


def build_health(db: Session, tenant_id: str) -> Dict[str, Any]:
    repo_ids = metrics.list_tenant_repository_ids(db, tenant_id)
    repo_total = len(repo_ids)
    by_status = metrics.repository_status_counts(db, tenant_id)
    ready_count = by_status.get("ready", 0)
    index_stats = metrics.index_run_stats(db, tenant_id)
    wiki = metrics.wiki_stats(db, tenant_id, repo_total)
    projects = metrics.project_counts(db, tenant_id)
    stale_count = metrics.stale_repository_count(db, tenant_id)
    modernization = metrics.modernization_plan_counts(db, tenant_id)
    error_count = by_status.get("error", 0)
    indexed_pct = round((ready_count / repo_total) * 100) if repo_total else 0
    index_success_pct = (
        round((index_stats["completed_runs"] / index_stats["total_runs"]) * 100)
        if index_stats["total_runs"]
        else 100
    )
    wiki_approval_pct = (
        round((wiki["live_pages"] / wiki["total_wiki_pages"]) * 100)
        if wiki["total_wiki_pages"]
        else 0
    )

    health_score = _health_score(
        repo_total,
        ready_count,
        wiki["coverage_pct"],
        index_stats["failed_runs"],
        stale_count,
    )

    return {
        "tenant_id": tenant_id,
        "generated_at": datetime.now().isoformat(),
        "health_score": health_score,
        "repositories": {
            "total": repo_total,
            "by_status": by_status,
            "ready": ready_count,
            "indexed_pct": indexed_pct,
            "avg_index_age_days": metrics.average_index_age_days(db, tenant_id),
            "stale_count": stale_count,
            "error_count": error_count,
        },
        "indexing": {
            **index_stats,
            "success_pct": index_success_pct,
        },
        "wiki": {
            **wiki,
            "approval_pct": wiki_approval_pct,
        },
        "projects": projects,
        "modernization": modernization,
        "risk": {
            "stale_repositories": stale_count,
            "failed_index_runs": index_stats["failed_runs"],
            "repositories_in_error": error_count,
            "at_risk_total": stale_count + error_count + index_stats["failed_runs"],
        },
    }


def build_summary(db: Session, tenant_id: str) -> Dict[str, Any]:
    health = build_health(db, tenant_id)
    repos = health["repositories"]
    indexing = health["indexing"]
    wiki = health["wiki"]
    languages = metrics.language_mix(db, tenant_id)
    top_language = next(iter(languages), None) if languages else None

    return {
        "tenant_id": tenant_id,
        "generated_at": health["generated_at"],
        "repositories_total": repos["total"],
        "repositories_ready": repos.get("ready", 0),
        "wiki_coverage_pct": wiki["coverage_pct"],
        "total_loc": indexing["total_loc"],
        "top_language": top_language,
        "projects_active": health["projects"]["total"],
        "stale_repositories": repos["stale_count"],
        "health_score": health["health_score"],
        "modernization_active": health["modernization"]["active"],
        "next_actions": build_next_actions(db, tenant_id),
    }

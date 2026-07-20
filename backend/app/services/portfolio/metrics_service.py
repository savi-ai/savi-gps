"""Shared tenant-scoped query helpers for portfolio metrics."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import (
    CodeChunk,
    IndexRun,
    ModernizationPlan,
    Project,
    Repository,
    RepositoryAnalysisAttribute,
    RepositoryWikiSite,
    WikiPage,
)

EXTENSION_LANGUAGE_MAP: Dict[str, str] = {
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".h": "C",
    ".hpp": "C++",
    ".swift": "Swift",
    ".scala": "Scala",
    ".sql": "SQL",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".md": "Markdown",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sh": "Shell",
    ".xml": "XML",
    ".json": "JSON",
}


def infer_language_from_path(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    return EXTENSION_LANGUAGE_MAP.get(ext, "Other")


def list_tenant_repository_ids(db: Session, tenant_id: str) -> List[str]:
    rows = (
        db.query(Repository.id)
        .filter(Repository.tenant_id == tenant_id)
        .all()
    )
    return [row[0] for row in rows]


def repository_status_counts(db: Session, tenant_id: str) -> Dict[str, int]:
    rows = (
        db.query(Repository.status, func.count(Repository.id))
        .filter(Repository.tenant_id == tenant_id)
        .group_by(Repository.status)
        .all()
    )
    return {status or "unknown": count for status, count in rows}


def average_index_age_days(db: Session, tenant_id: str) -> Optional[float]:
    repos = (
        db.query(Repository.last_indexed_at)
        .filter(
            Repository.tenant_id == tenant_id,
            Repository.last_indexed_at.isnot(None),
        )
        .all()
    )
    if not repos:
        return None
    now = datetime.now()
    ages = [(now - row[0]).total_seconds() / 86400 for row in repos if row[0]]
    if not ages:
        return None
    return round(sum(ages) / len(ages), 1)


def stale_repository_count(db: Session, tenant_id: str, stale_days: int = 30) -> int:
    cutoff = datetime.now().timestamp() - (stale_days * 86400)
    cutoff_dt = datetime.fromtimestamp(cutoff)
    return (
        db.query(func.count(Repository.id))
        .filter(
            Repository.tenant_id == tenant_id,
            (Repository.last_indexed_at.is_(None))
            | (Repository.last_indexed_at < cutoff_dt),
        )
        .scalar()
        or 0
    )


def index_run_stats(db: Session, tenant_id: str) -> Dict[str, int]:
    rows = (
        db.query(IndexRun.status, func.count(IndexRun.id), func.coalesce(func.sum(IndexRun.loc), 0))
        .join(Repository, IndexRun.repository_id == Repository.id)
        .filter(Repository.tenant_id == tenant_id)
        .group_by(IndexRun.status)
        .all()
    )
    total_runs = 0
    completed_runs = 0
    failed_runs = 0
    total_loc = 0
    for status, count, loc_sum in rows:
        total_runs += count
        total_loc += int(loc_sum or 0)
        if status in ("completed", "complete", "ready"):
            completed_runs += count
        elif status in ("failed", "error"):
            failed_runs += count
    return {
        "total_runs": total_runs,
        "completed_runs": completed_runs,
        "failed_runs": failed_runs,
        "total_loc": total_loc,
    }


def language_mix(db: Session, tenant_id: str, limit: int = 12) -> Dict[str, int]:
    rows = (
        db.query(CodeChunk.language, func.count(CodeChunk.id))
        .join(Repository, CodeChunk.repository_id == Repository.id)
        .filter(Repository.tenant_id == tenant_id)
        .group_by(CodeChunk.language)
        .all()
    )
    counts: Dict[str, int] = {}
    for language, count in rows:
        label = (language or "").strip() or "Other"
        counts[label] = counts.get(label, 0) + count

    if not counts:
        path_rows = (
            db.query(CodeChunk.file_path)
            .join(Repository, CodeChunk.repository_id == Repository.id)
            .filter(Repository.tenant_id == tenant_id)
            .limit(5000)
            .all()
        )
        for (file_path,) in path_rows:
            label = infer_language_from_path(file_path or "")
            counts[label] = counts.get(label, 0) + 1

    sorted_items = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    if len(sorted_items) <= limit:
        return dict(sorted_items)
    top = dict(sorted_items[: limit - 1])
    other_total = sum(count for _, count in sorted_items[limit - 1 :])
    top["Other"] = top.get("Other", 0) + other_total
    return top


def wiki_stats(db: Session, tenant_id: str, repo_total: int) -> Dict[str, int]:
    repos_with_site = (
        db.query(func.count(func.distinct(RepositoryWikiSite.repository_id)))
        .join(Repository, RepositoryWikiSite.repository_id == Repository.id)
        .filter(Repository.tenant_id == tenant_id)
        .scalar()
        or 0
    )
    page_rows = (
        db.query(WikiPage.state, func.count(WikiPage.id))
        .join(Repository, WikiPage.repository_id == Repository.id)
        .filter(Repository.tenant_id == tenant_id)
        .group_by(WikiPage.state)
        .all()
    )
    total_pages = 0
    live_pages = 0
    draft_pages = 0
    for state, count in page_rows:
        total_pages += count
        if state == "live":
            live_pages += count
        else:
            draft_pages += count

    coverage_pct = round((repos_with_site / repo_total) * 100) if repo_total else 0
    return {
        "repos_with_wiki_site": repos_with_site,
        "total_wiki_pages": total_pages,
        "live_pages": live_pages,
        "draft_pages": draft_pages,
        "coverage_pct": coverage_pct,
    }


def project_counts(db: Session, tenant_id: str) -> Dict[str, int]:
    rows = (
        db.query(Project.pillar, func.count(Project.id))
        .filter(Project.tenant_id == tenant_id)
        .group_by(Project.pillar)
        .all()
    )
    by_pillar = {pillar or "build": count for pillar, count in rows}
    total = sum(by_pillar.values())
    return {
        "total": total,
        "build": by_pillar.get("build", 0),
        "modernize": by_pillar.get("modernize", 0),
    }


def modernization_plan_counts(db: Session, tenant_id: str) -> Dict[str, int]:
    rows = (
        db.query(ModernizationPlan.state, func.count(ModernizationPlan.id))
        .filter(ModernizationPlan.tenant_id == tenant_id)
        .group_by(ModernizationPlan.state)
        .all()
    )
    by_state = {state or "unknown": count for state, count in rows}
    active_states = ("assessing", "planned", "executing", "verifying")
    return {
        "total": sum(by_state.values()),
        "active": sum(by_state.get(state, 0) for state in active_states),
        "complete": by_state.get("complete", 0),
        "cancelled": by_state.get("cancelled", 0),
        "by_state": by_state,
    }


def analysis_highlights(
    db: Session, tenant_id: str, limit: int = 8
) -> List[Dict[str, object]]:
    rows = (
        db.query(
            RepositoryAnalysisAttribute.attribute_key,
            RepositoryAnalysisAttribute.attribute_label,
            RepositoryAnalysisAttribute.value_text,
            func.count(func.distinct(RepositoryAnalysisAttribute.repository_id)),
        )
        .filter(
            RepositoryAnalysisAttribute.tenant_id == tenant_id,
            RepositoryAnalysisAttribute.value_text.isnot(None),
            RepositoryAnalysisAttribute.value_text != "",
        )
        .group_by(
            RepositoryAnalysisAttribute.attribute_key,
            RepositoryAnalysisAttribute.attribute_label,
            RepositoryAnalysisAttribute.value_text,
        )
        .order_by(func.count(func.distinct(RepositoryAnalysisAttribute.repository_id)).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "key": key,
            "label": label,
            "value": value,
            "repo_count": repo_count,
        }
        for key, label, value, repo_count in rows
    ]

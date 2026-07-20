"""Derive modernization readiness from wiki artifacts and index metadata."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import (
    CodeChunk,
    ModernizationPlan,
    Repository,
    RepositoryAnalysisAttribute,
    RepositoryWikiSite,
    WikiPage,
)
from app.services.intelligence.analysis_storage import load_analysis_artifacts, resolve_analysis_dir


def _signal(
    signal_id: str,
    label: str,
    value: str,
    score: int,
    status: str,
    detail: str,
) -> Dict[str, Any]:
    return {
        "id": signal_id,
        "label": label,
        "value": value,
        "score": max(0, min(100, score)),
        "status": status,
        "detail": detail,
    }


def _freshness_score(last_indexed_at: Optional[datetime]) -> tuple[int, str, str]:
    if not last_indexed_at:
        return 0, "Never indexed", "Run indexing before starting a modernization plan."
    age_days = (datetime.now() - last_indexed_at).total_seconds() / 86400
    if age_days <= 7:
        return 100, f"{int(age_days)}d ago", "Index is fresh."
    if age_days <= 30:
        return 75, f"{int(age_days)}d ago", "Consider re-indexing before major changes."
    return 45, f"{int(age_days)}d ago", "Index may be stale — re-index recommended."


def _extract_runtime(wiki_json: Optional[Dict], attrs: List[RepositoryAnalysisAttribute]) -> str:
    for attr in attrs:
        key = (attr.attribute_key or "").lower()
        if key in ("java_version", "runtime", "jdk", "language_version"):
            return attr.value_text or "Unknown"
    if wiki_json:
        for layer in wiki_json.get("tech_stack") or []:
            if "runtime" in (layer.get("layer") or "").lower() or "language" in (
                layer.get("layer") or ""
            ).lower():
                techs = layer.get("technologies") or []
                if techs:
                    return str(techs[0])
    return "Unknown"


def _framework_versions(attrs: List[RepositoryAnalysisAttribute]) -> List[str]:
    hits = []
    for attr in attrs:
        key = (attr.attribute_key or "").lower()
        if any(token in key for token in ("spring", "framework", "hibernate", "boot")):
            if attr.value_text:
                hits.append(f"{attr.attribute_label}: {attr.value_text}")
    return hits[:5]


def _legacy_risk_score(runtime: str, wiki_json: Optional[Dict]) -> tuple[int, str]:
    text = runtime.lower()
    risk_notes = []
    score = 70
    if "java 8" in text or "java8" in text or "1.8" in text:
        score = 35
        risk_notes.append("Java 8 is past standard support")
    elif "java 11" in text:
        score = 55
        risk_notes.append("Java 11 approaching end of extended support")
    elif "java 17" in text or "java 21" in text:
        score = 90

    if wiki_json:
        for layer in wiki_json.get("tech_stack") or []:
            for tech in layer.get("technologies") or []:
                t = str(tech).lower()
                if "spring boot 2" in t or "hibernate 5" in t or "servlet 3" in t:
                    score = min(score, 40)
                    risk_notes.append(f"Legacy stack signal: {tech}")
                if "tomcat7" in t or "tomcat 7" in t:
                    score = min(score, 35)
                    risk_notes.append(f"Legacy server: {tech}")

    detail = "; ".join(risk_notes) if risk_notes else "No major legacy runtime signals detected."
    return score, detail


def _test_signal_score(db: Session, repository_id: str) -> tuple[int, str, int]:
    test_paths = (
        db.query(func.count(CodeChunk.id))
        .filter(
            CodeChunk.repository_id == repository_id,
            CodeChunk.file_path.ilike("%test%"),
        )
        .scalar()
        or 0
    )
    if test_paths >= 10:
        return 85, f"{test_paths} test-related files", test_paths
    if test_paths >= 3:
        return 65, f"{test_paths} test-related files", test_paths
    if test_paths >= 1:
        return 45, f"{test_paths} test-related file(s)", test_paths
    return 20, "No test files detected", 0


def _doc_coverage_score(
    wiki_site: Optional[RepositoryWikiSite],
    pages: List[WikiPage],
) -> tuple[int, str]:
    if not wiki_site and not pages:
        return 0, "No wiki documentation"
    page_count = len(pages)
    live = sum(1 for p in pages if p.state == "live")
    verified = sum(p.verified_claim_count or 0 for p in pages)
    total_claims = sum(p.total_claim_count or 0 for p in pages)
    citation_pct = round((verified / total_claims) * 100) if total_claims else 0

    score = 40
    if wiki_site:
        score += 25
    if page_count >= 3:
        score += 20
    elif page_count >= 1:
        score += 10
    if citation_pct >= 50:
        score += 15
    elif citation_pct > 0:
        score += 5

    detail = f"{page_count} wiki pages"
    if wiki_site:
        detail += ", unified wiki site"
    if total_claims:
        detail += f", {citation_pct}% citation coverage"
    return min(100, score), detail


def _drift_score(pages: List[WikiPage]) -> tuple[int, str]:
    if not pages:
        return 50, "No wiki pages to assess drift"
    stale = sum(1 for p in pages if p.drift_status == "stale")
    pending = sum(1 for p in pages if p.drift_status == "pending_review")
    if stale:
        return 30, f"{stale} stale wiki page(s)"
    if pending:
        return 60, f"{pending} page(s) pending review"
    return 90, "No drift detected"


def compute_readiness(db: Session, repository: Repository) -> Dict[str, Any]:
    """Build readiness panel JSON for a repository."""
    attrs = (
        db.query(RepositoryAnalysisAttribute)
        .filter(RepositoryAnalysisAttribute.repository_id == repository.id)
        .all()
    )
    pages = db.query(WikiPage).filter(WikiPage.repository_id == repository.id).all()
    wiki_site = (
        db.query(RepositoryWikiSite)
        .filter(RepositoryWikiSite.repository_id == repository.id)
        .order_by(RepositoryWikiSite.updated_at.desc())
        .first()
    )

    artifacts = load_analysis_artifacts(resolve_analysis_dir(repository))
    wiki_json = artifacts.get("wiki_json") if artifacts else None
    if not wiki_json and wiki_site and wiki_site.summary_json:
        wiki_json = wiki_site.summary_json

    runtime = _extract_runtime(wiki_json, attrs)
    legacy_score, legacy_detail = _legacy_risk_score(runtime, wiki_json)
    fresh_score, fresh_value, fresh_detail = _freshness_score(repository.last_indexed_at)
    doc_score, doc_detail = _doc_coverage_score(wiki_site, pages)
    drift_sc, drift_detail = _drift_score(pages)
    test_score, test_detail, test_count = _test_signal_score(db, repository.id)
    frameworks = _framework_versions(attrs)

    signals = [
        _signal("index_freshness", "Index freshness", fresh_value, fresh_score, 
                "good" if fresh_score >= 75 else "warn" if fresh_score >= 45 else "bad", fresh_detail),
        _signal("documentation", "Documentation", f"{len(pages)} pages", doc_score,
                "good" if doc_score >= 70 else "warn" if doc_score >= 40 else "bad", doc_detail),
        _signal("runtime", "Runtime / language", runtime, legacy_score,
                "good" if legacy_score >= 70 else "warn" if legacy_score >= 45 else "bad", legacy_detail),
        _signal("test_coverage", "Test signal", test_detail, test_score,
                "good" if test_score >= 65 else "warn" if test_score >= 40 else "bad",
                "Heuristic based on test-related file paths in the index."),
        _signal("drift", "Wiki drift", drift_detail.split(" ")[0], drift_sc,
                "good" if drift_sc >= 70 else "warn", drift_detail),
    ]

    if frameworks:
        signals.append(
            _signal(
                "frameworks",
                "Framework versions",
                frameworks[0][:60],
                60,
                "warn",
                "; ".join(frameworks),
            )
        )

    overall = round(sum(s["score"] for s in signals) / len(signals)) if signals else 0
    if overall >= 75:
        level = "high"
    elif overall >= 50:
        level = "medium"
    else:
        level = "low"

    existing_plans = (
        db.query(ModernizationPlan)
        .filter(
            ModernizationPlan.repository_id == repository.id,
            ModernizationPlan.tenant_id == repository.tenant_id,
            ModernizationPlan.state.notin_(["complete", "cancelled"]),
        )
        .order_by(ModernizationPlan.updated_at.desc())
        .all()
    )

    tech_stack = wiki_json.get("tech_stack") if wiki_json else []
    overview = (wiki_json or {}).get("overview") or {}

    return {
        "repository_id": repository.id,
        "repository_name": repository.name,
        "repository_status": repository.status,
        "overall_score": overall,
        "readiness_level": level,
        "signals": signals,
        "tech_stack": tech_stack,
        "overview": overview,
        "business_logic_summary": (wiki_json or {}).get("business_logic_layer", {}).get("summary"),
        "existing_plans": [
            {
                "id": p.id,
                "title": p.title,
                "state": p.state,
                "spawned_project_id": p.spawned_project_id,
            }
            for p in existing_plans
        ],
        "indexed": repository.status == "ready",
        "test_file_count": test_count,
    }

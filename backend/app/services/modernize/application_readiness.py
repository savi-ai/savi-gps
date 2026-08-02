"""Application-level readiness — aggregate member repo signals."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import Application, ApplicationRepository, Repository
from app.services.modernize.readiness_scorer import compute_readiness

_LEVEL_RANK = {"high": 3, "medium": 2, "low": 1}


def _worst_level(levels: List[str]) -> str:
    if not levels:
        return "low"
    return min(levels, key=lambda lv: _LEVEL_RANK.get(lv, 0))


def compute_application_readiness(
    db: Session,
    tenant_id: str,
    application_id: str,
) -> Optional[Dict[str, Any]]:
    app = (
        db.query(Application)
        .filter(Application.id == application_id, Application.tenant_id == tenant_id)
        .first()
    )
    if not app:
        return None

    memberships = (
        db.query(ApplicationRepository, Repository)
        .join(Repository, ApplicationRepository.repository_id == Repository.id)
        .filter(ApplicationRepository.application_id == app.id)
        .order_by(Repository.name.asc())
        .all()
    )

    repo_rows: List[Dict[str, Any]] = []
    all_signals: Dict[str, Dict[str, Any]] = {}
    scores: List[int] = []
    levels: List[str] = []
    all_gaps: List[Dict[str, Any]] = []
    version_ids: List[str] = []
    policies_applied: List[Dict[str, Any]] = []
    seen_versions = set()
    seen_policy_keys = set()

    for membership, repo in memberships:
        if repo.status != "ready":
            repo_rows.append({
                "repository_id": repo.id,
                "repository_name": repo.github_full_name or repo.name,
                "role": membership.role,
                "indexed": False,
                "overall_score": None,
                "readiness_level": None,
                "status": repo.status,
                "signals": [],
            })
            levels.append("low")
            scores.append(0)
            continue

        rd = compute_readiness(db, repo)
        level = rd.get("readiness_level") or "medium"
        score = int(rd.get("overall_score") or 0)
        levels.append(level)
        scores.append(score)

        for sig in rd.get("signals") or []:
            sid = sig.get("id") or sig.get("label")
            existing = all_signals.get(sid)
            if not existing or sig.get("score", 100) < existing.get("score", 100):
                all_signals[sid] = {**sig, "repository_id": repo.id, "repository_name": repo.name}

        for gap in rd.get("policy_gaps") or []:
            all_gaps.append({**gap, "repository_id": repo.id, "repository_name": repo.name})
        for vid in rd.get("policy_version_ids") or []:
            if vid not in seen_versions:
                seen_versions.add(vid)
                version_ids.append(vid)
        for applied in rd.get("policies_applied") or []:
            key = applied.get("version_id") or applied.get("policy_id")
            if key and key not in seen_policy_keys:
                seen_policy_keys.add(key)
                policies_applied.append(applied)

        repo_rows.append({
            "repository_id": repo.id,
            "repository_name": repo.github_full_name or repo.name,
            "role": membership.role,
            "indexed": True,
            "overall_score": score,
            "readiness_level": level,
            "status": repo.status,
            "signals": rd.get("signals") or [],
            "policy_gaps": rd.get("policy_gaps") or [],
        })

    aggregate_score = round(sum(scores) / len(scores)) if scores else 0
    aggregate_level = _worst_level([lv for lv in levels if lv])

    return {
        "application_id": app.id,
        "application_name": app.name,
        "repository_count": len(memberships),
        "repositories_ready": sum(1 for r in repo_rows if r.get("indexed")),
        "overall_score": aggregate_score,
        "readiness_level": aggregate_level,
        "signals": list(all_signals.values()),
        "repositories": repo_rows,
        "policy_version_ids": version_ids,
        "policies_applied": policies_applied,
        "policy_gaps": all_gaps,
    }

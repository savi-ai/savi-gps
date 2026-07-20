"""Manual modernization assessments — persist scores; optional auto-run on analysis.

Default product rule: assessments are NOT computed during page loads or during
repo/application analysis unless tenant settings enable auto-assess flags.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import Application, ApplicationRepository, RepoAnalysisView, Repository
from app.core.logger import logger
from app.services.intelligence.analysis_storage import (
    get_analysis_dir,
    get_application_analysis_dir,
)
from app.services.modernize.application_readiness import compute_application_readiness
from app.services.modernize.readiness_scorer import compute_readiness
from app.services.tenant_config_service import TenantConfigService

REPO_READINESS_FILE = "readiness.json"
APP_READINESS_FILE = "readiness.json"
VIEW_TYPE_READINESS = "readiness"

DEFAULT_ASSESSMENT_SETTINGS = {
    "auto_assess_on_repo_index": False,
    "auto_assess_on_application_analysis": False,
}


def _iso_now() -> str:
    return datetime.now().isoformat()


def get_assessment_settings(db: Session, tenant_id: str) -> Dict[str, bool]:
    """Tenant flags controlling auto-run during analysis (default: all manual)."""
    raw = TenantConfigService(db).get_assessment_settings(tenant_id)
    return {
        "auto_assess_on_repo_index": bool(
            raw.get("auto_assess_on_repo_index", DEFAULT_ASSESSMENT_SETTINGS["auto_assess_on_repo_index"])
        ),
        "auto_assess_on_application_analysis": bool(
            raw.get(
                "auto_assess_on_application_analysis",
                DEFAULT_ASSESSMENT_SETTINGS["auto_assess_on_application_analysis"],
            )
        ),
    }


def _repo_path(repository: Repository) -> Path:
    return get_analysis_dir(repository) / "views" / REPO_READINESS_FILE


def _app_path(tenant_id: str, application_id: str) -> Path:
    return get_application_analysis_dir(tenant_id, application_id) / APP_READINESS_FILE


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to read assessment file %s: %s", path, e)
        return None


def _persist_repo_view(db: Session, repository: Repository, payload: Dict[str, Any]) -> None:
    """Also store a summary row for list/query convenience."""
    row = (
        db.query(RepoAnalysisView)
        .filter(
            RepoAnalysisView.repository_id == repository.id,
            RepoAnalysisView.view_type == VIEW_TYPE_READINESS,
            RepoAnalysisView.anchor_symbol.is_(None),
        )
        .first()
    )
    summary = (
        f"Readiness {payload.get('overall_score')} ({payload.get('readiness_level')}) "
        f"via {payload.get('trigger', 'manual')}"
    )
    if row:
        row.summary_sentence = summary
        row.derivation_json = payload
        row.updated_at = datetime.now()
    else:
        db.add(
            RepoAnalysisView(
                id=str(uuid.uuid4()),
                tenant_id=repository.tenant_id,
                repository_id=repository.id,
                view_type=VIEW_TYPE_READINESS,
                anchor_symbol=None,
                summary_sentence=summary,
                mermaid=None,
                derivation_json=payload,
            )
        )
    db.commit()


class AssessmentService:
    def __init__(self, db: Session):
        self.db = db

    def load_repo_assessment(self, repository: Repository) -> Optional[Dict[str, Any]]:
        disk = _read_json(_repo_path(repository))
        if disk:
            return disk
        row = (
            self.db.query(RepoAnalysisView)
            .filter(
                RepoAnalysisView.repository_id == repository.id,
                RepoAnalysisView.view_type == VIEW_TYPE_READINESS,
            )
            .order_by(RepoAnalysisView.updated_at.desc())
            .first()
        )
        if row and isinstance(row.derivation_json, dict):
            return row.derivation_json
        return None

    def load_application_assessment(
        self, tenant_id: str, application_id: str
    ) -> Optional[Dict[str, Any]]:
        return _read_json(_app_path(tenant_id, application_id))

    def get_repo_readiness_response(self, repository: Repository) -> Dict[str, Any]:
        settings = get_assessment_settings(self.db, repository.tenant_id)
        stored = self.load_repo_assessment(repository)
        if not stored:
            return {
                "assessed": False,
                "repository_id": repository.id,
                "repository_name": repository.name,
                "repository_status": repository.status,
                "indexed": repository.status == "ready",
                "message": "No assessment yet. Click Run assessment.",
                "assessment_settings": settings,
            }
        return {**stored, "assessed": True, "assessment_settings": settings}

    def get_application_readiness_response(
        self, tenant_id: str, application_id: str
    ) -> Optional[Dict[str, Any]]:
        app = (
            self.db.query(Application)
            .filter(Application.id == application_id, Application.tenant_id == tenant_id)
            .first()
        )
        if not app:
            return None
        settings = get_assessment_settings(self.db, tenant_id)
        stored = self.load_application_assessment(tenant_id, application_id)
        if not stored:
            member_count = (
                self.db.query(ApplicationRepository)
                .filter(ApplicationRepository.application_id == application_id)
                .count()
            )
            return {
                "assessed": False,
                "application_id": app.id,
                "application_name": app.name,
                "repository_count": member_count,
                "message": "No application assessment yet. Click Run assessment.",
                "repositories": [],
                "signals": [],
                "assessment_settings": settings,
            }
        return {**stored, "assessed": True, "assessment_settings": settings}

    def run_repo_assessment(
        self,
        repository: Repository,
        *,
        trigger: str = "manual",
    ) -> Dict[str, Any]:
        readiness = compute_readiness(self.db, repository)
        payload = {
            **readiness,
            "assessed": True,
            "assessed_at": _iso_now(),
            "trigger": trigger,
        }
        _write_json(_repo_path(repository), payload)
        try:
            _persist_repo_view(self.db, repository, payload)
        except Exception as e:
            logger.warning("Could not persist readiness view row: %s", e)
            self.db.rollback()
        logger.info(
            "Repo assessment %s score=%s trigger=%s",
            repository.id,
            payload.get("overall_score"),
            trigger,
        )
        return payload

    def run_application_assessment(
        self,
        tenant_id: str,
        application_id: str,
        *,
        trigger: str = "manual",
        reassess_members: bool = True,
    ) -> Dict[str, Any]:
        """Assess the whole application: optional per-member recompute, then aggregate."""
        memberships = (
            self.db.query(ApplicationRepository, Repository)
            .join(Repository, ApplicationRepository.repository_id == Repository.id)
            .filter(ApplicationRepository.application_id == application_id)
            .all()
        )
        if reassess_members:
            for _, repo in memberships:
                if repo.status == "ready":
                    self.run_repo_assessment(repo, trigger=trigger)

        # Aggregate from freshly stored member results when possible
        repo_rows: List[Dict[str, Any]] = []
        all_signals: Dict[str, Dict[str, Any]] = {}
        scores: List[int] = []
        levels: List[str] = []
        level_rank = {"high": 3, "medium": 2, "low": 1}

        app = (
            self.db.query(Application)
            .filter(Application.id == application_id, Application.tenant_id == tenant_id)
            .first()
        )
        if not app:
            raise ValueError("Application not found")

        for membership, repo in memberships:
            stored = self.load_repo_assessment(repo) if repo.status == "ready" else None
            if not stored:
                repo_rows.append(
                    {
                        "repository_id": repo.id,
                        "repository_name": repo.github_full_name or repo.name,
                        "role": membership.role,
                        "indexed": repo.status == "ready",
                        "assessed": False,
                        "overall_score": None,
                        "readiness_level": None,
                        "status": repo.status,
                        "signals": [],
                    }
                )
                if repo.status != "ready":
                    levels.append("low")
                    scores.append(0)
                continue

            level = stored.get("readiness_level") or "medium"
            score = int(stored.get("overall_score") or 0)
            levels.append(level)
            scores.append(score)
            for sig in stored.get("signals") or []:
                sid = sig.get("id") or sig.get("label")
                existing = all_signals.get(sid)
                if not existing or sig.get("score", 100) < existing.get("score", 100):
                    all_signals[sid] = {
                        **sig,
                        "repository_id": repo.id,
                        "repository_name": repo.name,
                    }
            repo_rows.append(
                {
                    "repository_id": repo.id,
                    "repository_name": repo.github_full_name or repo.name,
                    "role": membership.role,
                    "indexed": True,
                    "assessed": True,
                    "overall_score": score,
                    "readiness_level": level,
                    "status": repo.status,
                    "signals": stored.get("signals") or [],
                }
            )

        if not scores:
            # Fall back to live aggregate helper (still persist)
            live = compute_application_readiness(self.db, tenant_id, application_id) or {}
            payload = {
                **live,
                "assessed": True,
                "assessed_at": _iso_now(),
                "trigger": trigger,
            }
        else:
            aggregate_score = round(sum(scores) / len(scores))
            aggregate_level = min(levels, key=lambda lv: level_rank.get(lv, 0)) if levels else "low"
            payload = {
                "application_id": app.id,
                "application_name": app.name,
                "repository_count": len(memberships),
                "repositories_ready": sum(1 for r in repo_rows if r.get("indexed")),
                "repositories_assessed": sum(1 for r in repo_rows if r.get("assessed")),
                "overall_score": aggregate_score,
                "readiness_level": aggregate_level,
                "signals": list(all_signals.values()),
                "repositories": repo_rows,
                "assessed": True,
                "assessed_at": _iso_now(),
                "trigger": trigger,
            }

        _write_json(_app_path(tenant_id, application_id), payload)
        logger.info(
            "Application assessment %s score=%s trigger=%s",
            application_id,
            payload.get("overall_score"),
            trigger,
        )
        return payload

    def maybe_auto_assess_repo_after_index(self, repository: Repository) -> Optional[Dict[str, Any]]:
        settings = get_assessment_settings(self.db, repository.tenant_id)
        if not settings["auto_assess_on_repo_index"]:
            return None
        return self.run_repo_assessment(repository, trigger="repo_index")

    def maybe_auto_assess_application_after_analysis(
        self, tenant_id: str, application_id: str
    ) -> Optional[Dict[str, Any]]:
        settings = get_assessment_settings(self.db, tenant_id)
        if not settings["auto_assess_on_application_analysis"]:
            return None
        return self.run_application_assessment(
            tenant_id, application_id, trigger="application_analysis"
        )

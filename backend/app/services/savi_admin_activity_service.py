"""Admin activity rollup for Savi Teammates (Phase B4)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import SaviInstance, SaviWorkItem, Team


class SaviAdminActivityService:
    def __init__(self, db: Session):
        self.db = db

    def list_activity(
        self,
        tenant_id: str,
        *,
        status_filter: Optional[str] = None,
        phase_filter: Optional[str] = None,
        errors_only: bool = False,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        q = (
            self.db.query(SaviInstance, Team)
            .join(Team, Team.id == SaviInstance.team_id)
            .filter(SaviInstance.tenant_id == tenant_id)
            .order_by(SaviInstance.updated_at.desc())
        )
        if status_filter:
            q = q.filter(SaviInstance.status == status_filter)

        rows = q.limit(limit).all()
        out: List[Dict[str, Any]] = []
        for savi, team in rows:
            last = (
                self.db.query(SaviWorkItem)
                .filter(
                    SaviWorkItem.tenant_id == tenant_id,
                    SaviWorkItem.savi_instance_id == savi.id,
                )
                .order_by(SaviWorkItem.updated_at.desc())
                .first()
            )
            phase = last.orchestrator_phase if last else None
            err = last.orchestrator_error if last else None
            if errors_only and not err:
                continue
            if phase_filter and phase != phase_filter:
                continue
            out.append(
                {
                    "savi_id": savi.id,
                    "savi_name": savi.name,
                    "savi_status": savi.status,
                    "team_id": team.id,
                    "team_name": team.name,
                    "last_work_item_id": last.id if last else None,
                    "last_work_title": last.title if last else None,
                    "last_work_state": last.state if last else None,
                    "orchestrator_phase": phase,
                    "orchestrator_error": err,
                    "orchestrator_tokens": last.orchestrator_tokens if last else 0,
                    "pr_url": last.pr_url if last else None,
                    "updated_at": (
                        (last.updated_at or savi.updated_at).isoformat()
                        if (last and last.updated_at) or savi.updated_at
                        else None
                    ),
                    "inbox_path": f"/dashboard/admin/teams/{team.id}/inbox",
                }
            )
        return out

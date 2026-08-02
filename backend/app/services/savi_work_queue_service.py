"""Per-Savi work queue — Phase T3 (ADR 0007).

Queue boundary is savi_instance_id + team_id. Never tenant-global.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.database import (
    Application,
    SaviInstance,
    SaviWorkItem,
    TeamApplication,
    User,
)
from app.core.logger import logger
from app.services.savi_roster_service import SaviRosterService
from app.services.team_service import TeamService

WORK_STATES = (
    "inbox",
    "needs_info",
    "queued",
    "in_progress",
    "in_review",
    "done",
    "blocked",
    "cancelled",
)
OPEN_STATES = ("inbox", "needs_info", "queued", "in_progress", "in_review", "blocked")
TERMINAL_STATES = ("done", "cancelled")
DEFAULT_PRIORITY = 50  # mid band; lower number = higher priority


class SaviWorkQueueService:
    def __init__(self, db: Session):
        self.db = db

    def list_for_savi(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        *,
        include_done: bool = False,
    ) -> List[SaviWorkItem]:
        self._require_savi_on_team(tenant_id, team_id, savi_id)
        q = self.db.query(SaviWorkItem).filter(
            SaviWorkItem.tenant_id == tenant_id,
            SaviWorkItem.team_id == team_id,
            SaviWorkItem.savi_instance_id == savi_id,
        )
        if not include_done:
            q = q.filter(SaviWorkItem.state.notin_(TERMINAL_STATES))
        return q.order_by(
            SaviWorkItem.awaiting_priority.desc(),
            SaviWorkItem.priority.is_(None),
            SaviWorkItem.priority.asc(),
            SaviWorkItem.created_at.asc(),
        ).all()

    def get(
        self, tenant_id: str, team_id: str, savi_id: str, item_id: str
    ) -> Optional[SaviWorkItem]:
        return (
            self.db.query(SaviWorkItem)
            .filter(
                SaviWorkItem.id == item_id,
                SaviWorkItem.tenant_id == tenant_id,
                SaviWorkItem.team_id == team_id,
                SaviWorkItem.savi_instance_id == savi_id,
            )
            .first()
        )

    def in_progress_for_savi(
        self, tenant_id: str, savi_id: str
    ) -> Optional[SaviWorkItem]:
        return (
            self.db.query(SaviWorkItem)
            .filter(
                SaviWorkItem.tenant_id == tenant_id,
                SaviWorkItem.savi_instance_id == savi_id,
                SaviWorkItem.state == "in_progress",
            )
            .first()
        )

    def enqueue(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        *,
        title: str,
        description: Optional[str] = None,
        application_id: Optional[str] = None,
        source: str = "manual",
        external_ref: Optional[str] = None,
        assigned_by: Optional[str] = None,
        priority: Optional[int] = None,
        context_refs: Optional[List[Dict[str, Any]]] = None,
        extra_repository_ids: Optional[List[str]] = None,
    ) -> SaviWorkItem:
        savi = self._require_savi_on_team(tenant_id, team_id, savi_id)
        if savi.status != "active":
            raise ValueError("Savi must be active to accept work")

        title = (title or "").strip()
        if not title:
            raise ValueError("title is required")

        if application_id:
            self._require_app_on_team(tenant_id, team_id, application_id)

        source = (source or "manual").lower()
        if source not in ("manual", "jira", "slack"):
            raise ValueError("source must be manual, jira, or slack")

        from app.services.savi_context_assembly_service import SaviContextAssemblyService

        assembly = SaviContextAssemblyService(self.db)
        stored_refs = assembly.normalize_context_refs(
            context_refs, extra_repository_ids
        )
        if stored_refs.get("extra_repository_ids"):
            assembly.validate_extra_repos(
                tenant_id, team_id, stored_refs["extra_repository_ids"]
            )

        item = SaviWorkItem(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            team_id=team_id,
            savi_instance_id=savi_id,
            application_id=application_id,
            title=title,
            description=description,
            source=source,
            external_ref=external_ref,
            state="inbox",
            priority=priority,
            awaiting_priority=False,
            ready_questions=[],
            clarification_answers={},
            context_refs=stored_refs,
            assigned_by=assigned_by,
        )
        self.db.add(item)
        self.db.flush()

        self._route_after_intake(item, assigned_by=assigned_by)
        self.db.commit()
        self.db.refresh(item)
        logger.info(
            "Enqueued work %s on savi %s team %s state=%s awaiting_priority=%s",
            item.id,
            savi_id,
            team_id,
            item.state,
            item.awaiting_priority,
        )
        return item

    def answer_clarification(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        item_id: str,
        answers: Dict[str, str],
    ) -> SaviWorkItem:
        item = self.get(tenant_id, team_id, savi_id, item_id)
        if not item:
            raise ValueError("Work item not found")
        if item.state not in ("needs_info", "inbox"):
            raise ValueError(f"Cannot answer clarification in state {item.state}")

        merged = dict(item.clarification_answers or {})
        for k, v in (answers or {}).items():
            if v is not None and str(v).strip():
                merged[str(k)] = str(v).strip()
        item.clarification_answers = merged

        # Fold answers into description for readiness heuristics
        extra = "\n".join(f"{k}: {v}" for k, v in merged.items())
        if extra:
            base = item.description or ""
            if "--- clarifications ---" not in base:
                item.description = f"{base}\n\n--- clarifications ---\n{extra}".strip()
            else:
                item.description = re.sub(
                    r"--- clarifications ---.*",
                    f"--- clarifications ---\n{extra}",
                    base,
                    flags=re.S,
                )

        # Allow answering "which application" via special key
        app_ans = merged.get("application_id") or merged.get("q_application")
        if app_ans and not item.application_id:
            self._require_app_on_team(tenant_id, team_id, app_ans)
            item.application_id = app_ans

        item.updated_at = datetime.now()
        self._route_after_intake(item, assigned_by=item.assigned_by)
        self.db.commit()
        self.db.refresh(item)
        return item

    def set_priority(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        item_id: str,
        priority: int,
    ) -> SaviWorkItem:
        item = self.get(tenant_id, team_id, savi_id, item_id)
        if not item:
            raise ValueError("Work item not found")
        if item.state in TERMINAL_STATES:
            raise ValueError("Cannot set priority on a closed item")
        if not isinstance(priority, int) or priority < 1 or priority > 100:
            raise ValueError("priority must be an integer 1–100 (1 = highest)")

        item.priority = priority
        item.awaiting_priority = False
        item.updated_at = datetime.now()

        if item.state in ("inbox", "needs_info"):
            ready, questions = self.ready_check(item)
            if not ready:
                item.state = "needs_info"
                item.ready_questions = questions
            else:
                item.state = "queued"
                item.ready_questions = []

        self.db.commit()
        self.db.refresh(item)
        return item

    def start_next(
        self, tenant_id: str, team_id: str, savi_id: str
    ) -> Optional[SaviWorkItem]:
        """Promote highest-priority queued item to in_progress (one at a time)."""
        self._require_savi_on_team(tenant_id, team_id, savi_id)
        busy = self.in_progress_for_savi(tenant_id, savi_id)
        if busy:
            raise ValueError(
                f"Savi already has in_progress work ({busy.id}). "
                "Finish or block it before starting another."
            )

        waiting = (
            self.db.query(SaviWorkItem)
            .filter(
                SaviWorkItem.tenant_id == tenant_id,
                SaviWorkItem.team_id == team_id,
                SaviWorkItem.savi_instance_id == savi_id,
                SaviWorkItem.state == "queued",
                SaviWorkItem.awaiting_priority == False,  # noqa: E712
            )
            .order_by(
                SaviWorkItem.priority.is_(None),
                SaviWorkItem.priority.asc(),
                SaviWorkItem.created_at.asc(),
            )
            .first()
        )
        if not waiting:
            return None

        waiting.state = "in_progress"
        waiting.started_at = datetime.now()
        waiting.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(waiting)
        return waiting

    def transition(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        item_id: str,
        new_state: str,
    ) -> SaviWorkItem:
        item = self.get(tenant_id, team_id, savi_id, item_id)
        if not item:
            raise ValueError("Work item not found")
        new_state = (new_state or "").lower()
        if new_state not in WORK_STATES:
            raise ValueError(f"Invalid state: {new_state}")

        allowed = self._allowed_transitions(item.state)
        if new_state not in allowed:
            raise ValueError(
                f"Cannot transition from {item.state} to {new_state}. "
                f"Allowed: {', '.join(sorted(allowed))}"
            )

        if new_state == "in_progress":
            busy = self.in_progress_for_savi(tenant_id, savi_id)
            if busy and busy.id != item.id:
                raise ValueError(
                    f"Savi already has in_progress work ({busy.id})"
                )
            item.started_at = item.started_at or datetime.now()

        if new_state in TERMINAL_STATES:
            item.completed_at = datetime.now()

        item.state = new_state
        item.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(item)
        return item

    # --- readiness ---------------------------------------------------------

    def ready_check(self, item: SaviWorkItem) -> Tuple[bool, List[Dict[str, str]]]:
        """Heuristic definition-of-ready (LLM optional later)."""
        questions: List[Dict[str, str]] = []
        desc = (item.description or "").strip()
        title = (item.title or "").strip()
        answers = item.clarification_answers or {}

        if not item.application_id and not answers.get("application_id") and not answers.get(
            "q_application"
        ):
            questions.append(
                {
                    "id": "q_application",
                    "prompt": "Which Application should this work target? (provide application_id)",
                }
            )

        if len(desc) < 40 and not answers.get("q_description"):
            questions.append(
                {
                    "id": "q_description",
                    "prompt": "Please add a fuller description of the requested work.",
                }
            )

        desc_l = desc.lower()
        ac_keys = ("acceptance", "ac:", "criteria", "should ", "must ", "given ")
        if not any(k in desc_l for k in ac_keys) and not answers.get("q_acceptance"):
            questions.append(
                {
                    "id": "q_acceptance",
                    "prompt": "What are the acceptance criteria for done?",
                }
            )

        bug_like = any(
            k in title.lower() for k in ("bug", "fix", "defect", "regression")
        )
        repro_keys = ("repro", "steps to", "reproduce", "how to reproduce")
        if bug_like and not any(k in desc_l for k in repro_keys) and not answers.get(
            "q_repro"
        ):
            questions.append(
                {
                    "id": "q_repro",
                    "prompt": "What are the reproduction steps?",
                }
            )

        # If answers cover outstanding question ids, drop them
        answered_ids = {k for k, v in answers.items() if v and str(v).strip()}
        questions = [q for q in questions if q["id"] not in answered_ids]

        return (len(questions) == 0, questions)

    def _route_after_intake(
        self,
        item: SaviWorkItem,
        *,
        assigned_by: Optional[str],
        force_priority_set: bool = False,
    ) -> None:
        ready, questions = self.ready_check(item)
        if not ready:
            item.state = "needs_info"
            item.ready_questions = questions
            item.awaiting_priority = False
            return

        item.ready_questions = []
        contention = self._has_priority_contention(
            item.tenant_id,
            item.team_id,
            item.savi_instance_id,
            exclude_id=item.id,
            new_assigner=assigned_by,
        )

        if contention and item.priority is None and not force_priority_set:
            item.state = "inbox"
            item.awaiting_priority = True
            return

        if item.priority is None:
            item.priority = DEFAULT_PRIORITY
        item.awaiting_priority = False
        item.state = "queued"

    def _has_priority_contention(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        *,
        exclude_id: str,
        new_assigner: Optional[str],
    ) -> bool:
        """Busy Savi or any other open item on this Savi's queue → ask priority."""
        if self.in_progress_for_savi(tenant_id, savi_id):
            return True

        other = (
            self.db.query(SaviWorkItem.id)
            .filter(
                SaviWorkItem.tenant_id == tenant_id,
                SaviWorkItem.team_id == team_id,
                SaviWorkItem.savi_instance_id == savi_id,
                SaviWorkItem.id != exclude_id,
                SaviWorkItem.state.in_(("inbox", "needs_info", "queued", "blocked")),
            )
            .first()
        )
        return other is not None

    def _allowed_transitions(self, state: str) -> set:
        return {
            "inbox": {"needs_info", "queued", "cancelled"},
            "needs_info": {"inbox", "queued", "cancelled"},
            "queued": {"in_progress", "blocked", "cancelled", "inbox"},
            "in_progress": {"in_review", "blocked", "queued", "cancelled", "done"},
            "in_review": {"in_progress", "done", "blocked", "cancelled"},
            "blocked": {"queued", "inbox", "cancelled", "in_progress"},
            "done": set(),
            "cancelled": set(),
        }.get(state, set())

    def _require_savi_on_team(
        self, tenant_id: str, team_id: str, savi_id: str
    ) -> SaviInstance:
        team = TeamService(self.db).get_team(tenant_id, team_id)
        if not team:
            raise ValueError("Team not found")
        savi = SaviRosterService(self.db).get(tenant_id, savi_id)
        if not savi or savi.team_id != team_id:
            raise ValueError("Savi instance not found on this team")
        return savi

    def _require_app_on_team(
        self, tenant_id: str, team_id: str, application_id: str
    ) -> Application:
        app = (
            self.db.query(Application)
            .filter(Application.id == application_id, Application.tenant_id == tenant_id)
            .first()
        )
        if not app:
            raise ValueError("Application not found")
        link = (
            self.db.query(TeamApplication)
            .filter(
                TeamApplication.team_id == team_id,
                TeamApplication.application_id == application_id,
            )
            .first()
        )
        if not link:
            raise ValueError("Application is not linked to this team")
        return app

    def to_dict(self, item: SaviWorkItem) -> Dict[str, Any]:
        assigner = None
        if item.assigned_by:
            user = self.db.query(User).filter(User.id == item.assigned_by).first()
            if user:
                assigner = {
                    "id": user.id,
                    "username": user.username,
                    "full_name": user.full_name,
                }
        app_name = None
        if item.application_id:
            app = (
                self.db.query(Application)
                .filter(Application.id == item.application_id)
                .first()
            )
            if app:
                app_name = app.name
        return {
            "id": item.id,
            "tenant_id": item.tenant_id,
            "team_id": item.team_id,
            "savi_instance_id": item.savi_instance_id,
            "application_id": item.application_id,
            "application_name": app_name,
            "title": item.title,
            "description": item.description,
            "source": item.source,
            "external_ref": item.external_ref,
            "state": item.state,
            "priority": item.priority,
            "awaiting_priority": bool(item.awaiting_priority),
            "ready_questions": item.ready_questions or [],
            "clarification_answers": item.clarification_answers or {},
            "context_refs": item.context_refs or {
                "refs": [],
                "extra_repository_ids": [],
            },
            "context_pack": item.context_pack,
            "pr_url": item.pr_url,
            "pr_number": item.pr_number,
            "pr_repository_id": item.pr_repository_id,
            "connector_meta": item.connector_meta or {},
            "orchestrator_phase": item.orchestrator_phase,
            "orchestrator_timeline": item.orchestrator_timeline or [],
            "orchestrator_tokens": item.orchestrator_tokens or 0,
            "orchestrator_error": item.orchestrator_error,
            "assigned_by": assigner,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            "started_at": item.started_at.isoformat() if item.started_at else None,
            "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        }

"""CRUD and state machine for modernization plans."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import Application, ApplicationRepository, ModernizationPlan, ModernizationPlaybook, Repository
from app.services.modernize.application_readiness import compute_application_readiness
from app.services.intelligence.application_service import ApplicationService
from app.services.modernize.assessment_service import AssessmentService

VALID_STATES = ("assessing", "planned", "executing", "verifying", "complete", "cancelled")

TRANSITIONS: Dict[str, set] = {
    "assessing": {"planned", "cancelled"},
    "planned": {"executing", "cancelled"},
    "executing": {"verifying", "cancelled"},
    "verifying": {"complete", "cancelled"},
    "complete": set(),
    "cancelled": set(),
}


def _application_for_repo(db: Session, tenant_id: str, repository_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not repository_id:
        return None
    row = (
        db.query(Application, ApplicationRepository)
        .join(ApplicationRepository, ApplicationRepository.application_id == Application.id)
        .filter(
            Application.tenant_id == tenant_id,
            ApplicationRepository.repository_id == repository_id,
        )
        .first()
    )
    if not row:
        return None
    app, membership = row
    return {"id": app.id, "name": app.name, "role": membership.role}


def _application_dict(db: Session, tenant_id: str, application_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not application_id:
        return None
    app = (
        db.query(Application)
        .filter(Application.id == application_id, Application.tenant_id == tenant_id)
        .first()
    )
    if not app:
        return None
    return {"id": app.id, "name": app.name, "role": None}


def _resolve_plan_application(
    db: Session, tenant_id: str, plan: ModernizationPlan
) -> Optional[Dict[str, Any]]:
    if plan.source_application_id:
        return _application_dict(db, tenant_id, plan.source_application_id)
    return _application_for_repo(db, tenant_id, plan.repository_id)


def _plan_deletable(plan: ModernizationPlan) -> bool:
    """Plans may be deleted only before execution has started."""
    if getattr(plan, "spawned_project_id", None):
        return False
    return (plan.state or "") in ("assessing", "planned", "cancelled")


def _plan_to_dict(
    plan: ModernizationPlan,
    repo: Optional[Repository] = None,
    *,
    application: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    data = {
        "id": plan.id,
        "tenant_id": plan.tenant_id,
        "repository_id": plan.repository_id,
        "repository_name": repo.github_full_name or repo.name if repo else None,
        "title": plan.title,
        "state": plan.state,
        "playbook_id": plan.playbook_id,
        "assessment_json": plan.assessment_json,
        "plan_md": plan.plan_md,
        "spawned_project_id": plan.spawned_project_id,
        "source_application_id": plan.source_application_id,
        "plan_bundle_id": plan.plan_bundle_id,
        "plan_type": getattr(plan, "plan_type", None) or "modernize",
        "assessment_run_id": getattr(plan, "assessment_run_id", None),
        "created_by": plan.created_by,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
        "can_delete": _plan_deletable(plan),
    }
    if application is not None:
        data["application"] = application
    return data


def _default_plan_md(
    title: str,
    readiness: Dict[str, Any],
    playbook: Optional[ModernizationPlaybook],
    *,
    plan_type: str = "modernize",
) -> str:
    if plan_type == "fix":
        from app.services.modernize.fix_plan_builder import (
            assessment_to_findings,
            render_fix_plan_md,
        )

        findings = assessment_to_findings(readiness)
        return render_fix_plan_md(title, findings, assessment=readiness)

    lines = [f"# {title}", ""]
    overview = readiness.get("overview") or {}
    if overview.get("description"):
        lines.extend(["## Current state", overview["description"], ""])

    synth = readiness.get("synthesis") or {}
    if synth.get("narrative"):
        lines.extend(["## Assessment narrative", synth["narrative"], ""])
        recs = synth.get("prioritized_recommendations") or []
        if recs:
            lines.append("### Prioritized recommendations")
            for r in recs:
                lines.append(f"- {r}")
            lines.append("")

    lines.append("## Readiness summary")
    lines.append(f"- Overall score: **{readiness.get('overall_score')}** ({readiness.get('readiness_level')})")
    for sig in readiness.get("signals") or []:
        lines.append(f"- {sig['label']}: {sig['value']} ({sig['status']})")
    lines.append("")

    effort = readiness.get("agent_effort") or {}
    if effort:
        lines.append("## Agent effort estimate")
        lines.append(
            f"- Band: **{effort.get('band')}** · "
            f"**{effort.get('estimated_agent_hours')}** agent-hours "
            f"(confidence: {effort.get('confidence')})"
        )
        lines.append(f"- _{effort.get('disclaimer') or 'Agent effort ≠ calendar developer weeks'}_")
        for stage in effort.get("stage_breakdown") or []:
            lines.append(
                f"- {stage.get('stage')}: {stage.get('agent_hours')}h"
                + (f" — {stage['notes']}" if stage.get("notes") else "")
            )
        assumptions = effort.get("assumptions") or []
        if assumptions:
            lines.append("")
            lines.append("### Assumptions")
            for a in assumptions:
                lines.append(f"- {a}")
        lines.append("")

    if playbook:
        lines.extend([f"## Playbook: {playbook.name}", playbook.description or "", ""])
        checklist = playbook.checklist_json or []
        if checklist:
            lines.append("### Checklist")
            for item in checklist:
                lines.append(f"- [ ] {item}")
            lines.append("")

    bl = readiness.get("business_logic_summary")
    if bl:
        lines.extend(["## Business logic layer", bl, ""])

    lines.extend([
        "## Goals",
        "- [ ] Define target runtime and framework versions",
        "- [ ] Identify breaking changes and migration order",
        "- [ ] Plan test strategy and rollout",
        "",
        "## Recommended sequencing",
        "1. Requirements — lock target stack and acceptance from assessment signals",
        "2. Tasks — decompose into agent-executable work items",
        "3. Code — implement upgrades/refactors",
        "4. Test — verify against acceptance",
        "5. Push — open PR to the configured target repository",
        "",
    ])
    return "\n".join(lines)


class PlanService:
    def __init__(self, db: Session):
        self.db = db

    def _get_repo(self, tenant_id: str, repository_id: Optional[str]) -> Optional[Repository]:
        if not repository_id:
            return None
        return (
            self.db.query(Repository)
            .filter(Repository.id == repository_id, Repository.tenant_id == tenant_id)
            .first()
        )

    def _get_plan(self, tenant_id: str, plan_id: str) -> Optional[ModernizationPlan]:
        return (
            self.db.query(ModernizationPlan)
            .filter(ModernizationPlan.id == plan_id, ModernizationPlan.tenant_id == tenant_id)
            .first()
        )

    def list_playbooks(self, tenant_id: str) -> List[Dict[str, Any]]:
        rows = (
            self.db.query(ModernizationPlaybook)
            .filter(
                (ModernizationPlaybook.tenant_id == tenant_id)
                | (ModernizationPlaybook.is_system == True)  # noqa: E712
            )
            .order_by(ModernizationPlaybook.is_system.desc(), ModernizationPlaybook.name)
            .all()
        )
        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "checklist_json": p.checklist_json,
                "is_system": p.is_system,
            }
            for p in rows
        ]

    def create_plan(
        self,
        tenant_id: str,
        user_id: str,
        repository_id: str,
        title: Optional[str] = None,
        playbook_id: Optional[str] = None,
        *,
        plan_type: str = "modernize",
    ) -> Dict[str, Any]:
        if plan_type not in ("fix", "modernize"):
            raise ValueError("plan_type must be 'fix' or 'modernize'")

        repo = self._get_repo(tenant_id, repository_id)
        if not repo:
            raise ValueError("Repository not found")
        if repo.status != "ready":
            raise ValueError("Repository must be indexed (status=ready) before creating a plan")

        playbook = None
        if playbook_id:
            playbook = (
                self.db.query(ModernizationPlaybook)
                .filter(
                    ModernizationPlaybook.id == playbook_id,
                    (ModernizationPlaybook.tenant_id == tenant_id)
                    | (ModernizationPlaybook.is_system == True),  # noqa: E712
                )
                .first()
            )
            if not playbook:
                raise ValueError("Playbook not found")

        readiness = AssessmentService(self.db).run_repo_assessment(repo, trigger="plan_create")
        assessment_run_id = readiness.get("assessed_at")

        if plan_type == "fix" and assessment_run_id:
            existing_fix = (
                self.db.query(ModernizationPlan)
                .filter(
                    ModernizationPlan.tenant_id == tenant_id,
                    ModernizationPlan.repository_id == repository_id,
                    ModernizationPlan.plan_type == "fix",
                    ModernizationPlan.assessment_run_id == assessment_run_id,
                )
                .first()
            )
            if existing_fix:
                raise ValueError(
                    "A fix plan already exists for this repository and assessment run"
                )

        if plan_type == "fix":
            plan_title = title or f"Fix {repo.name}"
        else:
            plan_title = title or f"Modernize {repo.name}"

        plan = ModernizationPlan(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            repository_id=repository_id,
            title=plan_title,
            state="assessing",
            playbook_id=playbook_id,
            assessment_json=readiness,
            plan_md=_default_plan_md(plan_title, readiness, playbook, plan_type=plan_type),
            plan_type=plan_type,
            assessment_run_id=assessment_run_id,
            created_by=user_id,
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return _plan_to_dict(plan, repo)

    def create_application_modernize_plan(
        self,
        tenant_id: str,
        user_id: str,
        application_id: str,
        *,
        title: Optional[str] = None,
        playbook_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """W8.3: one app-scoped modernize plan (repository_id=NULL)."""
        app_svc = ApplicationService(self.db)
        app = app_svc.get_application(tenant_id, application_id)
        if not app:
            raise ValueError("Application not found")

        playbook = None
        if playbook_id:
            playbook = (
                self.db.query(ModernizationPlaybook)
                .filter(
                    ModernizationPlaybook.id == playbook_id,
                    (ModernizationPlaybook.tenant_id == tenant_id)
                    | (ModernizationPlaybook.is_system == True),  # noqa: E712
                )
                .first()
            )
            if not playbook:
                raise ValueError("Playbook not found")

        readiness = AssessmentService(self.db).run_application_assessment(
            tenant_id, application_id, trigger="plan_create"
        )
        assessment_run_id = readiness.get("assessed_at")

        existing = (
            self.db.query(ModernizationPlan)
            .filter(
                ModernizationPlan.tenant_id == tenant_id,
                ModernizationPlan.source_application_id == application_id,
                ModernizationPlan.plan_type == "modernize",
                ModernizationPlan.repository_id.is_(None),
                ModernizationPlan.state.in_(
                    ("assessing", "planned", "executing", "verifying")
                ),
            )
            .first()
        )
        if existing:
            raise ValueError(
                "An active application modernization plan already exists for this application"
            )

        plan_title = title or f"Modernize {app.name}"
        plan = ModernizationPlan(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            repository_id=None,
            title=plan_title,
            state="assessing",
            playbook_id=playbook_id,
            assessment_json=readiness,
            plan_md=_default_plan_md(plan_title, readiness, playbook),
            source_application_id=application_id,
            plan_type="modernize",
            assessment_run_id=assessment_run_id,
            created_by=user_id,
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return _plan_to_dict(
            plan,
            None,
            application={"id": app.id, "name": app.name, "role": None},
        )

    def create_application_plans(
        self,
        tenant_id: str,
        user_id: str,
        application_id: str,
        *,
        title: Optional[str] = None,
        playbook_id: Optional[str] = None,
        skip_existing: bool = True,
    ) -> Dict[str, Any]:
        app_svc = ApplicationService(self.db)
        app = app_svc.get_application(tenant_id, application_id)
        if not app:
            raise ValueError("Application not found")

        detail = app_svc.to_detail_dict(app)
        bundle_id = str(uuid.uuid4())
        base_title = title or f"Modernize {app.name}"
        created: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []

        playbook = None
        if playbook_id:
            playbook = (
                self.db.query(ModernizationPlaybook)
                .filter(
                    ModernizationPlaybook.id == playbook_id,
                    (ModernizationPlaybook.tenant_id == tenant_id)
                    | (ModernizationPlaybook.is_system == True),  # noqa: E712
                )
                .first()
            )
            if not playbook:
                raise ValueError("Playbook not found")

        app_readiness = compute_application_readiness(self.db, tenant_id, application_id) or {}

        for repo_dict in detail.get("repositories", []):
            repo = self._get_repo(tenant_id, repo_dict["id"])
            if not repo:
                continue
            if repo.status != "ready":
                skipped.append({
                    "repository_id": repo.id,
                    "repository_name": repo.github_full_name or repo.name,
                    "reason": f"status={repo.status}",
                })
                continue

            if skip_existing:
                active = (
                    self.db.query(ModernizationPlan)
                    .filter(
                        ModernizationPlan.tenant_id == tenant_id,
                        ModernizationPlan.repository_id == repo.id,
                        ModernizationPlan.state.in_(
                            ("assessing", "planned", "executing", "verifying")
                        ),
                    )
                    .first()
                )
                if active:
                    skipped.append({
                        "repository_id": repo.id,
                        "repository_name": repo.github_full_name or repo.name,
                        "reason": "active_plan_exists",
                        "plan_id": active.id,
                    })
                    continue

            readiness = AssessmentService(self.db).run_repo_assessment(
                repo, trigger="plan_create"
            )
            role = repo_dict.get("role")
            plan_title = f"{base_title} — {repo.github_full_name or repo.name}"
            if role:
                plan_title = f"{base_title} ({role})"

            plan = ModernizationPlan(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                repository_id=repo.id,
                title=plan_title,
                state="assessing",
                playbook_id=playbook_id,
                assessment_json=readiness,
                plan_md=_default_plan_md(plan_title, readiness, playbook),
                source_application_id=application_id,
                plan_bundle_id=bundle_id,
                plan_type="modernize",
                assessment_run_id=readiness.get("assessed_at"),
                created_by=user_id,
            )
            self.db.add(plan)
            created.append(_plan_to_dict(plan, repo))

        if not created:
            self.db.rollback()
            raise ValueError(
                "No plans created — ensure member repositories are indexed and have no active plans"
            )

        self.db.commit()
        coordination_lines = [
            f"# {base_title}",
            "",
            f"Application: **{app.name}**",
            f"Bundle ID: `{bundle_id}`",
            "",
            "## Coordination overview",
            f"- Aggregate readiness: **{app_readiness.get('overall_score', '—')}** "
            f"({app_readiness.get('readiness_level', 'unknown')})",
            f"- Plans created: **{len(created)}**",
            "",
            "## Per-repository plans",
        ]
        for p in created:
            coordination_lines.append(
                f"- [{p['title']}](/dashboard/modernize/plans/{p['id']}) — {p['repository_name']}"
            )
        if skipped:
            coordination_lines.extend(["", "## Skipped", ""])
            for s in skipped:
                coordination_lines.append(
                    f"- {s['repository_name']}: {s['reason']}"
                )

        return {
            "application_id": application_id,
            "application_name": app.name,
            "bundle_id": bundle_id,
            "coordination_md": "\n".join(coordination_lines),
            "plans": created,
            "skipped": skipped,
            "readiness": {
                "overall_score": app_readiness.get("overall_score"),
                "readiness_level": app_readiness.get("readiness_level"),
            },
        }

    def list_plans(
        self,
        tenant_id: str,
        state: Optional[str] = None,
        repository_id: Optional[str] = None,
        application_id: Optional[str] = None,
        bundle_id: Optional[str] = None,
        plan_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = (
            self.db.query(ModernizationPlan)
            .filter(ModernizationPlan.tenant_id == tenant_id)
        )

        if state:
            query = query.filter(ModernizationPlan.state == state)
        if repository_id:
            query = query.filter(ModernizationPlan.repository_id == repository_id)
        if application_id:
            query = query.filter(ModernizationPlan.source_application_id == application_id)
        if bundle_id:
            query = query.filter(ModernizationPlan.plan_bundle_id == bundle_id)
        if plan_type in ("fix", "modernize"):
            query = query.filter(ModernizationPlan.plan_type == plan_type)

        rows = query.order_by(ModernizationPlan.updated_at.desc()).all()
        out: List[Dict[str, Any]] = []
        for plan in rows:
            repo = self._get_repo(tenant_id, plan.repository_id) if plan.repository_id else None
            out.append(
                _plan_to_dict(
                    plan,
                    repo,
                    application=_resolve_plan_application(self.db, tenant_id, plan),
                )
            )
        return out

    def get_plan(self, tenant_id: str, plan_id: str) -> Optional[Dict[str, Any]]:
        plan = self._get_plan(tenant_id, plan_id)
        if not plan:
            return None
        repo = self._get_repo(tenant_id, plan.repository_id) if plan.repository_id else None
        return _plan_to_dict(
            plan,
            repo,
            application=_resolve_plan_application(self.db, tenant_id, plan),
        )

    def delete_plan(self, tenant_id: str, plan_id: str) -> Dict[str, Any]:
        """Delete a plan that has not been executed (no spawn / execution project)."""
        plan = self._get_plan(tenant_id, plan_id)
        if not plan:
            raise ValueError("Plan not found")
        if not _plan_deletable(plan):
            raise ValueError(
                "Only plans that have not started execution can be deleted "
                "(no linked project; state assessing, planned, or cancelled)"
            )
        title = plan.title
        self.db.delete(plan)
        self.db.commit()
        return {"deleted": True, "id": plan_id, "title": title}

    def update_plan(
        self,
        tenant_id: str,
        plan_id: str,
        *,
        state: Optional[str] = None,
        plan_md: Optional[str] = None,
        assessment_json: Optional[Dict] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        plan = self._get_plan(tenant_id, plan_id)
        if not plan:
            raise ValueError("Plan not found")

        if state is not None:
            if state not in VALID_STATES:
                raise ValueError(f"Invalid state: {state}")
            allowed = TRANSITIONS.get(plan.state, set())
            if state != plan.state and state not in allowed:
                raise ValueError(f"Cannot transition from {plan.state} to {state}")
            plan.state = state

        if plan_md is not None:
            plan.plan_md = plan_md
        if assessment_json is not None:
            plan.assessment_json = assessment_json
        if title is not None:
            plan.title = title

        plan.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(plan)
        repo = self._get_repo(tenant_id, plan.repository_id) if plan.repository_id else None
        return _plan_to_dict(
            plan,
            repo,
            application=_resolve_plan_application(self.db, tenant_id, plan),
        )

    def refresh_assessment(self, tenant_id: str, plan_id: str) -> Dict[str, Any]:
        plan = self._get_plan(tenant_id, plan_id)
        if not plan:
            raise ValueError("Plan not found")

        if plan.source_application_id and not plan.repository_id:
            plan.assessment_json = AssessmentService(self.db).run_application_assessment(
                tenant_id, plan.source_application_id, trigger="plan_refresh"
            )
            plan.assessment_run_id = (plan.assessment_json or {}).get("assessed_at")
            plan.updated_at = datetime.now()
            self.db.commit()
            self.db.refresh(plan)
            return _plan_to_dict(
                plan,
                None,
                application=_resolve_plan_application(self.db, tenant_id, plan),
            )

        repo = self._get_repo(tenant_id, plan.repository_id) if plan.repository_id else None
        if not repo:
            raise ValueError("Repository not found")
        plan.assessment_json = AssessmentService(self.db).run_repo_assessment(
            repo, trigger="plan_refresh"
        )
        plan.assessment_run_id = (plan.assessment_json or {}).get("assessed_at")
        plan.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(plan)
        return _plan_to_dict(
            plan,
            repo,
            application=_resolve_plan_application(self.db, tenant_id, plan),
        )

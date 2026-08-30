"""Spawn a Build project from an approved modernization plan (Stitch 2 / W5)."""
from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.logger import logger
from app.core.database import (
    Application,
    ApplicationRepository,
    ModernizationPlan,
    Project,
    Repository,
    RepositoryProjectLink,
    RepositoryWikiSite,
    WikiPage,
)
from app.services.modernize.execution_service import ExecutionService
from app.services.intelligence.analysis_storage import load_analysis_artifacts, resolve_analysis_dir

GITHUB_URL_RE = re.compile(
    r"^(https://github\.com/[\w.-]+/[\w.-]+/?|git@github\.com:[\w.-]+/[\w.-]+(\.git)?)$",
    re.IGNORECASE,
)

MODERNIZE_STUB_ARCHITECTURE = {
    "summary": "Existing application architecture (modernize Alpha path)",
    "source": "modernize_spawn_stub",
    "notes": (
        "Architecture step is skipped for modernization projects. "
        "Code and test agents use the linked source repository + plan brief."
    ),
    "react_flow_diagrams": {"nodes": [], "edges": []},
}


def _wiki_excerpt(wiki_json: Optional[Dict], max_chars: int = 4000) -> str:
    if not wiki_json:
        return ""
    parts: List[str] = []
    overview = wiki_json.get("overview") or {}
    if overview.get("description"):
        parts.append(f"**Overview:** {overview['description']}")

    func = wiki_json.get("functionality") or {}
    if func.get("summary"):
        parts.append(f"**Functionality:** {func['summary']}")
    bullets = func.get("bullets") or []
    if bullets:
        parts.append("**Key capabilities:**")
        for b in bullets[:8]:
            parts.append(f"- {b}")

    bl = wiki_json.get("business_logic_layer") or {}
    if bl.get("summary"):
        parts.append(f"**Business logic:** {bl['summary']}")

    tech = wiki_json.get("tech_stack") or []
    if tech:
        parts.append("**Tech stack:**")
        for layer in tech[:6]:
            name = layer.get("layer", "Layer")
            techs = ", ".join(layer.get("technologies") or [])
            parts.append(f"- {name}: {techs}")

    text = "\n\n".join(parts)
    return text[:max_chars]


def _build_brief(
    plan: ModernizationPlan, repo: Optional[Repository], wiki_json: Optional[Dict]
) -> str:
    assessment = plan.assessment_json or {}
    repo_label = (
        (repo.github_full_name or repo.name) if repo else "(application-scoped)"
    )
    lines = [
        f"# Modernization brief: {plan.title}",
        "",
        f"**Source repository:** {repo_label}",
        f"**Readiness score:** {assessment.get('overall_score', 'n/a')} ({assessment.get('readiness_level', 'unknown')})",
        "",
        "## Plan",
        plan.plan_md or "_No plan markdown yet._",
        "",
        "## Repository intelligence (from wiki)",
        _wiki_excerpt(wiki_json) or "_No wiki artifacts available — link repo and re-index._",
    ]
    gaps = assessment.get("policy_gaps") or []
    if gaps:
        lines.extend(["", "## Policy gaps"])
        for g in gaps[:20]:
            name = g.get("policy_name") or "Policy"
            msg = g.get("message") or g.get("rule_id") or "violation"
            signal = g.get("signal_id") or ""
            lines.append(f"- **{name}** ({signal}): {msg}")
    applied = assessment.get("policies_applied") or []
    if applied:
        lines.extend(["", "## Policies applied"])
        for p in applied[:10]:
            lines.append(
                f"- {p.get('policy_name')} v{p.get('version_number')} (`{p.get('version_id', '')[:8]}`)"
            )
    return "\n".join(lines)


def _page_titles(db: Session, repository_id: str) -> List[str]:
    pages = (
        db.query(WikiPage.title)
        .filter(WikiPage.repository_id == repository_id)
        .order_by(WikiPage.title)
        .limit(12)
        .all()
    )
    return [p[0] for p in pages]


def _normalize_github_url(url: str) -> str:
    cleaned = (url or "").strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    return cleaned


def validate_target_github_url(url: str) -> str:
    cleaned = _normalize_github_url(url)
    if not cleaned:
        raise ValueError("Target GitHub repository URL is required")
    if not (
        cleaned.startswith("https://github.com/")
        or cleaned.startswith("git@github.com:")
    ):
        raise ValueError(
            "Invalid GitHub URL. Must start with https://github.com/ or git@github.com:"
        )
    # Soft shape check for https form
    if cleaned.startswith("https://github.com/"):
        parts = cleaned.replace("https://github.com/", "").split("/")
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise ValueError("GitHub URL must look like https://github.com/owner/repo")
    return cleaned


def spawn_build_project(
    db: Session,
    tenant_id: str,
    user_id: str,
    plan_id: str,
    *,
    target_github_url: Optional[str] = None,
    target_branch: Optional[str] = None,
) -> Dict[str, Any]:
    plan = (
        db.query(ModernizationPlan)
        .filter(ModernizationPlan.id == plan_id, ModernizationPlan.tenant_id == tenant_id)
        .first()
    )
    if not plan:
        raise ValueError("Plan not found")
    if plan.state != "planned":
        raise ValueError("Plan must be in 'planned' state before spawning a Build project")
    if plan.spawned_project_id:
        raise ValueError("Plan already has a linked Build project")

    plan_type = getattr(plan, "plan_type", None) or "modernize"

    repo: Optional[Repository] = None
    if plan.repository_id:
        repo = (
            db.query(Repository)
            .filter(Repository.id == plan.repository_id, Repository.tenant_id == tenant_id)
            .first()
        )
        if not repo:
            raise ValueError("Repository not found")

    if plan_type == "fix":
        if not repo:
            raise ValueError("Fix plans require a repository")
        target_url = validate_target_github_url(target_github_url or repo.url or "")
        branch = (target_branch or repo.default_branch or "main").strip() or "main"
    else:
        # W8.3/W8.4: app-scoped modernize may have no repository_id
        branch = (target_branch or "main").strip() or "main"
        if target_github_url and target_github_url.strip():
            target_url = validate_target_github_url(target_github_url)
        else:
            target_url = None

    existing = (
        db.query(Project)
        .filter(Project.tenant_id == tenant_id, Project.name == plan.title)
        .first()
    )
    if existing:
        raise ValueError(f"A project named '{plan.title}' already exists")

    from app.services.build.project_application_service import resolve_application_for_spawn
    from app.services.intelligence.application_service import ApplicationService

    target_app: Optional[Application] = None
    if plan.source_application_id:
        target_app = (
            db.query(Application)
            .filter(
                Application.id == plan.source_application_id,
                Application.tenant_id == tenant_id,
            )
            .first()
        )
        if not target_app:
            raise ValueError("Application not found for this modernization plan")

    # Context member for wiki brief when app-scoped (no plan.repository_id)
    if not repo and target_app:
        ready = (
            db.query(Repository)
            .join(ApplicationRepository, ApplicationRepository.repository_id == Repository.id)
            .filter(
                ApplicationRepository.application_id == target_app.id,
                Repository.tenant_id == tenant_id,
                Repository.status == "ready",
            )
            .order_by(Repository.name)
            .first()
        )
        member = (
            db.query(Repository)
            .join(ApplicationRepository, ApplicationRepository.repository_id == Repository.id)
            .filter(
                ApplicationRepository.application_id == target_app.id,
                Repository.tenant_id == tenant_id,
            )
            .order_by(Repository.name)
            .first()
        )
        repo = ready or member

    if not target_app and repo:
        target_app = resolve_application_for_spawn(
            db,
            tenant_id=tenant_id,
            plan_application_id=plan.source_application_id,
            repository_id=repo.id,
        )
        if not target_app:
            try:
                target_app = ApplicationService(db).create_application(
                    tenant_id,
                    name=repo.github_full_name or repo.name,
                    description=f"Auto-created for modernization of {repo.name}",
                    domain="Modernization",
                    created_by=user_id,
                    repository_ids=[repo.id],
                    origin="imported",
                )
            except ValueError:
                target_app = (
                    db.query(Application)
                    .filter(
                        Application.tenant_id == tenant_id,
                        Application.name == (repo.github_full_name or repo.name),
                    )
                    .first()
                )
                if target_app:
                    try:
                        ApplicationService(db).add_repository(tenant_id, target_app.id, repo.id)
                    except ValueError:
                        pass

    if plan_type == "modernize" and not target_app:
        raise ValueError(
            "Modernization spawn requires an application "
            "(set source_application_id on the plan)"
        )

    wiki_json = None
    page_titles: List[str] = []
    overview: Dict[str, Any] = {}
    if repo:
        artifacts = load_analysis_artifacts(resolve_analysis_dir(repo))
        wiki_json = artifacts.get("wiki_json") if artifacts else None
        if not wiki_json:
            wiki_site = (
                db.query(RepositoryWikiSite)
                .filter(RepositoryWikiSite.repository_id == repo.id)
                .order_by(RepositoryWikiSite.updated_at.desc())
                .first()
            )
            if wiki_site and wiki_site.summary_json:
                wiki_json = wiki_site.summary_json
        page_titles = _page_titles(db, repo.id)
        overview = (wiki_json or {}).get("overview") or {}

    context_name = (
        target_app.name if target_app and not plan.repository_id
        else (repo.name if repo else plan.title)
    )
    brief = _build_brief(plan, repo, wiki_json) if repo else (
        f"# Modernization brief: {plan.title}\n\n"
        f"**Application:** {target_app.name if target_app else 'n/a'}\n\n"
        "## Plan\n"
        f"{plan.plan_md or '_No plan markdown yet._'}\n"
    )

    if plan_type == "fix":
        seed_message = (
            f"I've prepared a **fix execution workspace** for **{repo.name}**.\n\n"
            f"**Target:** same repo (`{target_url}`, branch `{branch}`)\n\n"
            f"Run stages from the plan page: **Fix → Code → Test → Push → PR** "
            f"(Copilot approve each stage). Source clone lives under `executions/…/source/`."
        )
        pillar = "fix"
        current_step = "developer"
        project_github_url = target_url
    else:
        target_note = (
            f"**Optional seed target:** `{target_url}` (branch `{branch}`)\n\n"
            if target_url
            else "**Targets:** defined after Architecture (register GitHub URLs per component).\n\n"
        )
        seed_message = (
            f"I've prepared a modernization execution workspace for **{context_name}**.\n\n"
            f"{target_note}"
            f"Wiki sections available: {', '.join(page_titles) if page_titles else 'none yet'}.\n\n"
            f"Run from the plan **Execution** panel (Copilot): "
            f"**Requirements → Tasks → Architecture → Code → Test → Push**."
        )
        pillar = "modernize"
        current_step = "features"
        project_github_url = target_url

    conversation = [
        {"role": "assistant", "content": seed_message},
        {"role": "assistant", "content": brief},
    ]

    project = Project(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=plan.title,
        pillar=pillar,
        mode="enhance",
        source_plan_id=plan.id,
        source_application_id=target_app.id if target_app else None,
        description=overview.get("description") or (
            f"Fix plan for {repo.name}" if plan_type == "fix" and repo
            else f"Modernization of {context_name}"
        ),
        domain="Modernization" if plan_type == "modernize" else "Fix",
        priority="high",
        vision=brief[:8000],
        conversation_history=json.dumps(conversation),
        github_repo_url=project_github_url,
        target_branch=branch,
        architecture=MODERNIZE_STUB_ARCHITECTURE,
        current_step=current_step,
        step_status="ReadyForNext",
    )
    db.add(project)

    if target_app and not plan.source_application_id:
        plan.source_application_id = target_app.id

    if repo:
        link = RepositoryProjectLink(
            id=str(uuid.uuid4()),
            repository_id=repo.id,
            project_id=project.id,
            link_type="modernization",
        )
        db.add(link)

    plan.spawned_project_id = project.id
    plan.state = "executing"
    db.commit()
    db.refresh(project)
    db.refresh(plan)

    plan_type = getattr(plan, "plan_type", None) or "modernize"
    execution_info: Dict[str, Any] = {}
    try:
        execution_info = ExecutionService(db).initialize_on_spawn(
            plan,
            project_id=project.id,
            repo=repo,
            application_id=target_app.id if target_app else plan.source_application_id,
            target_github_url=target_url if plan_type == "modernize" else None,
            target_branch=branch,
        )
    except Exception as exc:
        logger.warning("Execution workspace init failed for plan %s: %s", plan.id, exc)
        execution_info = {"error": str(exc)[:500]}

    if target_url:
        try:
            from app.services.build.project_repo_graduation_service import (
                graduate_project_github_repo,
            )

            graduate_project_github_repo(
                db,
                project,
                github_repo_url=target_url,
                created_by=user_id,
                start_index=False,
            )
        except Exception:
            pass

    stages = (
        ["fix", "code", "test", "push", "pr"]
        if plan_type == "fix"
        else ["requirements", "tasks", "architecture", "code", "test", "push"]
    )

    return {
        "plan_id": plan.id,
        "plan_state": plan.state,
        "plan_type": plan_type,
        "project": {
            "id": project.id,
            "name": project.name,
            "pillar": project.pillar,
            "mode": project.mode,
            "source_plan_id": project.source_plan_id,
            "source_application_id": project.source_application_id,
            "target_application_id": project.source_application_id,
            "current_step": project.current_step,
            "github_repo_url": project.github_repo_url,
            "target_branch": project.target_branch,
        },
        "repository_link": {
            "repository_id": repo.id if repo else None,
            "link_type": "modernization",
        },
        "target": {
            "github_repo_url": target_url,
            "branch": branch,
        },
        "stages": stages,
        "execution": execution_info,
        "seeded": True,
        "wiki_pages_referenced": page_titles,
        "alpha_preview": True,
    }

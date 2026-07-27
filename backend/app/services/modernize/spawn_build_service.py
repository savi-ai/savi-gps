"""Spawn a Build project from an approved modernization plan (Stitch 2)."""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import (
    ModernizationPlan,
    Project,
    Repository,
    RepositoryProjectLink,
    RepositoryWikiSite,
    WikiPage,
)
from app.services.intelligence.analysis_storage import load_analysis_artifacts, resolve_analysis_dir


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


def _build_brief(plan: ModernizationPlan, repo: Repository, wiki_json: Optional[Dict]) -> str:
    assessment = plan.assessment_json or {}
    lines = [
        f"# Modernization brief: {plan.title}",
        "",
        f"**Source repository:** {repo.github_full_name or repo.name}",
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


def spawn_build_project(
    db: Session,
    tenant_id: str,
    user_id: str,
    plan_id: str,
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

    repo = (
        db.query(Repository)
        .filter(Repository.id == plan.repository_id, Repository.tenant_id == tenant_id)
        .first()
    )
    if not repo:
        raise ValueError("Repository not found")

    existing = (
        db.query(Project)
        .filter(Project.tenant_id == tenant_id, Project.name == plan.title)
        .first()
    )
    if existing:
        raise ValueError(f"A project named '{plan.title}' already exists")

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

    brief = _build_brief(plan, repo, wiki_json)
    page_titles = _page_titles(db, repo.id)
    overview = (wiki_json or {}).get("overview") or {}

    seed_message = (
        f"I've prepared a modernization workspace for **{repo.name}** based on the approved plan "
        f"and wiki analysis.\n\n"
        f"Wiki sections available: {', '.join(page_titles) if page_titles else 'none yet'}.\n\n"
        f"Review the brief below and refine goals, target stack, and migration phases."
    )

    conversation = [
        {"role": "assistant", "content": seed_message},
        {"role": "assistant", "content": brief},
    ]

    project = Project(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=plan.title,
        pillar="modernize",
        source_plan_id=plan.id,
        description=overview.get("description") or f"Modernization of {repo.name}",
        domain="Modernization",
        priority="high",
        vision=brief[:8000],
        conversation_history=json.dumps(conversation),
        current_step="idea",
    )
    db.add(project)

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

    return {
        "plan_id": plan.id,
        "plan_state": plan.state,
        "project": {
            "id": project.id,
            "name": project.name,
            "pillar": project.pillar,
            "source_plan_id": project.source_plan_id,
            "current_step": project.current_step,
        },
        "repository_link": {
            "repository_id": repo.id,
            "link_type": "modernization",
        },
        "seeded": True,
        "wiki_pages_referenced": page_titles,
    }

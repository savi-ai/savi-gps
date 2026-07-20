"""Compose application wiki views from member repository wikis (read-time synthesis)."""
from __future__ import annotations

import html
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.database import (
    Application,
    ApplicationRepository,
    Repository,
    RepositoryWikiSite,
)

_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 86400


def _repo_display(repo: Repository) -> str:
    return repo.github_full_name or repo.name


def _load_member_wikis(
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

    rows = (
        db.query(ApplicationRepository, Repository)
        .join(Repository, ApplicationRepository.repository_id == Repository.id)
        .filter(ApplicationRepository.application_id == app.id)
        .order_by(Repository.name.asc())
        .all()
    )

    members: List[Dict[str, Any]] = []
    for membership, repo in rows:
        site = (
            db.query(RepositoryWikiSite)
            .filter(RepositoryWikiSite.repository_id == repo.id)
            .order_by(RepositoryWikiSite.updated_at.desc())
            .first()
        )
        summary = (site.summary_json if site else None) or {}
        members.append({
            "repository_id": repo.id,
            "repository_name": _repo_display(repo),
            "role": membership.role,
            "status": repo.status,
            "summary": summary,
            "html_content": site.html_content if site else None,
            "updated_at": site.updated_at.isoformat() if site and site.updated_at else None,
        })

    return {"application": app, "members": members}


def _compose_markdown(
    app: Application,
    members: List[Dict[str, Any]],
    *,
    db: Optional[Session] = None,
    tenant_id: Optional[str] = None,
) -> str:
    lines = [f"# {app.name}", ""]
    if app.description:
        lines.extend([app.description, ""])

    lines.append("## Overview")
    lines.append("")
    if not members:
        lines.append("_No repositories linked to this application yet._")
    else:
        for m in members:
            overview = (m.get("summary") or {}).get("overview") or {}
            desc = overview.get("description") or "_No overview indexed yet._"
            role = f" ({m['role']})" if m.get("role") else ""
            lines.append(f"### {m['repository_name']}{role}")
            lines.append(desc)
            lines.append("")

    lines.append("## Technology stack")
    lines.append("")
    seen: set[str] = set()
    for m in members:
        for layer in (m.get("summary") or {}).get("tech_stack") or []:
            layer_name = layer.get("layer") or "Stack"
            techs = ", ".join(layer.get("technologies") or [])
            key = f"{layer_name}:{techs}"
            if key in seen or not techs:
                continue
            seen.add(key)
            lines.append(f"- **{layer_name}** ({m['repository_name']}): {techs}")
    if len(seen) == 0:
        lines.append("_No tech stack data from member wikis yet._")
    lines.append("")

    lines.append("## Repositories")
    lines.append("")
    for m in members:
        role = f" · {m['role']}" if m.get("role") else ""
        status = m.get("status") or "unknown"
        lines.append(f"- **{m['repository_name']}**{role} — {status}")
    lines.append("")

    if db is not None and tenant_id:
        from app.services.intelligence.application_graph_service import ApplicationGraphService

        service_map = ApplicationGraphService(db).compute_service_map(
            tenant_id, app.id, use_cache=True
        )
        lines.append("## Cross-service dependencies")
        lines.append("")
        lines.append(service_map.get("summary") or "_No dependency map available._")
        lines.append("")
        if service_map.get("mermaid"):
            lines.append("```mermaid")
            lines.append(service_map["mermaid"])
            lines.append("```")
            lines.append("")
        if service_map.get("edges"):
            lines.append("### Detected links")
            lines.append("")
            for edge in service_map["edges"][:12]:
                lines.append(
                    f"- **{edge['source_name']}** → **{edge['target_name']}** "
                    f"({edge['kind'].replace('_', ' ')}): {edge['evidence']}"
                )
            lines.append("")

    return "\n".join(lines)


def _markdown_to_simple_html(md: str) -> str:
    """Lightweight markdown → HTML for application wiki pages."""
    lines = md.splitlines()
    out: List[str] = []
    in_ul = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<h3>{html.escape(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<h2>{html.escape(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<h1>{html.escape(stripped[2:])}</h1>")
        elif stripped.startswith("- "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{html.escape(stripped[2:])}</li>")
        elif stripped == "":
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append("")
        else:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<p>{html.escape(stripped)}</p>")
    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


def _compose_html(app: Application, members: List[Dict[str, Any]], markdown: str) -> str:
    body_parts = [
        "<!DOCTYPE html>",
        "<html lang='en'><head>",
        f"<meta charset='utf-8'><title>{html.escape(app.name)} — Application Wiki</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;max-width:960px;margin:0 auto;padding:2rem;line-height:1.6;color:#1e293b}",
        "h1{border-bottom:2px solid #e2e8f0;padding-bottom:.5rem}",
        "h2{margin-top:2rem;color:#334155}",
        "h3{margin-top:1.25rem}",
        ".repo-nav{display:flex;flex-wrap:wrap;gap:.5rem;margin:1rem 0;padding:1rem;background:#f8fafc;border-radius:8px}",
        ".repo-nav a{font-size:.875rem;color:#2563eb;text-decoration:none}",
        ".repo-section{margin-top:2rem;padding-top:1rem;border-top:1px solid #e2e8f0}",
        ".badge{font-size:.75rem;background:#e2e8f0;padding:.125rem .5rem;border-radius:4px;margin-left:.5rem}",
        "</style></head><body>",
        f"<h1>{html.escape(app.name)}</h1>",
    ]
    if app.description:
        body_parts.append(f"<p>{html.escape(app.description)}</p>")

    body_parts.append("<nav class='repo-nav'><strong>Member wikis:</strong>")
    for m in members:
        body_parts.append(
            f"<a href='/dashboard/intelligence/repositories/{m['repository_id']}/wiki-site'>"
            f"{html.escape(m['repository_name'])}</a>"
        )
    body_parts.append("</nav>")

    body_parts.append(_markdown_to_simple_html(markdown))

    for m in members:
        if m.get("html_content"):
            body_parts.append(
                f"<section class='repo-section' id='repo-{html.escape(m['repository_id'])}'>"
                f"<h2>{html.escape(m['repository_name'])}"
            )
            if m.get("role"):
                body_parts.append(f"<span class='badge'>{html.escape(m['role'])}</span>")
            body_parts.append("</h2>")
            body_parts.append(m["html_content"])
            body_parts.append("</section>")

    body_parts.append("</body></html>")
    return "\n".join(body_parts)


def synthesize_application_wiki_html(
    db: Session,
    tenant_id: str,
    application_id: str,
    *,
    use_cache: bool = True,
) -> Optional[str]:
    cache_key = f"html:{tenant_id}:{application_id}"
    if use_cache and cache_key in _CACHE:
        ts, payload = _CACHE[cache_key]
        if time.time() - ts < _CACHE_TTL_SECONDS:
            return payload.get("html")

    loaded = _load_member_wikis(db, tenant_id, application_id)
    if loaded is None:
        return None

    app: Application = loaded["application"]
    members: List[Dict[str, Any]] = loaded["members"]
    markdown = _compose_markdown(app, members, db=db, tenant_id=tenant_id)
    html_doc = _compose_html(app, members, markdown)
    _CACHE[cache_key] = (time.time(), {"html": html_doc})
    return html_doc


def synthesize_application_wiki(
    db: Session,
    tenant_id: str,
    application_id: str,
    *,
    use_cache: bool = True,
) -> Optional[Dict[str, Any]]:
    cache_key = f"{tenant_id}:{application_id}"
    if use_cache and cache_key in _CACHE:
        ts, payload = _CACHE[cache_key]
        if time.time() - ts < _CACHE_TTL_SECONDS:
            return {**payload, "cached": True}

    loaded = _load_member_wikis(db, tenant_id, application_id)
    if loaded is None:
        return None

    app: Application = loaded["application"]
    members: List[Dict[str, Any]] = loaded["members"]
    markdown = _compose_markdown(app, members, db=db, tenant_id=tenant_id)

    payload = {
        "application_id": app.id,
        "application_name": app.name,
        "repository_count": len(members),
        "markdown": markdown,
        "members": [
            {
                "repository_id": m["repository_id"],
                "repository_name": m["repository_name"],
                "role": m.get("role"),
                "has_wiki": bool(m.get("summary")),
            }
            for m in members
        ],
        "cached": False,
    }
    _CACHE[cache_key] = (time.time(), payload)
    return payload


def invalidate_application_wiki_cache(tenant_id: str, application_id: str) -> None:
    _CACHE.pop(f"{tenant_id}:{application_id}", None)
    _CACHE.pop(f"html:{tenant_id}:{application_id}", None)

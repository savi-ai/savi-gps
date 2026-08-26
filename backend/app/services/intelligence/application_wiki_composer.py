"""Deterministic application wiki composer matching application-wiki-sample.html.

Structural sections come from member wiki JSON + service map + specs.
Readiness/drift are overlaid at render time from readiness.json (no regen required).
Optional LLM may add dashed architecture edges into composite.json.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.database import (
    Application,
    ApplicationRepository,
    IndexRun,
    Repository,
    RepositoryWikiSite,
)
from app.core.logger import logger
from app.core.pipeline_log import log_pipeline
from app.services.intelligence.analysis_storage import (
    WIKI_HTML_NAME,
    WIKI_JSON_NAME,
    WIKI_MD_NAME,
    get_application_analysis_dir,
    mark_completed,
    mark_started,
)
from app.services.intelligence.application_synthesizer import invalidate_application_wiki_cache

COMPOSITE_JSON_NAME = "composite.json"
STYLES_PATH = (
    Path(__file__).resolve().parents[2] / "templates" / "wiki" / "application_wiki_styles.css"
)

# Rotating palette for member repo badges (bg, fg, css_slug)
_REPO_COLORS: List[Tuple[str, str, str]] = [
    ("#e1f5fe", "#0277bd", "c0"),
    ("#e8f5e9", "#2e7d32", "c1"),
    ("#f3e5f5", "#7b1fa2", "c2"),
    ("#fff3e0", "#e65100", "c3"),
    ("#e0f2f1", "#00695c", "c4"),
    ("#fce4ec", "#c2185b", "c5"),
]


def _esc(value: Any) -> str:
    return html.escape(str(value) if value is not None else "")


def _short_name(full: str) -> str:
    return (full or "").split("/")[-1] or full or "repo"


def _repo_wiki_href(repository_id: str, fragment: str = "") -> str:
    base = f"/wiki/repositories/{repository_id}"
    return f"{base}#{fragment}" if fragment else base


def _repo_wiki_link_attrs() -> str:
    return ' target="_blank" rel="noopener noreferrer"'


def _relative_time(iso: Optional[str]) -> str:
    if not iso:
        return "unknown"
    try:
        raw = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        seconds = int((now - dt.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return iso[:16]
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    if seconds < 86400 * 14:
        return f"{seconds // 86400}d ago"
    return dt.strftime("%Y-%m-%d")


def _load_styles() -> str:
    if STYLES_PATH.is_file():
        return STYLES_PATH.read_text(encoding="utf-8")
    return "body{font-family:system-ui,sans-serif;padding:2rem}"


def _dynamic_repo_css(members: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for i, m in enumerate(members):
        slug = m["color_slug"]
        bg, fg, _ = _REPO_COLORS[i % len(_REPO_COLORS)]
        lines.append(f".repo-{slug} {{ background: {bg}; color: {fg}; }}")
        lines.append(f".dot-{slug} {{ background: {fg}; }}")
        lines.append(f".repo-card.{slug} {{ border-top-color: {fg}; }}")
    return "\n".join(lines)


def gather_member_context(
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

    from app.services.intelligence.spec_drift_service import (
        SpecDriftService,
        load_specs_index,
    )
    from app.services.modernize.assessment_service import AssessmentService

    assess = AssessmentService(db)
    drift_svc = SpecDriftService(db)

    members: List[Dict[str, Any]] = []
    for i, (membership, repo) in enumerate(rows):
        site = (
            db.query(RepositoryWikiSite)
            .filter(RepositoryWikiSite.repository_id == repo.id)
            .order_by(RepositoryWikiSite.updated_at.desc())
            .first()
        )
        summary = (site.summary_json if site else None) or {}
        display = repo.github_full_name or repo.name
        short = _short_name(display)
        bg, fg, color_slug = _REPO_COLORS[i % len(_REPO_COLORS)]
        color_slug = f"r{i}"

        last_run = (
            db.query(IndexRun)
            .filter(IndexRun.repository_id == repo.id, IndexRun.status == "completed")
            .order_by(IndexRun.completed_at.desc())
            .first()
        )
        readiness = assess.load_repo_assessment(repo) or {}
        specs = load_specs_index(repo)
        try:
            drift = drift_svc.drift_summary(repo)
        except Exception:
            drift = {}

        members.append({
            "repository_id": repo.id,
            "repository_name": display,
            "short_name": short,
            "role": membership.role,
            "status": repo.status,
            "summary": summary,
            "updated_at": site.updated_at.isoformat() if site and site.updated_at else None,
            "indexed_at": last_run.completed_at.isoformat() if last_run and last_run.completed_at else None,
            "has_wiki": bool(site and (site.html_content or site.summary_json)),
            "color_slug": color_slug,
            "color_bg": bg,
            "color_fg": fg,
            "readiness_score": readiness.get("overall_score"),
            "readiness_level": readiness.get("readiness_level"),
            "readiness_assessed": bool(readiness),
            "specs": specs[:20],
            "drift": drift,
            "api_surface": summary.get("api_surface") or [],
            "tech_stack": summary.get("tech_stack") or [],
            "overview_description": (summary.get("overview") or {}).get("description")
            or (summary.get("functionality") or {}).get("summary")
            or "",
            "feature_bullets": (summary.get("functionality") or {}).get("bullets") or [],
        })

    from app.services.intelligence.application_graph_service import ApplicationGraphService

    service_map = ApplicationGraphService(db).compute_service_map(
        tenant_id, application_id, use_cache=True
    )
    app_readiness = assess.load_application_assessment(tenant_id, application_id) or {}

    return {
        "application": app,
        "members": members,
        "service_map": service_map,
        "app_readiness": app_readiness,
    }


def build_composite_payload(
    ctx: Dict[str, Any],
    *,
    inferred_edges: Optional[List[Dict[str, Any]]] = None,
    inferred_mermaid: Optional[str] = None,
) -> Dict[str, Any]:
    app: Application = ctx["application"]
    members: List[Dict[str, Any]] = ctx["members"]
    service_map: Dict[str, Any] = ctx["service_map"] or {}
    edges = list(service_map.get("edges") or [])
    mermaid = (service_map.get("mermaid") or "").strip()
    if inferred_mermaid:
        mermaid = inferred_mermaid.strip()

    contracts: List[Dict[str, Any]] = []
    for edge in edges:
        contracts.append({
            "contract": edge.get("evidence") or edge.get("kind") or "link",
            "kind": edge.get("kind"),
            "exposed_by_id": edge.get("target_id"),
            "exposed_by": edge.get("target_name"),
            "consumed_by_id": edge.get("source_id"),
            "consumed_by": edge.get("source_name"),
            "source": "graph",
        })
    for edge in inferred_edges or []:
        contracts.append({
            "contract": edge.get("label") or edge.get("contract") or "inferred link",
            "kind": edge.get("kind") or "inferred",
            "exposed_by_id": edge.get("to_id"),
            "exposed_by": edge.get("to"),
            "consumed_by_id": edge.get("from_id"),
            "consumed_by": edge.get("from"),
            "source": "llm_inferred",
        })

    # Deduplicate APIs listed on members that match cross-repo roles
    if not contracts:
        for m in members:
            for api in (m.get("api_surface") or [])[:8]:
                path = api.get("path") or api.get("description") or ""
                method = api.get("method") or ""
                label = f"{method} {path}".strip()
                if not label:
                    continue
                contracts.append({
                    "contract": label,
                    "kind": "api",
                    "exposed_by_id": m["repository_id"],
                    "exposed_by": m["short_name"],
                    "consumed_by_id": None,
                    "consumed_by": "—",
                    "source": "member_wiki",
                })

    features: List[str] = []
    for m in members:
        for bullet in (m.get("feature_bullets") or [])[:3]:
            features.append(f"{bullet} ({m['short_name']})")
        if len(features) >= 8:
            break

    what_parts: List[str] = []
    for m in members:
        desc = (m.get("overview_description") or "").strip()
        if desc:
            role = f" ({m['role']})" if m.get("role") else ""
            what_parts.append(f"{m['short_name']}{role}: {desc}")

    activity: List[Dict[str, Any]] = []
    for m in members:
        if m.get("updated_at"):
            activity.append({
                "repository_id": m["repository_id"],
                "short_name": m["short_name"],
                "color_slug": m["color_slug"],
                "text": f"{m['short_name']} — wiki updated",
                "at": m["updated_at"],
            })
        if m.get("indexed_at"):
            activity.append({
                "repository_id": m["repository_id"],
                "short_name": m["short_name"],
                "color_slug": m["color_slug"],
                "text": f"{m['short_name']} — index completed",
                "at": m["indexed_at"],
            })
    activity.sort(key=lambda a: a.get("at") or "", reverse=True)

    specs_items: List[Dict[str, Any]] = []
    for m in members:
        for spec in m.get("specs") or []:
            path = spec.get("path") or spec.get("relative_path") or "spec"
            specs_items.append({
                "text": path,
                "repository_id": m["repository_id"],
                "short_name": m["short_name"],
                "color_slug": m["color_slug"],
                "kind": "spec",
            })

    return {
        "schema_version": 1,
        "application_id": app.id,
        "application_name": app.name,
        "description": app.description,
        "domain": app.domain,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generation_source": "application_wiki_composer",
        "members": [
            {
                "repository_id": m["repository_id"],
                "repository_name": m["repository_name"],
                "short_name": m["short_name"],
                "role": m.get("role"),
                "status": m.get("status"),
                "color_slug": m["color_slug"],
                "color_bg": m["color_bg"],
                "color_fg": m["color_fg"],
                "overview_description": m.get("overview_description") or "",
                "has_wiki": m.get("has_wiki"),
                "updated_at": m.get("updated_at"),
                "indexed_at": m.get("indexed_at"),
                "tech_stack": m.get("tech_stack") or [],
            }
            for m in members
        ],
        "overview": {
            "blurb": app.description
            or (
                f"{app.name} is composed of {len(members)} member "
                f"repositor{'y' if len(members) == 1 else 'ies'}."
            ),
            "what_it_does": what_parts,
            "key_features": features,
        },
        "architecture": {
            "mermaid": mermaid,
            "summary": service_map.get("summary") or "",
            "graph_edge_count": len(edges),
            "inferred_edges": inferred_edges or [],
            "synth_note": (
                "Solid edges are graph-derived (symbol/import evidence). "
                "Dashed edges are LLM-inferred and excluded from readiness scoring until confirmed."
            ),
        },
        "contracts": contracts,
        "specs": specs_items[:30],
        "activity": activity[:20],
        "stats": {
            "repository_count": len(members),
            "contract_count": len(contracts),
        },
    }


def load_live_overlay(db: Session, tenant_id: str, application_id: str, composite: Dict[str, Any]) -> Dict[str, Any]:
    """Fresh readiness + drift for render — does not require regenerating composite."""
    from app.services.modernize.assessment_service import AssessmentService
    from app.services.intelligence.spec_drift_service import SpecDriftService

    assess = AssessmentService(db)
    app_rd = assess.load_application_assessment(tenant_id, application_id) or {}
    drift_svc = SpecDriftService(db)

    bars: List[Dict[str, Any]] = []
    drift_findings: List[Dict[str, Any]] = []
    scores: List[int] = []
    driver = None
    worst_score = 101

    for m in composite.get("members") or []:
        repo = (
            db.query(Repository)
            .filter(Repository.id == m["repository_id"], Repository.tenant_id == tenant_id)
            .first()
        )
        score = None
        level = None
        if repo:
            rd = assess.load_repo_assessment(repo) or {}
            if rd:
                score = rd.get("overall_score")
                level = rd.get("readiness_level")
            try:
                dsum = drift_svc.drift_summary(repo)
                if dsum.get("wiki_stale") or dsum.get("drift_status") in ("stale", "pending_review"):
                    drift_findings.append({
                        "repository_id": m["repository_id"],
                        "short_name": m.get("short_name"),
                        "color_slug": m.get("color_slug"),
                        "text": (
                            f"Wiki drift on {m.get('short_name')}: "
                            f"{dsum.get('drift_status') or 'pending'} "
                            f"({dsum.get('wiki_stale', 0)} stale page(s))"
                        ),
                    })
            except Exception:
                pass

        if score is not None:
            scores.append(int(score))
            if int(score) < worst_score:
                worst_score = int(score)
                driver = m.get("short_name")

        bars.append({
            "repository_id": m["repository_id"],
            "short_name": m.get("short_name"),
            "color_slug": m.get("color_slug"),
            "score": score,
            "level": level,
            "assessed": score is not None,
        })

    overall = app_rd.get("overall_score")
    if overall is None and scores:
        overall = min(scores)  # worst-case, matching sample

    return {
        "overall_score": overall,
        "readiness_level": app_rd.get("readiness_level"),
        "assessed": bool(app_rd) or bool(scores),
        "driver": driver,
        "bars": bars,
        "drift_findings": drift_findings,
        "drift_count": len(drift_findings),
    }


def _repo_badge(m: Dict[str, Any], fragment: str = "") -> str:
    href = _repo_wiki_href(m["repository_id"], fragment)
    slug = m["color_slug"]
    return (
        f'<a class="repo-badge repo-{_esc(slug)}" href="{_esc(href)}"{_repo_wiki_link_attrs()}>'
        f'<span class="dot dot-{_esc(slug)}"></span>{_esc(m["short_name"])}</a>'
    )


def render_application_wiki_html(
    composite: Dict[str, Any],
    overlay: Dict[str, Any],
    *,
    applications_href: str = "/dashboard/intelligence/applications",
) -> str:
    app_name = composite.get("application_name") or "Application"
    members = composite.get("members") or []
    overview = composite.get("overview") or {}
    architecture = composite.get("architecture") or {}
    contracts = composite.get("contracts") or []
    specs = composite.get("specs") or []
    activity = composite.get("activity") or []
    stats = composite.get("stats") or {}

    member_by_id = {m["repository_id"]: m for m in members}

    badges = " ".join(_repo_badge(m) for m in members)
    blurb = overview.get("blurb") or ""
    if members and "composed of" not in blurb.lower():
        names = ", ".join(_repo_badge(m) for m in members)
        blurb = (
            f"<strong>{_esc(app_name)}</strong> is composed from "
            f"{len(members)} member repositor{'y' if len(members) == 1 else 'ies'}: {names}."
        )
    else:
        blurb = f"<p><strong>{_esc(app_name)}</strong> — {_esc(blurb)}</p>"
        if members:
            blurb += f"<p>Members: {badges}</p>"

    what_html = ""
    what = overview.get("what_it_does") or []
    if what:
        what_html = "<h3>What this application does</h3><ul>" + "".join(
            f"<li>{_esc(w)}</li>" for w in what
        ) + "</ul>"
    elif members:
        what_html = "<h3>What this application does</h3><ul>" + "".join(
            f"<li>{_repo_badge(m)} — {_esc(m.get('overview_description') or m.get('role') or 'Member repository')}</li>"
            for m in members
        ) + "</ul>"

    features = overview.get("key_features") or []
    features_html = ""
    if features:
        features_html = "<h3>Key Features</h3><ul>" + "".join(
            f"<li>{_esc(f)}</li>" for f in features
        ) + "</ul>"

    overall = overlay.get("overall_score")
    drift_count = overlay.get("drift_count") or 0
    contract_count = stats.get("contract_count") or len(contracts)
    stats_html = (
        f'<div class="stat">{len(members)} Repositories</div>'
        f'<div class="stat">{contract_count} Cross-repo contracts</div>'
        f'<div class="stat">{drift_count} Drift finding{"s" if drift_count != 1 else ""}</div>'
        f'<div class="stat">Readiness '
        f'{_esc(overall) if overall is not None else "—"}'
        f'{"" if overall is None else "/100"}</div>'
    )

    mermaid = (architecture.get("mermaid") or "").strip()
    arch_body = ""
    if mermaid:
        arch_body = (
            '<div class="diagram-legend">'
            '<span class="item"><span class="legend-line"></span>Graph-derived edge</span>'
            '<span class="item"><span class="legend-line inferred"></span>LLM-inferred edge</span>'
            "</div>"
            f'<div class="mermaid">\n{mermaid}\n</div>'
        )
    else:
        arch_body = (
            "<p>No cross-repo dependency edges detected yet. "
            "Index member repositories so the service map can populate this diagram.</p>"
        )
    if architecture.get("summary"):
        arch_body += f"<p>{_esc(architecture['summary'])}</p>"

    repo_cards = []
    for m in members:
        desc = m.get("overview_description") or "No overview indexed yet."
        indexed = _relative_time(m.get("indexed_at") or m.get("updated_at"))
        repo_cards.append(
            f'<div class="component-box repo-card {_esc(m["color_slug"])}">'
            f"<h3>{_esc(m['short_name'])}</h3>"
            f"<p>{_esc(desc)}</p>"
            f'<a class="open-link" href="{_esc(_repo_wiki_href(m["repository_id"]))}"{_repo_wiki_link_attrs()}>Open repo wiki →</a>'
            f'<div class="meta"><span>Role: {_esc(m.get("role") or "unknown")}</span>'
            f"<span>Indexed {_esc(indexed)}</span></div>"
            "</div>"
        )
    repos_html = (
        "<p>Always available regardless of what the composite sections above can derive — "
        "the fallback layer for jumping straight into a member repo's own wiki.</p>"
        f'<div class="repo-grid">{"".join(repo_cards) or "<p>No repositories linked.</p>"}</div>'
    )

    api_rows = []
    for c in contracts:
        exp = member_by_id.get(c.get("exposed_by_id") or "")
        con = member_by_id.get(c.get("consumed_by_id") or "")
        exp_html = _repo_badge(exp) if exp else _esc(c.get("exposed_by") or "—")
        con_html = _repo_badge(con) if con else _esc(c.get("consumed_by") or "—")
        note = ""
        if c.get("source") == "llm_inferred":
            note = ' <span style="color:#9aa2ac; font-size:12px;">(inferred)</span>'
        api_rows.append(
            "<tr>"
            f"<td><code>{_esc(c.get('contract'))}</code>{note}</td>"
            f"<td>{exp_html}</td>"
            f"<td>{con_html}</td>"
            "</tr>"
        )
    api_html = (
        "<table><tr><th>Contract</th><th>Exposed by</th><th>Consumed by</th></tr>"
        + ("".join(api_rows) or "<tr><td colspan='3'>No cross-repo contracts detected yet.</td></tr>")
        + "</table>"
    )

    tech_parts = []
    for m in members:
        badges_tech = []
        for layer in m.get("tech_stack") or []:
            for t in layer.get("technologies") or []:
                badges_tech.append(f'<div class="tech-badge">{_esc(t)}</div>')
            if layer.get("layer") and not layer.get("technologies"):
                badges_tech.append(f'<div class="tech-badge">{_esc(layer["layer"])}</div>')
        if not badges_tech:
            badges_tech.append('<span style="color:#9aa2ac;font-size:13px;">Not detected</span>')
        tech_parts.append(f"<h3>{_esc(m['short_name'])}</h3>" + "".join(badges_tech))
    tech_html = "".join(tech_parts) or "<p>No tech stack data from member wikis yet.</p>"

    specs_html_parts = []
    for s in specs:
        m = member_by_id.get(s.get("repository_id") or "")
        badge = _repo_badge(m) if m else _esc(s.get("short_name") or "")
        specs_html_parts.append(
            f'<div class="rule-box">{_esc(s.get("text"))} — {badge}</div>'
        )
    specs_html = (
        "".join(specs_html_parts)
        or '<div class="workflow-box">No specs/steering files indexed on member repos yet.</div>'
    )

    # Readiness overlay
    score = overlay.get("overall_score")
    driver = overlay.get("driver")
    driver_txt = (
        f"Application score is worst-case across member repos"
        + (f" — driven down by <strong>{_esc(driver)}</strong>" if driver else "")
        if score is not None
        else "Run assessment on member repos (and the application) to populate readiness."
    )
    score_html = (
        f'{_esc(score)}<span style="font-size:16px; color:#9aa2ac;">/100</span>'
        if score is not None
        else "—"
    )
    bars_html = []
    for b in overlay.get("bars") or []:
        sc = b.get("score")
        width = max(0, min(100, int(sc))) if sc is not None else 0
        fill_cls = "rbar-fill mid" if sc is not None and int(sc) < 70 else "rbar-fill"
        val = _esc(sc) if sc is not None else "—"
        bars_html.append(
            '<div class="rbar-row">'
            f'<span class="rbar-label"><span class="dot-{_esc(b.get("color_slug"))}" '
            f'style="width:7px;height:7px;border-radius:50%;display:inline-block;"></span>'
            f'{_esc(b.get("short_name"))}</span>'
            f'<div class="rbar-track"><div class="{fill_cls}" style="width:{width}%"></div></div>'
            f'<span class="rbar-val">{val}</span>'
            "</div>"
        )
    drift_boxes = []
    for d in overlay.get("drift_findings") or []:
        m = member_by_id.get(d.get("repository_id") or "")
        badge = _repo_badge(m) if m else ""
        href = _repo_wiki_href(d["repository_id"]) if d.get("repository_id") else "#"
        drift_boxes.append(
            f'<div class="workflow-box" style="margin-top:16px;">'
            f"<strong>Drift detected:</strong> {badge} — {_esc(d.get('text'))} "
            f'<a href="{_esc(href)}"{_repo_wiki_link_attrs()}>View repo wiki →</a></div>'
        )
    readiness_html = (
        '<div class="component-box">'
        '<div class="readiness-top">'
        f'<div class="readiness-score">{score_html}</div>'
        f'<div class="readiness-driver">{driver_txt}</div>'
        "</div>"
        + "".join(bars_html)
        + ("".join(drift_boxes) or "")
        + "</div>"
    )

    activity_items = []
    for a in activity[:12]:
        activity_items.append(
            '<div class="activity-item">'
            f'<span class="dot-{_esc(a.get("color_slug"))}" style="width:8px;height:8px;border-radius:50%;margin-top:6px;flex-shrink:0;display:inline-block;"></span>'
            f"<span>{_esc(a.get('text'))}</span>"
            f'<span class="time">{_esc(_relative_time(a.get("at")))}</span>'
            "</div>"
        )
    activity_html = (
        f'<div class="activity-list">{"".join(activity_items) or "<div class=\"activity-item\"><span>No recent activity yet.</span></div>"}</div>'
    )

    synth_note_arch = _esc(architecture.get("synth_note") or "")
    live_badge = "Live" if overlay.get("assessed") else "Synthesized"
    header_badges = (
        f'<span class="scope-badge live"><span class="dot"></span>{_esc(live_badge)}</span>'
        f'<span class="scope-badge">🧩 {len(members)} repos</span>'
        f'<span class="scope-badge">🔄 Composed · readiness live</span>'
    )

    styles = _load_styles() + "\n" + _dynamic_repo_css(members)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_esc(app_name)} — Application Wiki</title>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10.6.1/dist/mermaid.min.js"></script>
    <style>
{styles}
    </style>
</head>
<body>
    <div class="top-header">
        <div>
            <h1>📚 {_esc(app_name)} Wiki</h1>
            <div class="crumb"><a href="{_esc(applications_href)}">Applications</a> / {_esc(app_name)}</div>
        </div>
        <div class="header-badges">{header_badges}</div>
    </div>
    <div class="container">
        <aside id="sidebar"><ul id="toc"></ul></aside>
        <main>
<section id="overview">
<h2>Overview</h2>
{blurb if blurb.startswith("<") else f"<p>{blurb}</p>"}
{stats_html}
{what_html}
{features_html}
</section>

<section id="architecture">
<h2>Composite Architecture
<span class="synth-note">{synth_note_arch}</span>
</h2>
{arch_body}
</section>

<section id="repos">
<h2>Repo Index</h2>
{repos_html}
</section>

<section id="api-surface">
<h2>Cross-Repo API Surface</h2>
{api_html}
</section>

<section id="tech-stack">
<h2>Technology Stack
<span class="synth-note">Union of member repo stacks — pure aggregation, no synthesis.</span>
</h2>
{tech_html}
</section>

<section id="specs">
<h2>Specs &amp; Steering
<span class="synth-note">Federated across spec-rich member repos.</span>
</h2>
{specs_html}
</section>

<section id="readiness">
<h2>Readiness &amp; Drift</h2>
{readiness_html}
</section>

<section id="activity">
<h2>Recent Activity</h2>
{activity_html}
</section>
        </main>
    </div>
    <script>
        mermaid.initialize({{ startOnLoad: true, theme: 'default' }});
        const sections = [
            {{ id: 'overview', title: '📋 Overview', level: 1 }},
            {{ id: 'architecture', title: '🏗️ Composite Architecture', level: 1 }},
            {{ id: 'repos', title: '📚 Repo Index', level: 1 }},
            {{ id: 'api-surface', title: '🔌 Cross-Repo API Surface', level: 1 }},
            {{ id: 'tech-stack', title: '📦 Technology Stack', level: 1 }},
            {{ id: 'specs', title: '🧭 Specs & Steering', level: 1 }},
            {{ id: 'readiness', title: '🚦 Readiness & Drift', level: 1 }},
            {{ id: 'activity', title: '🕒 Recent Activity', level: 1 }}
        ];
        const toc = document.getElementById('toc');
        sections.forEach(s => {{
            const li = document.createElement('li');
            li.className = `toc-level-${{s.level}}`;
            const a = document.createElement('a');
            a.href = `#${{s.id}}`;
            a.textContent = s.title;
            li.appendChild(a);
            toc.appendChild(li);
        }});
    </script>
</body>
</html>
"""


def _compile_markdown(composite: Dict[str, Any], overlay: Dict[str, Any]) -> str:
    lines = [f"# {composite.get('application_name')}", ""]
    if composite.get("description"):
        lines.extend([composite["description"], ""])
    lines.append("## Overview")
    lines.append("")
    lines.append((composite.get("overview") or {}).get("blurb") or "")
    lines.append("")
    lines.append("## Members")
    lines.append("")
    for m in composite.get("members") or []:
        lines.append(f"- **{m.get('short_name')}** ({m.get('role') or 'unknown'})")
    lines.append("")
    arch = (composite.get("architecture") or {}).get("mermaid")
    if arch:
        lines.extend(["## Composite Architecture", "", "```mermaid", arch, "```", ""])
    score = overlay.get("overall_score")
    lines.append(f"## Readiness: {score if score is not None else 'not assessed'}")
    return "\n".join(lines)


async def maybe_enrich_architecture_llm(
    composite: Dict[str, Any],
    *,
    db: Session,
    tenant_id: str,
) -> Dict[str, Any]:
    """Optional: ask LLM for dashed inferred edges. Never invent graph solid edges."""
    import os

    flag = (os.environ.get("WIKI_APP_ARCHITECTURE_LLM") or "0").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return composite

    mermaid = ((composite.get("architecture") or {}).get("mermaid") or "").strip()
    members = composite.get("members") or []
    if len(members) < 2:
        return composite

    try:
        from app.core.llm_client import get_llm_client
        from app.services.intelligence.wiki_generation_settings import (
            resolve_wiki_generation_settings,
        )

        gen = resolve_wiki_generation_settings(db, tenant_id)
        provider = gen.get("llm_provider") or "claude"
        if provider == "github_copilot":
            provider = "claude"
        llm = get_llm_client(provider, model_id=gen.get("llm_model") if provider == "bedrock" else None)
        member_lines = "\n".join(
            f"- {m['short_name']} id={m['repository_id']} role={m.get('role')} "
            f"overview={(m.get('overview_description') or '')[:200]}"
            for m in members
        )
        prompt = f"""Given this application and graph-derived Mermaid, suggest at most 3 dashed inferred edges
that are plausible but not proven. Return STRICT JSON only:
{{"inferred_edges":[{{"from":"short","to":"short","label":"reason","kind":"inferred"}}],
 "mermaid_extra":"optional extra mermaid lines using -.-> only"}}

Members:
{member_lines}

Existing mermaid:
{mermaid or '(none)'}
"""
        raw = await llm.generate(prompt)
        text = raw if isinstance(raw, str) else str(raw)
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
        inferred = data.get("inferred_edges") or []
        extra = (data.get("mermaid_extra") or "").strip()
        if extra and mermaid:
            composite["architecture"]["mermaid"] = mermaid + "\n" + extra
        composite["architecture"]["inferred_edges"] = inferred
        composite["generation_source"] = "application_wiki_composer+architecture_llm"
        log_pipeline(
            stage="app_wiki_architecture_llm",
            status="ok",
            message=f"Added {len(inferred)} inferred edge(s)",
            tenant_id=tenant_id,
        )
    except Exception as e:
        logger.warning("Application architecture LLM enrichment skipped: %s", e)
    return composite


async def compose_application_wiki(
    db: Session,
    tenant_id: str,
    application_id: str,
    *,
    enrich_architecture: bool = True,
) -> Dict[str, Any]:
    """Build composite.json + HTML + markdown; persist markers. Fast, no clone."""
    ctx = gather_member_context(db, tenant_id, application_id)
    if not ctx:
        raise ValueError("Application not found")

    app: Application = ctx["application"]
    analysis_dir = get_application_analysis_dir(tenant_id, application_id)
    analysis_dir.mkdir(parents=True, exist_ok=True)
    mark_started(analysis_dir)

    log_pipeline(
        stage="app_wiki_compose",
        status="start",
        message="Composing application wiki from member data",
        tenant_id=tenant_id,
        repository_name=app.name,
        extra={"application_id": application_id, "members": len(ctx["members"])},
    )

    composite = build_composite_payload(ctx)
    if enrich_architecture:
        composite = await maybe_enrich_architecture_llm(
            composite, db=db, tenant_id=tenant_id
        )

    overlay = load_live_overlay(db, tenant_id, application_id, composite)
    html_doc = render_application_wiki_html(
        composite,
        overlay,
        applications_href=f"/dashboard/intelligence/applications/{application_id}",
    )
    md = _compile_markdown(composite, overlay)

    (analysis_dir / COMPOSITE_JSON_NAME).write_text(
        json.dumps(composite, indent=2), encoding="utf-8"
    )
    (analysis_dir / WIKI_JSON_NAME).write_text(
        json.dumps(composite, indent=2), encoding="utf-8"
    )
    (analysis_dir / WIKI_HTML_NAME).write_text(html_doc, encoding="utf-8")
    (analysis_dir / WIKI_MD_NAME).write_text(md, encoding="utf-8")
    mark_completed(analysis_dir)
    invalidate_application_wiki_cache(tenant_id, application_id)

    log_pipeline(
        stage="app_wiki_compose",
        status="ok",
        message="Application wiki composed",
        tenant_id=tenant_id,
        repository_name=app.name,
        extra={"application_id": application_id},
    )

    return {
        "composite": composite,
        "overlay": overlay,
        "wiki_html": html_doc,
        "wiki_md": md,
        "wiki_json": composite,
        "analysis_dir": str(analysis_dir),
        "generation_source": composite.get("generation_source") or "application_wiki_composer",
    }


def load_application_composite_json(
    tenant_id: str,
    application_id: str,
) -> Optional[Dict[str, Any]]:
    """Load composed application wiki JSON from disk (composite.json or wiki_result.json)."""
    analysis_dir = get_application_analysis_dir(tenant_id, application_id)
    for name in (COMPOSITE_JSON_NAME, WIKI_JSON_NAME):
        path = analysis_dir / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("members") is not None:
            return data
    return None


def format_application_composite_for_chat(composite: Dict[str, Any]) -> str:
    """Compact application-level wiki context for grounded chat (not full HTML)."""
    lines: List[str] = []
    name = composite.get("application_name") or "Application"
    lines.append(f"## Application wiki: {name}")

    if composite.get("description"):
        lines.append(f"Description: {composite['description']}")
    if composite.get("domain"):
        lines.append(f"Domain: {composite['domain']}")

    overview = composite.get("overview") or {}
    if overview.get("blurb"):
        lines.append(f"Overview: {overview['blurb']}")
    for item in (overview.get("what_it_does") or [])[:6]:
        lines.append(f"- {item}")
    for feat in (overview.get("key_features") or [])[:8]:
        lines.append(f"- Feature: {feat}")

    lines.append("")
    lines.append("### Member repositories")
    for m in composite.get("members") or []:
        role = m.get("role") or "unknown"
        desc = (m.get("overview_description") or "").strip()
        line = f"- {m.get('short_name')} ({role})"
        if desc:
            line += f": {desc[:400]}"
        lines.append(line)

    arch = composite.get("architecture") or {}
    if arch.get("summary"):
        lines.append("")
        lines.append("### Composite architecture")
        lines.append(arch["summary"])
        edge_n = arch.get("graph_edge_count")
        if edge_n is not None:
            lines.append(f"Graph-derived cross-repo edges: {edge_n}")

    contracts = composite.get("contracts") or []
    if contracts:
        lines.append("")
        lines.append("### Cross-repo contracts")
        for c in contracts[:15]:
            exp = c.get("exposed_by") or "?"
            con = c.get("consumed_by") or "?"
            kind = c.get("kind") or c.get("source") or "link"
            lines.append(
                f"- `{c.get('contract')}` — {con} → {exp} ({kind})"
            )

    specs = composite.get("specs") or []
    if specs:
        lines.append("")
        lines.append("### Specs & steering (federated)")
        for s in specs[:10]:
            lines.append(f"- {s.get('short_name')}: {s.get('text')}")

    return "\n".join(lines)[:6000]


def render_live_application_wiki_html(
    db: Session,
    tenant_id: str,
    application_id: str,
) -> Optional[str]:
    """Serve HTML with fresh readiness/drift overlay over saved composite."""
    analysis_dir = get_application_analysis_dir(tenant_id, application_id)
    composite = load_application_composite_json(tenant_id, application_id)
    if not composite:
        return None
    overlay = load_live_overlay(db, tenant_id, application_id, composite)
    return render_application_wiki_html(
        composite,
        overlay,
        applications_href=f"/dashboard/intelligence/applications/{application_id}",
    )

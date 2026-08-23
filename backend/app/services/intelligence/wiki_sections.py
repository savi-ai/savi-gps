"""Build / enrich repository wiki ``sections_md`` from structured wiki JSON.

API/LLM wiki generation often returns structured fields without rich ``sections_md``.
Review pages (Overview, Architecture, …) read ``WikiPage.content_md`` from those
sections — this module synthesizes substantial markdown so review pages match
Full Wiki depth.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

# Fixed review-page slugs (must match WikiAgentService.SECTION_SLUGS)
REPO_SECTION_SLUGS: Tuple[str, ...] = (
    "overview",
    "architecture",
    "business_logic",
    "api_surface",
    "build_deploy",
)

# Below this (after stripping fences/noise), treat section as stub and replace.
_THIN_PROSE_CHARS = 280


def is_section_thin(content: Optional[str], *, min_prose_chars: int = _THIN_PROSE_CHARS) -> bool:
    """True when markdown is missing or mostly a stub heading / one-liner."""
    if not content or not str(content).strip():
        return True
    text = str(content)
    # Drop fenced code (incl. mermaid) — diagrams alone don't count as prose depth
    without_fences = re.sub(r"```[\s\S]*?```", " ", text)
    # Drop headings and bare bullets noise
    without_headings = re.sub(r"(?m)^#{1,6}\s+.*$", " ", without_fences)
    prose = re.sub(r"\s+", " ", without_headings).strip()
    if len(prose) < min_prose_chars:
        return True
    # Classic stub: single short paragraph
    if prose.count(".") <= 1 and len(prose) < min_prose_chars * 1.5:
        return True
    return False


def ensure_repo_sections_md(wiki_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure ``wiki_json['sections_md']`` has substantial markdown for each review slug.

    Mutates and returns ``wiki_json``. Existing rich sections are kept; thin/missing
    ones are rebuilt from structured fields.
    """
    sections = wiki_json.get("sections_md")
    if not isinstance(sections, dict):
        sections = {}
    else:
        sections = dict(sections)

    for slug in REPO_SECTION_SLUGS:
        existing = sections.get(slug)
        if is_section_thin(existing if isinstance(existing, str) else None):
            sections[slug] = build_section_md(slug, wiki_json)

    wiki_json["sections_md"] = sections
    return wiki_json


def build_section_md(slug: str, wiki_json: Dict[str, Any]) -> str:
    builders = {
        "overview": _build_overview,
        "architecture": _build_architecture,
        "business_logic": _build_business_logic,
        "api_surface": _build_api_surface,
        "build_deploy": _build_build_deploy,
    }
    fn = builders.get(slug)
    if not fn:
        return f"# {slug.replace('_', ' ').title()}\n"
    return fn(wiki_json)


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _cite(path: Any) -> str:
    if not path:
        return ""
    return f"`{path}`"


def _build_overview(wiki_json: Dict[str, Any]) -> str:
    repo = wiki_json.get("repo_name") or "Repository"
    o = _as_dict(wiki_json.get("overview"))
    func = _as_dict(wiki_json.get("functionality"))
    lines: List[str] = [f"# Overview\n"]

    desc = o.get("description") or o.get("summary") or f"Auto-generated wiki for {repo}."
    lines.append(f"{desc}\n")
    if o.get("purpose"):
        lines.append(f"**Purpose:** {o['purpose']}\n")

    loc = o.get("loc")
    files = o.get("file_count")
    meta_bits = []
    if loc is not None:
        meta_bits.append(f"{loc:,} LOC" if isinstance(loc, int) else f"{loc} LOC")
    if files is not None:
        meta_bits.append(f"{files} files")
    if meta_bits:
        lines.append(f"**Scale:** {', '.join(meta_bits)}\n")

    if func.get("summary") or func.get("bullets"):
        lines.append("## Functionality\n")
        if func.get("summary"):
            lines.append(f"{func['summary']}\n")
        for b in _as_list(func.get("bullets"))[:12]:
            lines.append(f"- {b}")
        lines.append("")

    tech = wiki_json.get("tech_stack") or []
    if isinstance(tech, list) and tech:
        lines.append("## Technology stack\n")
        for row in tech[:12]:
            if isinstance(row, dict):
                techs = row.get("technologies") or []
                if isinstance(techs, list):
                    tech_s = ", ".join(str(t) for t in techs)
                else:
                    tech_s = str(techs)
                evidence = _cite(row.get("evidence_file"))
                layer = row.get("layer") or "Stack"
                lines.append(f"- **{layer}:** {tech_s}" + (f" — {evidence}" if evidence else ""))
            elif row:
                lines.append(f"- {row}")
        lines.append("")

    attrs = wiki_json.get("analysis_attributes") or []
    if isinstance(attrs, list) and attrs:
        lines.append("## Analysis attributes\n")
        for a in attrs[:15]:
            if not isinstance(a, dict):
                continue
            key = a.get("label") or a.get("key") or "attr"
            val = a.get("value", "")
            evidence = _cite(a.get("source_file"))
            lines.append(f"- **{key}:** {val}" + (f" — {evidence}" if evidence else ""))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _architecture_prose(wiki_json: Dict[str, Any]) -> str:
    arch = wiki_json.get("architecture")
    if isinstance(arch, str) and arch.strip():
        # Avoid treating mermaid-only strings as prose
        if "graph " in arch[:40].lower() or arch.strip().startswith("flowchart"):
            return ""
        return arch.strip()
    if isinstance(arch, dict):
        parts = [
            arch.get("summary"),
            arch.get("pattern"),
            arch.get("description"),
            arch.get("style"),
        ]
        text = " ".join(str(p) for p in parts if p)
        if text.strip():
            return text.strip()
    o = _as_dict(wiki_json.get("overview"))
    # Prefer purpose + description as architecture narrative when dedicated field missing
    bits = [o.get("description"), o.get("purpose")]
    return " ".join(str(b) for b in bits if b).strip()


def _build_architecture(wiki_json: Dict[str, Any]) -> str:
    diagrams = _as_dict(wiki_json.get("diagrams"))
    bl = _as_dict(wiki_json.get("business_logic_layer"))
    lines: List[str] = ["# Architecture\n"]

    prose = _architecture_prose(wiki_json)
    if prose:
        lines.append("## Summary\n")
        lines.append(f"{prose}\n")
    else:
        lines.append(
            "## Summary\n\n"
            "Architecture inferred from indexed packages, services, and API entry points. "
            "See diagrams and core components below.\n"
        )

    high = (
        diagrams.get("high_level_mermaid")
        or diagrams.get("service_map_mermaid")
        or diagrams.get("low_level_mermaid")
    )
    if high:
        lines.append("## High-level view\n")
        lines.append(f"```mermaid\n{high.strip()}\n```\n")

    request = (
        diagrams.get("request_flow_mermaid")
        or diagrams.get("data_flow_mermaid")
        or _as_dict(wiki_json.get("data_flow")).get("diagram_mermaid")
    )
    if request and request != high:
        lines.append("## Request / data flow\n")
        lines.append(f"```mermaid\n{str(request).strip()}\n```\n")

    e2e = diagrams.get("e2e_flow_mermaid")
    if e2e and e2e not in (high, request):
        lines.append("## End-to-end flow\n")
        lines.append(f"```mermaid\n{str(e2e).strip()}\n```\n")

    deploy = diagrams.get("deployment_flow_mermaid")
    if deploy:
        lines.append("## Deployment topology\n")
        lines.append(f"```mermaid\n{str(deploy).strip()}\n```\n")

    tech = wiki_json.get("tech_stack") or []
    if isinstance(tech, list) and tech:
        lines.append("## Layers & technologies\n")
        lines.append("| Layer | Technologies | Evidence |")
        lines.append("| --- | --- | --- |")
        for row in tech[:15]:
            if not isinstance(row, dict):
                continue
            techs = row.get("technologies") or []
            tech_s = ", ".join(str(t) for t in techs) if isinstance(techs, list) else str(techs)
            evidence = row.get("evidence_file") or ""
            lines.append(
                f"| {row.get('layer') or '—'} | {tech_s or '—'} | {evidence or '—'} |"
            )
        lines.append("")

    components = _as_list(bl.get("components"))
    if components:
        lines.append("## Core components\n")
        if bl.get("summary"):
            lines.append(f"{bl['summary']}\n")
        for comp in components[:10]:
            if not isinstance(comp, dict):
                continue
            name = comp.get("name") or "Component"
            lines.append(f"### {name}\n")
            if comp.get("purpose"):
                lines.append(f"{comp['purpose']}\n")
            sources = _as_list(comp.get("source_files"))
            if sources:
                cites = ", ".join(_cite(s) for s in sources[:8] if s)
                if cites:
                    lines.append(f"**Evidence:** {cites}\n")
            for wf in _as_list(comp.get("workflows"))[:5]:
                if isinstance(wf, dict):
                    steps = wf.get("steps") or []
                    step_text = (
                        " → ".join(str(s) for s in steps)
                        if isinstance(steps, list)
                        else str(steps)
                    )
                    lines.append(f"- **{wf.get('operation', 'Workflow')}:** {step_text}")
                elif wf:
                    lines.append(f"- {wf}")
            if _as_list(comp.get("workflows")):
                lines.append("")
        lines.append("")

    data_flow = _as_dict(wiki_json.get("data_flow"))
    if data_flow.get("summary"):
        lines.append("## Data flow notes\n")
        lines.append(f"{data_flow['summary']}\n")

    db = _as_dict(wiki_json.get("database") or wiki_json.get("data_model"))
    if db.get("summary"):
        lines.append("## Data model\n")
        lines.append(f"{db['summary']}\n")
        dm = diagrams.get("data_model_mermaid")
        if dm:
            lines.append(f"```mermaid\n{str(dm).strip()}\n```\n")

    # Package hint from API / BL source files
    packages: List[str] = []
    for ep in _as_list(wiki_json.get("api_surface"))[:30]:
        if isinstance(ep, dict) and ep.get("file"):
            packages.append(str(ep["file"]).split("/")[0])
    for comp in components[:20]:
        if isinstance(comp, dict):
            for s in _as_list(comp.get("source_files"))[:5]:
                if s:
                    packages.append(str(s).split("/")[0])
    uniq = []
    seen = set()
    for p in packages:
        if p and p not in seen and p not in (".", ".."):
            seen.add(p)
            uniq.append(p)
    if uniq:
        lines.append("## Top-level packages (from evidence)\n")
        for p in uniq[:12]:
            lines.append(f"- `{p}/`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _build_business_logic(wiki_json: Dict[str, Any]) -> str:
    bl = _as_dict(wiki_json.get("business_logic_layer"))
    lines: List[str] = ["# Business Logic Layer\n"]
    summary = bl.get("summary") or bl.get("description") or ""
    if summary:
        lines.append(f"{summary}\n")

    components = _as_list(bl.get("components"))
    if not components:
        lines.append(
            "No core service/manager components were extracted. "
            "Re-index with CLI or a stronger LLM provider for deeper business-logic analysis.\n"
        )
        return "\n".join(lines)

    for comp in components[:12]:
        if isinstance(comp, str):
            lines.append(f"- {comp}")
            continue
        if not isinstance(comp, dict):
            continue
        lines.append(f"## {comp.get('name', 'Component')}\n")
        if comp.get("purpose"):
            lines.append(f"**Purpose:** {comp['purpose']}\n")
        sources = _as_list(comp.get("source_files"))
        if sources:
            lines.append("**Source files:**")
            for s in sources[:10]:
                if s:
                    lines.append(f"- {_cite(s)}")
            lines.append("")
        workflows = _as_list(comp.get("workflows"))
        if workflows:
            lines.append("**Key workflows:**\n")
            for wf in workflows:
                if isinstance(wf, dict):
                    steps = wf.get("steps") or []
                    step_text = (
                        " → ".join(str(s) for s in steps)
                        if isinstance(steps, list)
                        else str(steps)
                    )
                    lines.append(f"- **{wf.get('operation', 'Workflow')}:** {step_text}")
                else:
                    lines.append(f"- {wf}")
            lines.append("")
        rules = _as_list(comp.get("business_rules") or comp.get("rules"))
        if rules:
            lines.append("**Business rules:**\n")
            for rule in rules:
                if isinstance(rule, dict):
                    text = rule.get("rule") or rule.get("text") or json.dumps(rule)
                    evidence = _cite(rule.get("evidence_file"))
                    lines.append(f"- {text}" + (f" — {evidence}" if evidence else ""))
                else:
                    lines.append(f"- {rule}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_api_surface(wiki_json: Dict[str, Any]) -> str:
    items = wiki_json.get("api_surface")
    lines: List[str] = ["# API Surface\n"]

    endpoints: List[Any] = []
    if isinstance(items, dict):
        endpoints = _as_list(items.get("endpoints") or items.get("routes"))
        if items.get("summary"):
            lines.append(f"{items['summary']}\n")
    elif isinstance(items, list):
        endpoints = items
    elif items:
        lines.append(f"{items}\n")
        return "\n".join(lines)

    if not endpoints:
        lines.append("No HTTP/RPC endpoints detected in the index.\n")
        return "\n".join(lines)

    lines.append("| Method | Path / symbol | Description | Evidence |")
    lines.append("| --- | --- | --- | --- |")
    for ep in endpoints[:60]:
        if isinstance(ep, dict):
            method = ep.get("method") or ""
            path = ep.get("path") or ep.get("name") or ""
            desc = (ep.get("description") or "").replace("|", "/")
            file_ = ep.get("file") or ep.get("source_file") or ""
            lines.append(f"| `{method}` | `{path}` | {desc} | {file_ or '—'} |")
        else:
            lines.append(f"|  | `{ep}` |  | — |")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_build_deploy(wiki_json: Dict[str, Any]) -> str:
    b = _as_dict(wiki_json.get("build_deploy") or wiki_json.get("deployment_info"))
    run_local = _as_dict(wiki_json.get("run_locally"))
    diagrams = _as_dict(wiki_json.get("diagrams"))
    lines: List[str] = ["# Build & Deploy\n"]

    summary = b.get("summary") or b.get("hosting") or ""
    if summary:
        lines.append(f"{summary}\n")

    arts = [a for a in _as_list(b.get("artifacts")) if a]
    if arts:
        lines.append("## Artifacts & manifests\n")
        for a in arts[:25]:
            lines.append(f"- {_cite(a) if '/' in str(a) or '.' in str(a) else a}")
        lines.append("")

    deploy = diagrams.get("deployment_flow_mermaid")
    if deploy:
        lines.append("## Deployment flow\n")
        lines.append(f"```mermaid\n{str(deploy).strip()}\n```\n")

    if run_local.get("intro") or run_local.get("commands") or run_local.get("prerequisites"):
        lines.append("## Run locally\n")
        if run_local.get("intro"):
            lines.append(f"{run_local['intro']}\n")
        prereq = _as_list(run_local.get("prerequisites"))
        if prereq:
            lines.append("**Prerequisites:**")
            for p in prereq:
                lines.append(f"- {p}")
            lines.append("")
        if run_local.get("commands"):
            lines.append("```bash")
            lines.append(str(run_local["commands"]).rstrip())
            lines.append("```\n")

    if len(lines) <= 2:
        lines.append("Build and deploy details were not detected in the index.\n")

    return "\n".join(lines).rstrip() + "\n"

"""Build standalone HTML wiki from template + structured wiki_result JSON."""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "templates" / "wiki" / "wiki_site_template.html"

DEFAULT_HIGH_LEVEL = """graph TD
  client[Client] --> api[API Layer]
  api --> services[Services]
  services --> data[(Data Store)]"""

DEFAULT_LOW_LEVEL = """graph TD
  root[Repository Root] --> modules[Modules]
  modules --> components[Components]"""

DEFAULT_REQUEST_FLOW = """flowchart LR
  A[Request] --> B[Router]
  B --> C[Handler]
  C --> D[Response]"""

DEFAULT_DEPLOY = """flowchart TD
  A[Source] --> B[CI Build]
  B --> C[Artifact]
  C --> D[Deploy]"""


def _esc(value: Any) -> str:
    return html.escape(str(value) if value is not None else "")


def _bullets(items: List[str]) -> str:
    if not items:
        return "<li>Not detected</li>"
    return "\n".join(f"<li>{_esc(i)}</li>" for i in items)


def _tech_rows(stack: List[Dict]) -> str:
    if not stack:
        return "<tr><td colspan='3'>Not detected</td></tr>"
    rows = []
    for row in stack:
        techs = ", ".join(row.get("technologies") or [])
        evidence = row.get("evidence_file", "")
        rows.append(
            f"<tr><td>{_esc(row.get('layer', ''))}</td>"
            f"<td>{_esc(techs)}</td>"
            f"<td><code>{_esc(evidence)}</code></td></tr>"
        )
    return "\n".join(rows)


def _attr_rows(attrs: List[Dict]) -> str:
    if not attrs:
        return "<tr><td colspan='4'>No attributes extracted</td></tr>"
    rows = []
    for a in attrs:
        rows.append(
            f"<tr><td>{_esc(a.get('label', a.get('key', '')))}</td>"
            f"<td><strong>{_esc(a.get('value', ''))}</strong></td>"
            f"<td><code>{_esc(a.get('source_file', ''))}</code></td>"
            f"<td>{_esc(a.get('confidence', 'medium'))}</td></tr>"
        )
    return "\n".join(rows)


def _api_list(items: List[Dict]) -> str:
    if not items:
        return "<li>No API routes detected</li>"
    return "\n".join(
        f"<li><code>{_esc(i.get('file', ''))}</code> — {_esc(i.get('path', i.get('description', '')))}</li>"
        for i in items[:30]
    )


def _business_logic_html(business_logic: Optional[Dict[str, Any]]) -> str:
    if not business_logic:
        return "<p>Business logic not detected in index. Re-run indexing with Wiki Agent for deep analysis.</p>"

    parts: List[str] = []
    summary = business_logic.get("summary")
    if summary:
        parts.append(f"<p>{_esc(summary)}</p>")

    components = business_logic.get("components") or []
    if not components:
        return parts[0] if parts else "<p>No core components identified.</p>"

    for comp in components:
        name = comp.get("name", "Component")
        parts.append(f"<h3>{_esc(name)}</h3>")
        if comp.get("purpose"):
            parts.append(f"<p><strong>Purpose:</strong> {_esc(comp['purpose'])}</p>")
        sources = comp.get("source_files") or []
        if sources:
            src = ", ".join(f"<code>{_esc(s)}</code>" for s in sources[:8])
            parts.append(f"<p class='citation'>Sources: {src}</p>")

        workflows = comp.get("workflows") or []
        if workflows:
            parts.append("<p><strong>Key Workflows:</strong></p><ul>")
            for wf in workflows:
                op = wf.get("operation", "Operation")
                steps = wf.get("steps") or []
                flow = " → ".join(_esc(s) for s in steps) if steps else "Not detailed"
                parts.append(f"<li><strong>{_esc(op)}:</strong> {flow}</li>")
            parts.append("</ul>")

        rules = comp.get("business_rules") or []
        if rules:
            parts.append("<p><strong>Business Rules:</strong></p><ul>")
            for rule in rules:
                if isinstance(rule, dict):
                    text = rule.get("rule", "")
                    evidence = rule.get("evidence_file", "")
                    cite = f" <span class='citation'>({_esc(evidence)})</span>" if evidence else ""
                    parts.append(f"<li>{_esc(text)}{cite}</li>")
                else:
                    parts.append(f"<li>{_esc(rule)}</li>")
            parts.append("</ul>")

    return "\n".join(parts)


def build_wiki_html(
    wiki_json: Dict[str, Any],
    repo_name: str,
    repo_full_name: str,
    default_branch: str,
    index_run_id: Optional[str] = None,
    loc: int = 0,
    file_count: int = 0,
) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    overview = wiki_json.get("overview", {})
    functionality = wiki_json.get("functionality", {})
    diagrams = wiki_json.get("diagrams", {})
    build = wiki_json.get("build_deploy", {})
    run_local = wiki_json.get("run_locally", {})
    data_model = wiki_json.get("data_model") or wiki_json.get("database") or {}
    business_logic = wiki_json.get("business_logic_layer") or {}
    sections_md = wiki_json.get("sections_md") or {}
    bl_md = sections_md.get("business_logic")
    business_logic_html = (
        f"<div class='card'>{bl_md}</div>"
        if bl_md and bl_md.strip().startswith("#")
        else _business_logic_html(business_logic)
    )

    replacements = {
        "{{REPO_NAME}}": _esc(wiki_json.get("repo_name") or repo_name),
        "{{REPO_FULL_NAME}}": _esc(repo_full_name),
        "{{DEFAULT_BRANCH}}": _esc(default_branch),
        "{{LOC}}": _esc(f"{overview.get('loc', loc):,}"),
        "{{FILE_COUNT}}": _esc(str(overview.get("file_count", file_count))),
        "{{OVERVIEW_DESCRIPTION}}": _esc(overview.get("description", f"Auto-generated wiki for {repo_name}.")),
        "{{FUNCTIONALITY_SUMMARY}}": _esc(functionality.get("summary", "")),
        "{{FUNCTIONALITY_BULLETS}}": _bullets(functionality.get("bullets") or []),
        "{{TECH_STACK_ROWS}}": _tech_rows(wiki_json.get("tech_stack") or []),
        "{{ANALYSIS_ATTRIBUTE_ROWS}}": _attr_rows(wiki_json.get("analysis_attributes") or []),
        "{{HIGH_LEVEL_MERMAID}}": diagrams.get("high_level_mermaid") or DEFAULT_HIGH_LEVEL,
        "{{LOW_LEVEL_MERMAID}}": diagrams.get("low_level_mermaid") or DEFAULT_LOW_LEVEL,
        "{{BUSINESS_LOGIC_HTML}}": business_logic_html,
        "{{DATA_MODEL_SUMMARY}}": _esc(data_model.get("summary", "Entity relationships inferred from schema models.")),
        "{{DATA_MODEL_MERMAID}}": diagrams.get("data_model_mermaid") or "erDiagram\n  ENTITY ||--o{ RECORD : contains",
        "{{REQUEST_FLOW_MERMAID}}": diagrams.get("request_flow_mermaid") or DEFAULT_REQUEST_FLOW,
        "{{DEPLOYMENT_FLOW_MERMAID}}": diagrams.get("deployment_flow_mermaid") or DEFAULT_DEPLOY,
        "{{API_SURFACE_LIST}}": _api_list(wiki_json.get("api_surface") or []),
        "{{BUILD_DEPLOY_SUMMARY}}": _esc(build.get("summary", "")),
        "{{BUILD_ARTIFACTS_LIST}}": _bullets(build.get("artifacts") or []),
        "{{RUN_LOCALLY_INTRO}}": _esc(run_local.get("intro", "Steps to run this repository locally.")),
        "{{PREREQUISITES_LIST}}": _bullets(run_local.get("prerequisites") or []),
        "{{RUN_COMMANDS}}": _esc(run_local.get("commands", "# See README for setup instructions")),
        "{{OBSERVABILITY_SUMMARY}}": _esc((wiki_json.get("observability") or {}).get("summary", "Not detected")),
        "{{GENERATED_AT}}": datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        "{{INDEX_RUN_ID}}": _esc(index_run_id or "n/a"),
    }

    html_out = template
    for key, val in replacements.items():
        html_out = html_out.replace(key, val)
    return html_out

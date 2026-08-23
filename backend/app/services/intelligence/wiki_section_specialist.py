"""Section specialist LLM passes for thin wiki review pages (W1.4).

After ``ensure_repo_sections_md`` compiles structured fields into markdown,
sections that remain thin get a focused LLM rewrite grounded in wiki JSON +
code snippets. Priority: Architecture → Business Logic → API → Build → Overview.

Does not run on page browse — only during wiki generate / persist.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.llm_audit import log_llm_call
from app.core.logger import logger
from app.services.intelligence.wiki_sections import (
    REPO_SECTION_SLUGS,
    is_section_thin,
)
from app.services.llm_routing import get_llm_client, get_other_llm_client, resolve_wiki_generation

# Arch + BL first (Alpha differentiator), then the rest.
SPECIALIST_ORDER: Tuple[str, ...] = (
    "architecture",
    "business_logic",
    "api_surface",
    "build_deploy",
    "overview",
)

_SECTION_TITLES = {
    "overview": "Overview",
    "architecture": "Architecture",
    "business_logic": "Business Logic Layer",
    "api_surface": "API Surface",
    "build_deploy": "Build & Deploy",
}

_SECTION_FOCUS = {
    "overview": (
        "Write a substantive Overview: purpose, primary capabilities, scale, and tech stack. "
        "Cite evidence paths with backticks like `src/...`."
    ),
    "architecture": (
        "Write a deep Architecture page: layered/runtime style, main components, request/data flows, "
        "and how packages relate. Keep existing mermaid fences if present; add prose around them. "
        "Cite source paths with backticks."
    ),
    "business_logic": (
        "Write a deep Business Logic Layer page: core services/managers, workflows (step lists), "
        "business rules, and source file cites with backticks. Prefer concrete operations over fluff."
    ),
    "api_surface": (
        "Write an API Surface page: summarize entry points with method/path, purpose, and evidence files. "
        "Use a markdown table when endpoints exist. Cite paths with backticks."
    ),
    "build_deploy": (
        "Write Build & Deploy: artifacts, CI/CD hints, run-locally steps, and deployment topology notes. "
        "Cite manifests with backticks."
    ),
}


def specialist_enabled() -> bool:
    flag = (os.environ.get("WIKI_SECTION_SPECIALIST") or "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def list_thin_section_slugs(
    wiki_json: Dict[str, Any],
    *,
    order: Sequence[str] = SPECIALIST_ORDER,
    min_prose_chars: int = 280,
) -> List[str]:
    """Return thin section slugs in specialist priority order."""
    sections = wiki_json.get("sections_md")
    if not isinstance(sections, dict):
        sections = {}
    thin: List[str] = []
    for slug in order:
        if slug not in REPO_SECTION_SLUGS:
            continue
        raw = sections.get(slug)
        if is_section_thin(
            raw if isinstance(raw, str) else None,
            min_prose_chars=min_prose_chars,
        ):
            thin.append(slug)
    return thin


def _structured_context(slug: str, wiki_json: Dict[str, Any]) -> Dict[str, Any]:
    """Compact structured fields relevant to a section (grounding, not full wiki)."""
    base = {
        "repo_name": wiki_json.get("repo_name"),
        "overview": wiki_json.get("overview"),
        "tech_stack": wiki_json.get("tech_stack"),
    }
    if slug == "overview":
        base["functionality"] = wiki_json.get("functionality")
        base["analysis_attributes"] = (wiki_json.get("analysis_attributes") or [])[:12]
    elif slug == "architecture":
        base["architecture"] = wiki_json.get("architecture")
        base["diagrams"] = wiki_json.get("diagrams")
        base["business_logic_layer"] = wiki_json.get("business_logic_layer")
        base["data_flow"] = wiki_json.get("data_flow")
        base["database"] = wiki_json.get("database") or wiki_json.get("data_model")
    elif slug == "business_logic":
        base["business_logic_layer"] = wiki_json.get("business_logic_layer")
        base["functionality"] = wiki_json.get("functionality")
    elif slug == "api_surface":
        base["api_surface"] = wiki_json.get("api_surface")
        base["diagrams"] = {
            k: v
            for k, v in (wiki_json.get("diagrams") or {}).items()
            if k in ("request_flow_mermaid", "e2e_flow_mermaid")
        } if isinstance(wiki_json.get("diagrams"), dict) else {}
    elif slug == "build_deploy":
        base["build_deploy"] = wiki_json.get("build_deploy") or wiki_json.get("deployment_info")
        base["run_locally"] = wiki_json.get("run_locally")
        diagrams = wiki_json.get("diagrams") if isinstance(wiki_json.get("diagrams"), dict) else {}
        base["deployment_flow_mermaid"] = diagrams.get("deployment_flow_mermaid")
    return base


def _snippet_hints_for_slug(slug: str) -> Tuple[str, ...]:
    if slug == "architecture":
        return ("arch", "config", "main", "app.", "application", "router", "module")
    if slug == "business_logic":
        return ("service", "manager", "handler", "usecase", "impl", "logic", "processor")
    if slug == "api_surface":
        return ("controller", "router", "route", "api", "endpoint", "handler", "openapi", "swagger")
    if slug == "build_deploy":
        return (
            "dockerfile",
            "docker-compose",
            "pom.xml",
            "package.json",
            "makefile",
            "github/workflows",
            "build.",
            "deploy",
            "helm",
            "k8s",
            "terraform",
        )
    return ("readme", "package", "pom", "requirements", "go.mod")


def filter_snippets_for_section(slug: str, code_snippets: str, *, max_chars: int = 9000) -> str:
    """Prefer snippet blocks whose paths match the section; fall back to head of all."""
    raw = (code_snippets or "").strip()
    if not raw:
        return ""
    blocks = re.split(r"(?=^### )", raw, flags=re.M)
    blocks = [b for b in blocks if b.strip()]
    hints = _snippet_hints_for_slug(slug)
    preferred: List[str] = []
    other: List[str] = []
    for block in blocks:
        first = block.split("\n", 1)[0].lower()
        if any(h in first for h in hints):
            preferred.append(block)
        else:
            other.append(block)
    ordered = preferred + other
    out: List[str] = []
    total = 0
    for block in ordered:
        if total + len(block) > max_chars:
            break
        out.append(block)
        total += len(block)
    return "\n".join(out)


def _strip_md_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
    return cleaned.strip()


def _resolve_specialist_client(db: Optional[Session], tenant_id: Optional[str]):
    wiki = resolve_wiki_generation(db, tenant_id)
    provider = (
        wiki.get("wiki_generation_provider")
        or wiki.get("llm_provider")
        or settings.LLM_PROVIDER
        or "claude"
    ).lower()
    if provider in ("github_copilot", "anthropic"):
        # Specialist is API-only; Copilot wiki mode falls back to Other LLM.
        if provider == "github_copilot":
            return get_other_llm_client(db, tenant_id), resolve_wiki_generation(db, tenant_id)
        provider = "claude"
    model = wiki.get("llm_model")
    if provider == "claude" and not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")
    if provider == "openai" and not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set")
    client = get_llm_client(
        provider,
        model_id=model if provider in ("bedrock", "ollama") else None,
    )
    return client, {"provider": provider, "model": model}


async def _llm_rewrite_section(
    *,
    db: Optional[Session],
    tenant_id: Optional[str],
    repository_id: Optional[str],
    slug: str,
    wiki_json: Dict[str, Any],
    current_md: str,
    code_snippets: str,
) -> Optional[str]:
    title = _SECTION_TITLES.get(slug, slug)
    focus = _SECTION_FOCUS.get(slug, "Deepen this wiki section with evidence cites.")
    context = _structured_context(slug, wiki_json)
    snippets = filter_snippets_for_section(slug, code_snippets)

    system = (
        "You are a repository wiki section specialist for Savi GPS. "
        "Return ONLY markdown for one wiki review page. "
        "Ground every claim in the structured context or code snippets. "
        "Cite file paths with backticks. Do not invent APIs, services, or files. "
        "Do not wrap the whole answer in a markdown fence. "
        f"Start with a level-1 heading: # {title}"
    )
    prompt = (
        f"{focus}\n\n"
        f"Repository: {wiki_json.get('repo_name') or 'unknown'}\n"
        f"Section slug: {slug}\n\n"
        f"Structured context (JSON):\n{json.dumps(context, indent=2)[:12000]}\n\n"
        f"Current thin draft (improve / replace):\n{current_md[:4000]}\n\n"
        f"Code snippets:\n{snippets[:9000] or '(none provided — rely on structured context only)'}\n"
    )

    t0 = time.monotonic()
    try:
        client, meta = _resolve_specialist_client(db, tenant_id)
        provider = meta.get("provider") or "claude"
        model = meta.get("model")
        raw = await client.generate(
            prompt,
            system_prompt=system,
            temperature=0.2,
            max_tokens=4096,
        )
        duration_ms = int((time.monotonic() - t0) * 1000)
        md = _strip_md_fences(raw)
        if is_section_thin(md):
            log_llm_call(
                purpose="wiki_section_specialist",
                provider=provider,
                model=model,
                tenant_id=tenant_id,
                entity_type="repository",
                entity_id=repository_id,
                status="still_thin",
                duration_ms=duration_ms,
                extra={"slug": slug},
            )
            return None
        log_llm_call(
            purpose="wiki_section_specialist",
            provider=provider,
            model=model,
            tenant_id=tenant_id,
            entity_type="repository",
            entity_id=repository_id,
            status="ok",
            duration_ms=duration_ms,
            extra={"slug": slug, "chars": len(md)},
        )
        return md
    except Exception as e:
        duration_ms = int((time.monotonic() - t0) * 1000)
        log_llm_call(
            purpose="wiki_section_specialist",
            provider="unknown",
            tenant_id=tenant_id,
            entity_type="repository",
            entity_id=repository_id,
            status="error",
            duration_ms=duration_ms,
            error=str(e),
            extra={"slug": slug},
        )
        logger.warning("Section specialist failed for %s: %s", slug, e)
        return None


async def enrich_thin_sections(
    wiki_json: Dict[str, Any],
    *,
    db: Optional[Session] = None,
    tenant_id: Optional[str] = None,
    repository_id: Optional[str] = None,
    code_snippets: str = "",
    max_sections: int = 5,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """
    Mutate ``wiki_json['sections_md']`` for thin sections via specialist LLM.

    Returns a small report: ``{ attempted, enriched, skipped, thin_before }``.
    """
    report: Dict[str, Any] = {
        "attempted": [],
        "enriched": [],
        "skipped": [],
        "thin_before": [],
        "enabled": specialist_enabled() and use_llm,
    }
    if not isinstance(wiki_json, dict):
        return report

    sections = wiki_json.get("sections_md")
    if not isinstance(sections, dict):
        sections = {}
    else:
        sections = dict(sections)
    wiki_json["sections_md"] = sections

    thin = list_thin_section_slugs(wiki_json)
    report["thin_before"] = list(thin)

    if not specialist_enabled() or not use_llm:
        report["skipped"] = thin
        return report

    if not thin:
        return report

    # Probe credentials once; if unavailable, skip all without N errors
    try:
        _resolve_specialist_client(db, tenant_id)
    except Exception as e:
        logger.info("Section specialist skipped (no LLM client): %s", e)
        report["skipped"] = thin
        return report

    for slug in thin[: max(0, max_sections)]:
        report["attempted"].append(slug)
        current = sections.get(slug) or f"# {_SECTION_TITLES.get(slug, slug)}\n"
        md = await _llm_rewrite_section(
            db=db,
            tenant_id=tenant_id,
            repository_id=repository_id,
            slug=slug,
            wiki_json=wiki_json,
            current_md=str(current),
            code_snippets=code_snippets or "",
        )
        if md:
            sections[slug] = md if md.endswith("\n") else md + "\n"
            report["enriched"].append(slug)
            logger.info(
                "Section specialist enriched %s (%s chars) for repo=%s",
                slug,
                len(md),
                repository_id,
            )
        else:
            report["skipped"].append(slug)

    wiki_json["sections_md"] = sections
    wiki_json["sections_specialist"] = {
        "enriched": report["enriched"],
        "attempted": report["attempted"],
        "thin_before": report["thin_before"],
    }
    return report

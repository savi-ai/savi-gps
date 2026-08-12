"""Wiki Agent — generates structured wiki JSON and HTML for indexed repositories."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logger import logger
from app.core.secret_redaction import redact_secrets
from app.services.agents.base_agent import BaseAgent
from app.services.intelligence.analysis_storage import (
    CONFIG_NAME,
    WIKI_HTML_NAME,
    WIKI_JSON_NAME,
    WIKI_MD_NAME,
    mark_failed,
    mark_started,
    persist_analysis_artifacts,
)
from app.services.intelligence.code_chunker import FileChunk
from app.services.intelligence.mermaid_sanitize import sanitize_wiki_json_mermaid
from app.services.intelligence.wiki_html_builder import build_wiki_html
from app.services.intelligence.wiki_generation_settings import resolve_wiki_generation_settings

DEEP_WIKI_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "prompts" / "wiki_deep_analysis.txt"
)
APP_WIKI_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "prompts" / "wiki_application_deep_analysis.txt"
)

IMPL_NAME_MARKERS = (
    "impl", "service", "logic", "manager", "handler", "usecase", "use_case", "processor",
)


def _parse_llm_json(text: str) -> Dict[str, Any]:
    """Parse JSON from LLM response, tolerating markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def _agent_subprocess_env() -> Dict[str, str]:
    """Subprocess env with API keys from app settings (not only os.environ)."""
    env = os.environ.copy()
    if settings.ANTHROPIC_API_KEY:
        env["ANTHROPIC_API_KEY"] = settings.ANTHROPIC_API_KEY
    if settings.OPENAI_API_KEY:
        env["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    return env


def _load_deep_wiki_prompt() -> str:
    if DEEP_WIKI_PROMPT_PATH.is_file():
        return DEEP_WIKI_PROMPT_PATH.read_text(encoding="utf-8")
    return ""


def _load_application_wiki_prompt() -> str:
    if APP_WIKI_PROMPT_PATH.is_file():
        return APP_WIKI_PROMPT_PATH.read_text(encoding="utf-8")
    return ""


def _compile_wiki_md(wiki_json: Dict[str, Any], repo_name: str) -> str:
    sections = wiki_json.get("sections_md") or {}
    order = (
        "overview",
        "components",
        "integration",
        "dependencies",
        "service_map",
        "architecture",
        "business_logic",
        "api_surface",
        "data_flow",
        "e2e_flow",
        "database",
        "build_deploy",
    )
    parts: List[str] = []
    for key in order:
        content = sections.get(key)
        if content and content.strip():
            parts.append(content.strip())

    if not parts:
        bl = wiki_json.get("business_logic_layer") or {}
        overview = wiki_json.get("overview", {})
        title = wiki_json.get("application_name") or repo_name
        parts.append(f"# {title}\n\n{overview.get('description', '')}")
        if bl.get("summary"):
            parts.append(f"# Components\n\n{bl['summary']}")
        for comp in bl.get("components") or []:
            parts.append(f"## {comp.get('name', 'Component')}\n\n{comp.get('purpose', '')}")
        integration = wiki_json.get("integration") or {}
        if isinstance(integration, dict) and integration.get("summary"):
            parts.append(f"# Integration\n\n{integration['summary']}")
        elif isinstance(integration, str) and integration.strip():
            parts.append(f"# Integration\n\n{integration}")

    return "\n\n".join(parts) if parts else f"# {repo_name}\n\nWiki content pending deep analysis.\n"


class WikiAgent(BaseAgent):
    """Analyzes repository content and produces wiki_result.json + wiki_site.html + wiki_site.md."""

    SYSTEM_PROMPT = """You are the Savi GPS Wiki Agent — a principal engineer producing Deep Wiki quality documentation.

You analyze IMPLEMENTATION files (*Impl.java, *Service.java, *Manager.py, handlers) — not just interfaces.
Extract step-by-step workflows and business rules with file citations.

Return STRICT JSON only (no markdown fences) matching the requested schema.
Include mermaid diagrams: high_level_mermaid, low_level_mermaid, data_model_mermaid,
request_flow_mermaid, e2e_flow_mermaid, deployment_flow_mermaid.
You MUST include business_logic_layer with detailed components, workflows, and business_rules.
Extract analysis_attributes for every key in attribute_definitions.
Do not hallucinate — omit or mark "Not detected" when evidence is missing."""

    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        repository = state.get("repository", {})
        chunks: List[FileChunk] = state.get("chunks", [])
        loc = state.get("loc", 0)
        clone_path = state.get("clone_path")
        attribute_definitions = state.get("attribute_definitions", [])
        index_run_id = state.get("index_run_id")
        output_dir: Optional[Path] = state.get("output_dir")
        repository_id = state.get("repository_id")

        if output_dir is None:
            raise ValueError("output_dir (analysis directory) is required")

        output_dir = Path(output_dir)
        mark_started(output_dir)

        repo_name = repository.get("name", "repository")
        repo_full_name = repository.get("github_full_name") or repository.get("url", "")
        default_branch = repository.get("default_branch", "main")
        org_name = repository.get("github_org") or repository.get("github_owner") or "unknown-org"

        gen_settings = state.get("wiki_generation_settings") or resolve_wiki_generation_settings()
        generation_mode = gen_settings.get("wiki_generation_mode") or "auto"
        wiki_provider = (
            gen_settings.get("wiki_generation_provider")
            or gen_settings.get("llm_provider")
            or settings.LLM_PROVIDER
        )
        uses_copilot_cli = bool(gen_settings.get("uses_copilot_cli")) or (
            wiki_provider == "github_copilot"
        )
        agent_cli = gen_settings.get("agent_cli") or (
            "copilot" if uses_copilot_cli else "claude"
        )
        # API path never uses github_copilot as get_llm_client provider
        llm_provider = gen_settings.get("llm_provider") or settings.LLM_PROVIDER
        if llm_provider == "github_copilot":
            llm_provider = "claude"
        llm_model = gen_settings.get("llm_model")

        refresh_plan = state.get("wiki_refresh_plan")
        previous_wiki_json = state.get("previous_wiki_json")
        git_head = state.get("git_head")
        refresh_mode = getattr(refresh_plan, "mode", None) if refresh_plan else state.get("wiki_refresh_mode")
        refresh_reason = getattr(refresh_plan, "reason", None) if refresh_plan else state.get("wiki_refresh_reason")

        shell_invoked = False
        shell_succeeded = False
        generation_source = "wiki_agent_fallback"
        wiki_json = None
        wiki_html = None
        wiki_md = None

        allow_cli = generation_mode in ("cli", "auto") and bool(clone_path)
        # Copilot wiki is CLI-only — do not fall through to API with a fake provider
        allow_api = generation_mode in ("api", "auto") and not uses_copilot_cli
        allow_fallback = generation_mode != "cli" and not uses_copilot_cli

        # Incremental updates use the API path (patch prior wiki from git diffs).
        # CLI shell scripts always regenerate fully.
        if (
            refresh_mode == "incremental"
            and previous_wiki_json
            and allow_api
            and clone_path
            and refresh_plan
        ):
            try:
                from app.services.intelligence.wiki_git_refresh import (
                    format_incremental_prompt_context,
                )

                change_ctx = format_incremental_prompt_context(refresh_plan, str(clone_path))
                wiki_json = await self._generate_incremental_via_llm(
                    repo_name=repo_name,
                    repo_full_name=repo_full_name,
                    previous_wiki=previous_wiki_json,
                    change_context=change_ctx,
                    chunks=chunks,
                    attribute_definitions=attribute_definitions,
                    provider=llm_provider,
                    model_id=llm_model,
                )
                generation_source = f"wiki_agent_llm_incremental:{llm_provider}"
            except Exception as e:
                logger.warning(
                    "Incremental wiki LLM failed (%s); falling back to full generation",
                    redact_secrets(str(e)),
                )
                wiki_json = None

        if not wiki_json and allow_cli:
            shell_invoked = True
            shell_result = await self._run_shell_agent(
                org_name=org_name,
                repo_slug=repo_name,
                clone_path=clone_path,
                output_dir=output_dir,
                attribute_definitions=attribute_definitions,
                agent_cli=agent_cli,
            )
            if shell_result and shell_result.get("wiki_json"):
                shell_succeeded = True
                if shell_result.get("recovered_partial"):
                    generation_source = f"wiki_agent_shell_partial:{agent_cli}"
                else:
                    generation_source = f"wiki_agent_shell:{agent_cli}"
                wiki_json = shell_result["wiki_json"]
                wiki_html = shell_result.get("wiki_html")
                wiki_md = shell_result.get("wiki_md")
            elif generation_mode == "cli":
                # Strict CLI mode: no API fallback. Partial recovery already attempted.
                detail = (shell_result or {}).get("error") or "unknown CLI failure"
                err = (
                    f"Wiki CLI generation failed (AGENT_CLI={agent_cli}): {detail}"
                )
                logger.error(redact_secrets(err))
                mark_failed(output_dir, redact_secrets(err)[:4000])
                raise RuntimeError(err)
            elif uses_copilot_cli and generation_mode == "auto":
                # Copilot CLI timed out / failed — fall through to API with llm_provider
                logger.warning(
                    "Copilot CLI wiki failed (%s); falling back to API (%s)",
                    (shell_result or {}).get("error", "unknown")[:200],
                    llm_provider,
                )
            elif uses_copilot_cli:
                detail = (shell_result or {}).get("error") or "unknown CLI failure"
                err = (
                    f"Wiki CLI generation failed (AGENT_CLI={agent_cli}): {detail}"
                )
                logger.error(redact_secrets(err))
                mark_failed(output_dir, redact_secrets(err)[:4000])
                raise RuntimeError(err)

        # After CLI failure in auto mode, allow API even when provider was Copilot
        allow_api_after_cli = (
            generation_mode == "auto" and shell_invoked and not shell_succeeded
        )

        if not wiki_json and (allow_api or allow_api_after_cli):
            if shell_invoked and not shell_succeeded:
                logger.warning(
                    "wiki_agent.sh did not produce artifacts in %s — using LLM API (%s)",
                    output_dir,
                    llm_provider,
                )
            try:
                wiki_json = await self._generate_via_llm(
                    repo_name,
                    repo_full_name,
                    chunks,
                    loc,
                    attribute_definitions,
                    provider=llm_provider,
                    model_id=llm_model,
                )
                generation_source = f"wiki_agent_llm:{llm_provider}"
            except Exception as e:
                logger.error("WikiAgent LLM failed: %s", redact_secrets(str(e)))
                if generation_mode == "api" or not allow_fallback:
                    mark_failed(output_dir, redact_secrets(str(e)))
                    raise
                mark_failed(output_dir, redact_secrets(str(e)))
                wiki_json = self._fallback_json(
                    repo_name, loc, len({c.file_path for c in chunks}),
                    Counter(c.language or "unknown" for c in chunks),
                    Counter(c.file_path.split("/")[0] for c in chunks if "/" in c.file_path),
                    sorted({c.file_path for c in chunks})[:80],
                    [], [],
                )
                generation_source = "wiki_agent_fallback"

        if not wiki_json:
            wiki_json = self._fallback_json(
                repo_name, loc, len({c.file_path for c in chunks}),
                Counter(c.language or "unknown" for c in chunks),
                Counter(c.file_path.split("/")[0] for c in chunks if "/" in c.file_path),
                sorted({c.file_path for c in chunks})[:80],
                [], [],
            )
            generation_source = "wiki_agent_fallback"

        wiki_json = sanitize_wiki_json_mermaid(wiki_json)

        if not wiki_html:
            wiki_html = build_wiki_html(
                wiki_json,
                repo_name=repo_name,
                repo_full_name=repo_full_name,
                default_branch=default_branch,
                index_run_id=index_run_id,
                loc=loc,
                file_count=len({c.file_path for c in chunks}),
            )

        if not wiki_md:
            wiki_md = _compile_wiki_md(wiki_json, repo_name)
        else:
            from app.services.intelligence.mermaid_sanitize import degrade_mermaid_fences

            wiki_md, _ = degrade_mermaid_fences(wiki_md)

        paths = persist_analysis_artifacts(
            output_dir,
            wiki_json,
            wiki_html,
            wiki_md=wiki_md,
            index_run_id=index_run_id,
            generation_source=generation_source,
            shell_invoked=shell_invoked,
            shell_succeeded=shell_succeeded,
            repository_id=repository_id,
            mark_complete=generation_source != "wiki_agent_fallback",
            extra_meta={
                "generation_mode": generation_mode,
                "wiki_generation_provider": wiki_provider,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
                "agent_cli": agent_cli,
                "git_head": git_head,
                "wiki_refresh_mode": refresh_mode or "full",
                "wiki_refresh_reason": refresh_reason,
            },
        )

        state["wiki_json"] = wiki_json
        state["wiki_html"] = wiki_html
        state["wiki_md"] = wiki_md
        state["sections_md"] = wiki_json.get("sections_md", {})
        state["generation_source"] = generation_source
        state["generation_mode"] = generation_mode
        state["llm_provider"] = llm_provider
        state["wiki_generation_provider"] = wiki_provider
        state["shell_invoked"] = shell_invoked
        state["shell_succeeded"] = shell_succeeded
        state["analysis_paths"] = paths
        state["git_head"] = git_head
        state["wiki_refresh_mode"] = refresh_mode or "full"
        state["wiki_refresh_reason"] = refresh_reason
        return state

    async def process_application(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Generate an application-level wiki from a multi-repo workspace."""
        application = state.get("application") or {}
        workspace_path = state.get("workspace_path")
        output_dir: Optional[Path] = state.get("output_dir")
        application_id = state.get("application_id")
        manifest = state.get("manifest") or {}
        service_map_mermaid = state.get("service_map_mermaid") or ""

        if not workspace_path:
            raise ValueError("workspace_path is required for application wiki")
        if output_dir is None:
            raise ValueError("output_dir (analysis directory) is required")

        output_dir = Path(output_dir)
        mark_started(output_dir)

        app_name = application.get("name") or "Application"
        gen_settings = state.get("wiki_generation_settings") or resolve_wiki_generation_settings()
        generation_mode = gen_settings.get("wiki_generation_mode") or "auto"
        wiki_provider = (
            gen_settings.get("wiki_generation_provider")
            or gen_settings.get("llm_provider")
            or settings.LLM_PROVIDER
        )
        uses_copilot_cli = bool(gen_settings.get("uses_copilot_cli")) or (
            wiki_provider == "github_copilot"
        )
        llm_provider = gen_settings.get("llm_provider") or settings.LLM_PROVIDER
        if llm_provider == "github_copilot":
            llm_provider = "claude"
        llm_model = gen_settings.get("llm_model")

        # Application wiki is multi-repo. Copilot/Claude CLI routinely hangs on the
        # workspace root (hour-long timeout, no artifacts). Always use the LLM API
        # here; tenant CLI mode still applies to per-repo wikis during indexing.
        agent_cli = gen_settings.get("agent_cli") or (
            "copilot" if uses_copilot_cli else "claude"
        )
        if uses_copilot_cli or generation_mode == "cli":
            logger.info(
                "Application wiki skipping CLI (mode=%s provider=%s) — using LLM API",
                generation_mode,
                wiki_provider,
            )

        shell_invoked = False
        shell_succeeded = False
        generation_source = "wiki_agent_application_fallback"
        wiki_json = None
        wiki_html = None
        wiki_md = None

        if not wiki_json:
            try:
                wiki_json = await self._generate_application_via_llm(
                    app_name=app_name,
                    application=application,
                    workspace_path=str(workspace_path),
                    manifest=manifest,
                    service_map_mermaid=service_map_mermaid,
                    provider=llm_provider,
                    model_id=llm_model,
                )
                generation_source = f"wiki_agent_llm_application:{llm_provider}"
            except Exception as e:
                logger.error("Application WikiAgent LLM failed: %s", redact_secrets(str(e)))
                wiki_json = self._fallback_application_json(
                    app_name, manifest, service_map_mermaid
                )
                generation_source = "wiki_agent_application_fallback"

        if not wiki_json:
            wiki_json = self._fallback_application_json(
                app_name, manifest, service_map_mermaid
            )
            generation_source = "wiki_agent_application_fallback"

        wiki_json = sanitize_wiki_json_mermaid(wiki_json)
        wiki_json.setdefault("application_name", app_name)
        wiki_json.setdefault("repo_name", app_name)

        # Map service_map_mermaid into diagrams for HTML builder compatibility
        diagrams = wiki_json.setdefault("diagrams", {})
        if service_map_mermaid and not diagrams.get("high_level_mermaid"):
            diagrams["high_level_mermaid"] = service_map_mermaid
        if diagrams.get("service_map_mermaid") and not diagrams.get("high_level_mermaid"):
            diagrams["high_level_mermaid"] = diagrams["service_map_mermaid"]

        # Surface components as business_logic_layer for HTML builder
        if wiki_json.get("components") and not wiki_json.get("business_logic_layer"):
            comps = wiki_json["components"]
            if isinstance(comps, list):
                wiki_json["business_logic_layer"] = {
                    "summary": f"{len(comps)} application components",
                    "components": [
                        {
                            "name": c.get("name") or c.get("repository_name") or "Component",
                            "purpose": c.get("purpose") or c.get("role") or "",
                            "source_files": c.get("source_files") or [],
                            "workflows": c.get("workflows") or [],
                            "business_rules": c.get("business_rules") or [],
                        }
                        for c in comps
                        if isinstance(c, dict)
                    ],
                }

        if not wiki_html:
            wiki_html = build_wiki_html(
                wiki_json,
                repo_name=app_name,
                repo_full_name=application.get("description") or app_name,
                default_branch="application",
                index_run_id=None,
                loc=0,
                file_count=len((manifest.get("members") or [])),
            )

        if not wiki_md:
            wiki_md = _compile_wiki_md(wiki_json, app_name)
        else:
            from app.services.intelligence.mermaid_sanitize import degrade_mermaid_fences

            wiki_md, _ = degrade_mermaid_fences(wiki_md)

        paths = persist_analysis_artifacts(
            output_dir,
            wiki_json,
            wiki_html,
            wiki_md=wiki_md,
            index_run_id=None,
            generation_source=generation_source,
            shell_invoked=shell_invoked,
            shell_succeeded=shell_succeeded,
            repository_id=None,
            mark_complete=generation_source != "wiki_agent_application_fallback",
            extra_meta={
                "scope": "application",
                "application_id": application_id,
                "generation_mode": generation_mode,
                "wiki_generation_provider": wiki_provider,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
                "workspace_path": str(workspace_path),
                "member_count": len(manifest.get("members") or []),
            },
        )

        state["wiki_json"] = wiki_json
        state["wiki_html"] = wiki_html
        state["wiki_md"] = wiki_md
        state["sections_md"] = wiki_json.get("sections_md", {})
        state["generation_source"] = generation_source
        state["shell_invoked"] = shell_invoked
        state["shell_succeeded"] = shell_succeeded
        state["analysis_paths"] = paths
        return state

    def _scan_application_workspace(
        self,
        workspace_path: str,
        *,
        max_files_per_repo: int = 60,
        max_snippet_chars: int = 12000,
    ) -> Dict[str, Any]:
        """Collect file trees and light snippets from each member clone."""
        root = Path(workspace_path)
        repos_root = root / "repos"
        members_out: List[Dict[str, Any]] = []
        skip_dirs = {
            ".git", "node_modules", "vendor", "dist", "build", ".next",
            "__pycache__", ".venv", "venv", "target", "coverage",
        }
        exts = {
            ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs",
            ".kt", ".cs", ".rb", ".md", ".yml", ".yaml", ".json", ".toml",
            ".gradle", ".xml",
        }

        if not repos_root.is_dir():
            return {"members": members_out}

        for repo_dir in sorted(repos_root.iterdir()):
            if not repo_dir.is_dir():
                continue
            files: List[str] = []
            snippets: List[str] = []
            total_snip = 0
            for path in repo_dir.rglob("*"):
                if not path.is_file():
                    continue
                if any(part in skip_dirs for part in path.parts):
                    continue
                if path.suffix.lower() not in exts and path.name not in (
                    "Dockerfile", "Makefile", "README", "README.md",
                ):
                    continue
                rel = path.relative_to(root).as_posix()
                files.append(rel)
                if len(files) > max_files_per_repo * 3:
                    break
                if total_snip < max_snippet_chars and (
                    any(m in path.name.lower() for m in IMPL_NAME_MARKERS)
                    or path.name.lower().startswith("readme")
                    or any(
                        seg in path.as_posix().lower()
                        for seg in ("/service", "/api/", "/router", "/handler")
                    )
                ):
                    try:
                        text = path.read_text(encoding="utf-8", errors="ignore")[:600]
                    except OSError:
                        continue
                    block = f"### {rel}\n{text}\n"
                    snippets.append(block)
                    total_snip += len(block)

            members_out.append({
                "slug": repo_dir.name,
                "files": files[:max_files_per_repo],
                "snippets": "\n".join(snippets)[:max_snippet_chars],
            })
        return {"members": members_out}

    async def _generate_application_via_llm(
        self,
        *,
        app_name: str,
        application: Dict[str, Any],
        workspace_path: str,
        manifest: Dict[str, Any],
        service_map_mermaid: str,
        provider: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        from app.core.llm_client import get_llm_client

        llm = get_llm_client(provider, model_id=model_id if provider == "bedrock" else None)
        scan = self._scan_application_workspace(workspace_path)
        app_rules = _load_application_wiki_prompt()
        member_summaries = []
        for m in scan.get("members") or []:
            member_summaries.append(
                f"## {m['slug']}\nFiles (sample): {m.get('files', [])[:40]}\n\n"
                f"{m.get('snippets') or '(no snippets)'}\n"
            )

        prompt = f"""Analyze this multi-repository application workspace and return wiki JSON.

{app_rules}

Application: {app_name}
Description: {application.get('description') or 'n/a'}
Domain: {application.get('domain') or 'n/a'}

MANIFEST.json:
{json.dumps(manifest, indent=2)[:8000]}

Existing service-map Mermaid (refine if needed; do not invent edges):
{service_map_mermaid or '(none)'}

Workspace member sources:
{''.join(member_summaries)[:50000]}

Return compact JSON only (no markdown fences) with keys:
application_name, overview (description, purpose),
components (list of {{name, repository_slug, role, purpose, tech_stack, key_apis}}),
integration (summary, contracts),
dependencies (list of {{from, to, type, evidence}}),
diagrams (high_level_mermaid, service_map_mermaid, data_flow_mermaid, e2e_flow_mermaid),
sections_md (overview, components, integration, dependencies, service_map, data_flow, build_deploy),
tech_stack, build_deploy, data_flow.
Keep strings under 500 characters where possible. Cite paths under repos/<slug>/.
"""
        response = await llm.generate(
            prompt=prompt,
            system_prompt=(
                self.SYSTEM_PROMPT
                + "\nYou are documenting an APPLICATION spanning multiple repositories."
            ),
            max_tokens=8192,
            temperature=0.2,
        )
        try:
            return _parse_llm_json(response)
        except json.JSONDecodeError as first_err:
            logger.warning(
                "Application wiki JSON parse failed, retrying repair: %s", first_err
            )
            repair = await llm.generate(
                prompt=(
                    "Fix this into valid JSON only. Return the corrected JSON object, "
                    "no markdown fences:\n\n" + response[:60000]
                ),
                system_prompt="Return strict valid JSON only.",
                max_tokens=8192,
                temperature=0,
            )
            return _parse_llm_json(repair)

    def _fallback_application_json(
        self,
        app_name: str,
        manifest: Dict[str, Any],
        service_map_mermaid: str,
    ) -> Dict[str, Any]:
        members = manifest.get("members") or []
        components = []
        for m in members:
            components.append({
                "name": m.get("name") or m.get("slug") or "repo",
                "repository_slug": m.get("slug"),
                "role": m.get("role") or "",
                "purpose": f"Member repository {m.get('name') or m.get('slug')}",
            })
        mermaid = service_map_mermaid or "graph TD\n  app[Application]\n"
        if not service_map_mermaid:
            for i, m in enumerate(components):
                safe = f"c{i}"
                mermaid += f"  app --> {safe}[{m['name']}]\n"
        return {
            "application_name": app_name,
            "repo_name": app_name,
            "overview": {
                "description": (
                    f"{app_name} groups {len(components)} repositories. "
                    "Full multi-repo analysis was unavailable; this is a structural fallback."
                ),
            },
            "components": components,
            "integration": {
                "summary": "Integration details pending full application wiki generation.",
            },
            "dependencies": [],
            "diagrams": {
                "high_level_mermaid": mermaid,
                "service_map_mermaid": mermaid,
            },
            "sections_md": {
                "overview": f"# Overview\n\n{app_name} application wiki (fallback).\n",
                "components": "# Components\n\n"
                + "\n".join(
                    f"- **{c['name']}** ({c.get('role') or 'member'})" for c in components
                )
                + "\n",
                "service_map": f"# Service Map\n\n```mermaid\n{mermaid}\n```\n",
            },
        }

    async def _run_shell_agent(
        self,
        org_name: str,
        repo_slug: str,
        clone_path: str,
        output_dir: Path,
        attribute_definitions: List[Dict],
        agent_cli: str = "claude",
    ) -> Optional[Dict[str, Any]]:
        """
        Invoke wiki_agent.sh off the asyncio event loop.

        Returns wiki artifacts on success, or ``{"error": "..."}`` on failure
        (never ``None`` — callers need the reason for UI/logs).
        """
        import asyncio

        script = Path(__file__).resolve().parents[2] / "scripts" / "wiki_agent.sh"
        if not script.is_file():
            msg = f"wiki_agent.sh not found at {script}"
            logger.warning(msg)
            return {"error": msg}

        cli_bin = "copilot" if agent_cli == "copilot" else "claude"
        if not shutil.which(cli_bin):
            msg = (
                f"{cli_bin} CLI not on PATH — install it or switch wiki provider "
                f"(tenant settings → Wiki generation)"
            )
            logger.warning(msg)
            return {"error": msg}

        config_path = output_dir / CONFIG_NAME
        output_dir.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(attribute_definitions, indent=2), encoding="utf-8")

        if agent_cli == "claude" and not settings.ANTHROPIC_API_KEY:
            msg = "ANTHROPIC_API_KEY not set — required for AGENT_CLI=claude"
            logger.warning(msg)
            return {"error": msg}

        if agent_cli == "copilot":
            has_token = bool(
                os.environ.get("COPILOT_GITHUB_TOKEN")
                or os.environ.get("GH_TOKEN")
                or os.environ.get("GITHUB_TOKEN")
                or getattr(settings, "GITHUB_TOKEN", None)
            )
            # Still attempt CLI (may use `copilot login` / gh auth); hint if no env token
            if not has_token:
                logger.info(
                    "No COPILOT_GITHUB_TOKEN/GH_TOKEN/GITHUB_TOKEN in env — "
                    "copilot CLI must already be logged in on this host"
                )

        env = _agent_subprocess_env()
        env["AGENT_CLI"] = agent_cli
        github_token = getattr(settings, "GITHUB_TOKEN", None) or os.environ.get("GITHUB_TOKEN")
        if github_token and not env.get("GITHUB_TOKEN"):
            env["GITHUB_TOKEN"] = github_token
        if os.environ.get("COPILOT_GITHUB_TOKEN"):
            env["COPILOT_GITHUB_TOKEN"] = os.environ["COPILOT_GITHUB_TOKEN"]
        if os.environ.get("GH_TOKEN"):
            env["GH_TOKEN"] = os.environ["GH_TOKEN"]
        backend_root = Path(__file__).resolve().parents[3]
        timeout_s = max(60, int(getattr(settings, "WIKI_CLI_TIMEOUT_SECONDS", 3600) or 3600))

        argv = [
            "bash",
            str(script),
            org_name,
            repo_slug,
            str(output_dir.resolve()),
            str(clone_path),
            str(config_path.resolve()),
        ]

        try:
            logger.info(
                "Invoking wiki_agent.sh (AGENT_CLI=%s, timeout=%ss) for %s/%s → %s",
                agent_cli,
                timeout_s,
                org_name,
                repo_slug,
                output_dir,
            )
            # Critical: do not block uvicorn's event loop for long CLI runs.
            # Use a new session so timeout can kill the whole process group
            # (bash + nested copilot/claude), not only the parent shell.
            import signal

            pid_file = output_dir / "WIKI_CLI_PID"

            def _run_wiki_cli():
                proc = subprocess.Popen(
                    argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=str(backend_root),
                    env=env,
                    start_new_session=True,
                )
                try:
                    pid_file.write_text(str(proc.pid), encoding="utf-8")
                except OSError:
                    pass
                try:
                    stdout, stderr = proc.communicate(timeout=timeout_s)
                    return subprocess.CompletedProcess(
                        argv, proc.returncode, stdout, stderr
                    )
                except subprocess.TimeoutExpired:
                    logger.warning(
                        "Wiki CLI timeout — killing process group pgid=%s (AGENT_CLI=%s)",
                        proc.pid,
                        agent_cli,
                    )
                    self._kill_process_group(proc.pid)
                    try:
                        stdout, stderr = proc.communicate(timeout=15)
                    except Exception:
                        stdout, stderr = "", ""
                    raise subprocess.TimeoutExpired(
                        argv, timeout_s, output=stdout, stderr=stderr
                    )
                finally:
                    try:
                        pid_file.unlink(missing_ok=True)
                    except OSError:
                        pass

            try:
                result = await asyncio.to_thread(_run_wiki_cli)
            except subprocess.TimeoutExpired as te:
                err = (
                    f"wiki_agent.sh timed out after {timeout_s}s (AGENT_CLI={agent_cli}; "
                    f"process group killed. Raise WIKI_CLI_TIMEOUT_SECONDS if needed)"
                )
                logger.warning(err)
                partial = self._load_partial_wiki_artifacts(output_dir)
                if partial:
                    logger.info(
                        "Recovered partial wiki artifacts after CLI timeout in %s",
                        output_dir,
                    )
                    partial["timed_out"] = True
                    partial["error"] = err
                    partial["recovered_partial"] = True
                    return partial
                mark_failed(output_dir, err)
                return {"error": err, "timed_out": True}

            if result.stdout:
                logger.info(
                    "wiki_agent.sh stdout (truncated): %s",
                    redact_secrets(result.stdout[:2000]),
                )
            if result.stderr:
                logger.warning(
                    "wiki_agent.sh stderr (truncated): %s",
                    redact_secrets(result.stderr[:2000]),
                )
            if result.returncode != 0:
                err = (
                    (result.stderr or result.stdout or f"exit code {result.returncode}")
                )[:2000]
                err = redact_secrets(err)
                logger.warning(
                    "wiki_agent.sh exit %s (AGENT_CLI=%s): %s",
                    result.returncode,
                    agent_cli,
                    err,
                )
                partial = self._load_partial_wiki_artifacts(output_dir)
                if partial:
                    logger.info(
                        "Recovered partial wiki artifacts after CLI exit %s in %s",
                        result.returncode,
                        output_dir,
                    )
                    partial["error"] = err
                    partial["recovered_partial"] = True
                    return partial
                mark_failed(output_dir, err)
                return {"error": err}

            json_path = output_dir / WIKI_JSON_NAME
            html_path = output_dir / WIKI_HTML_NAME
            md_path = output_dir / WIKI_MD_NAME
            if not json_path.is_file():
                err = (
                    f"Missing {WIKI_JSON_NAME} after shell agent "
                    f"(AGENT_CLI={agent_cli}, exit 0)"
                )
                logger.warning(err)
                mark_failed(output_dir, err)
                return {"error": err}

            wiki_json = json.loads(json_path.read_text(encoding="utf-8"))
            wiki_html = html_path.read_text(encoding="utf-8") if html_path.is_file() else None
            wiki_md = md_path.read_text(encoding="utf-8") if md_path.is_file() else None
            # CLI sometimes finishes JSON before HTML/MD — complete locally
            if not wiki_html or not wiki_md:
                completed = self._complete_wiki_artifacts_from_json(
                    output_dir, wiki_json, repo_slug=repo_slug
                )
                wiki_html = wiki_html or completed.get("wiki_html")
                wiki_md = wiki_md or completed.get("wiki_md")
            return {"wiki_json": wiki_json, "wiki_html": wiki_html, "wiki_md": wiki_md}
        except (OSError, json.JSONDecodeError) as e:
            err = redact_secrets(str(e))
            logger.warning("Wiki shell agent error: %s", err)
            mark_failed(output_dir, err)
            return {"error": err}

    @staticmethod
    def _kill_process_group(pid: int) -> None:
        """SIGTERM the process group, then SIGKILL if still alive."""
        import signal
        import time

        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                return
        time.sleep(3)
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass

    def _complete_wiki_artifacts_from_json(
        self,
        output_dir: Path,
        wiki_json: Dict[str, Any],
        *,
        repo_slug: str = "repository",
    ) -> Dict[str, Any]:
        """Build HTML/MD from structured JSON when CLI only wrote wiki_result.json."""
        repo_name = wiki_json.get("repo_name") or repo_slug
        overview = wiki_json.get("overview") or {}
        wiki_html = build_wiki_html(
            wiki_json,
            repo_name=repo_name,
            repo_full_name=str(wiki_json.get("repo_url") or repo_name),
            default_branch="main",
            index_run_id=None,
            loc=int(overview.get("loc") or 0),
            file_count=int(overview.get("file_count") or 0),
        )
        wiki_md = _compile_wiki_md(wiki_json, repo_name)
        try:
            (output_dir / WIKI_HTML_NAME).write_text(wiki_html, encoding="utf-8")
            (output_dir / WIKI_MD_NAME).write_text(wiki_md, encoding="utf-8")
        except OSError as e:
            logger.warning("Could not write completed wiki html/md: %s", e)
        return {"wiki_html": wiki_html, "wiki_md": wiki_md}

    def _load_partial_wiki_artifacts(
        self, output_dir: Path
    ) -> Optional[Dict[str, Any]]:
        """If CLI left wiki_result.json, recover usable artifacts."""
        json_path = output_dir / WIKI_JSON_NAME
        if not json_path.is_file():
            return None
        try:
            wiki_json = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(wiki_json, dict) or not wiki_json:
            return None

        html_path = output_dir / WIKI_HTML_NAME
        md_path = output_dir / WIKI_MD_NAME
        wiki_html = html_path.read_text(encoding="utf-8") if html_path.is_file() else None
        wiki_md = md_path.read_text(encoding="utf-8") if md_path.is_file() else None
        if not wiki_html or not wiki_md:
            completed = self._complete_wiki_artifacts_from_json(
                output_dir,
                wiki_json,
                repo_slug=str(wiki_json.get("repo_name") or "repository"),
            )
            wiki_html = wiki_html or completed.get("wiki_html")
            wiki_md = wiki_md or completed.get("wiki_md")
        return {
            "wiki_json": wiki_json,
            "wiki_html": wiki_html,
            "wiki_md": wiki_md,
        }

    def _implementation_snippets(self, chunks: List[FileChunk], max_chars: int = 14000) -> str:
        relevant: List[FileChunk] = []
        for chunk in chunks:
            path_lower = chunk.file_path.lower()
            basename = path_lower.rsplit("/", 1)[-1]
            if any(marker in basename for marker in IMPL_NAME_MARKERS):
                relevant.append(chunk)
            elif any(seg in path_lower for seg in ("/service", "/services/", "/manager", "/handlers/")):
                relevant.append(chunk)

        if not relevant:
            relevant = chunks[:40]

        lines: List[str] = []
        total = 0
        for chunk in relevant[:25]:
            snippet = chunk.content[:800] if chunk.content else ""
            block = f"### {chunk.file_path}\n{snippet}\n"
            if total + len(block) > max_chars:
                break
            lines.append(block)
            total += len(block)
        return "\n".join(lines)

    async def _generate_incremental_via_llm(
        self,
        *,
        repo_name: str,
        repo_full_name: str,
        previous_wiki: Dict[str, Any],
        change_context: str,
        chunks: List[FileChunk],
        attribute_definitions: List[Dict],
        provider: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update prior wiki JSON using git change context (full JSON response)."""
        from app.core.llm_client import get_llm_client

        llm = get_llm_client(provider, model_id=model_id if provider == "bedrock" else None)
        attr_keys = [
            {"key": d.get("key"), "label": d.get("label"), "hint": d.get("extraction_hint")}
            for d in attribute_definitions
        ]
        # Prefer snippets from changed paths when available
        impl_snippets = self._implementation_snippets(chunks, max_chars=8000)
        prior = json.dumps(previous_wiki, indent=2)
        if len(prior) > 50000:
            prior = prior[:50000] + "\n… [prior wiki truncated] …\n"

        prompt = f"""Update the existing repository wiki JSON for {repo_name} ({repo_full_name}).

You are given the PREVIOUS wiki JSON and a git change set since that wiki was generated.
Return a COMPLETE updated wiki JSON (same schema) — not a patch.
- Preserve accurate sections that are unaffected by the changes.
- Revise overview, architecture, business_logic_layer, diagrams, api_surface, etc. when changes warrant it.
- Do not invent files or APIs not supported by the change context / snippets.
- Omit or mark "Not detected" when evidence is missing.

Git changes:
{change_context}

Attribute definitions:
{json.dumps(attr_keys, indent=2)}

Implementation snippets (may include files outside the diff):
{impl_snippets}

PREVIOUS wiki JSON:
{prior}

Return compact JSON only (no markdown fences) with the same keys as a full wiki:
repo_name, overview, functionality, tech_stack, business_logic_layer,
analysis_attributes, diagrams, api_surface, data_flow, database, build_deploy,
run_locally, observability.
"""
        response = await llm.generate(
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT,
            max_tokens=8192,
            temperature=0.2,
        )
        try:
            return _parse_llm_json(response)
        except json.JSONDecodeError as first_err:
            logger.warning(
                "Incremental wiki JSON parse failed, retrying repair: %s", first_err
            )
            repair = await llm.generate(
                prompt=(
                    "Fix this into valid JSON only. Return the corrected JSON object, "
                    "no markdown fences:\n\n" + response[:60000]
                ),
                system_prompt="Return strict valid JSON only.",
                max_tokens=8192,
                temperature=0,
            )
            return _parse_llm_json(repair)

    async def _generate_via_llm(
        self,
        repo_name: str,
        repo_full_name: str,
        chunks: List[FileChunk],
        loc: int,
        attribute_definitions: List[Dict],
        *,
        provider: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        from app.core.llm_client import get_llm_client

        llm = get_llm_client(provider, model_id=model_id if provider == "bedrock" else None)
        lang_counts = Counter(c.language or "unknown" for c in chunks)
        top_dirs = Counter(c.file_path.split("/")[0] for c in chunks if "/" in c.file_path)
        file_paths = sorted({c.file_path for c in chunks})[:80]

        api_files = [
            f for f in file_paths
            if any(x in f.lower() for x in ("router", "routes", "api/", "controller", "handler"))
        ][:20]
        deploy_files = [
            f for f in file_paths
            if any(x in f.lower() for x in ("dockerfile", "docker-compose", "Makefile", "package.json", "requirements.txt"))
        ][:15]

        attr_keys = [
            {"key": d.get("key"), "label": d.get("label"), "hint": d.get("extraction_hint")}
            for d in attribute_definitions
        ]

        impl_snippets = self._implementation_snippets(chunks)
        deep_rules = _load_deep_wiki_prompt()

        prompt = f"""Analyze this indexed repository and return wiki JSON with Deep Wiki parity.

{deep_rules}

Repository: {repo_name} ({repo_full_name})
Lines of code: {loc}
Languages: {dict(lang_counts.most_common(8))}
Top directories: {dict(top_dirs.most_common(10))}
Sample files: {file_paths[:40]}
Likely API files: {api_files}
Build/deploy files: {deploy_files}

Implementation file snippets (analyze these for business_logic_layer):
{impl_snippets}

Attribute definitions to extract:
{json.dumps(attr_keys, indent=2)}

Return compact JSON only (no markdown fences, no sections_md — HTML is built from structured fields).
Keep business_logic_layer.components to the top 8 core components.
Keep each string value under 400 characters. Escape quotes properly in JSON.

Return JSON with keys:
repo_name, overview, functionality, tech_stack,
business_logic_layer (summary, components with name, purpose, source_files, workflows, business_rules),
analysis_attributes,
diagrams (high_level_mermaid, low_level_mermaid, data_model_mermaid, request_flow_mermaid, e2e_flow_mermaid, deployment_flow_mermaid),
api_surface, data_flow, database, build_deploy, run_locally, observability.
"""

        response = await llm.generate(
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT,
            max_tokens=8192,
            temperature=0.2,
        )
        try:
            return _parse_llm_json(response)
        except json.JSONDecodeError as first_err:
            logger.warning(f"Wiki JSON parse failed, retrying with repair prompt: {first_err}")
            repair = await llm.generate(
                prompt=(
                    "Fix this into valid JSON only. Return the corrected JSON object, "
                    "no markdown fences:\n\n" + response[:60000]
                ),
                system_prompt="Return strict valid JSON only.",
                max_tokens=8192,
                temperature=0,
            )
            return _parse_llm_json(repair)

    def _fallback_json(
        self,
        repo_name: str,
        loc: int,
        file_count: int,
        langs: Counter,
        dirs: Counter,
        files: List[str],
        api_files: List[str],
        deploy_files: List[str],
    ) -> Dict[str, Any]:
        lang_lines = ", ".join(f"{k} ({v})" for k, v in langs.most_common(6))
        dir_mermaid = "graph TD\n  root[Repository Root]\n"
        for d, _ in dirs.most_common(8):
            safe = d.replace("-", "_").replace(".", "_")
            dir_mermaid += f"  root --> {safe}[{d}]\n"

        impl_files = [
            f for f in files
            if any(m in f.lower() for m in IMPL_NAME_MARKERS)
        ][:15]

        return {
            "repo_name": repo_name,
            "overview": {
                "description": f"Indexed repository with {file_count} files and ~{loc:,} lines of code.",
                "loc": loc,
                "file_count": file_count,
            },
            "functionality": {
                "summary": "Shallow index summary — re-index with claude CLI for deep wiki.",
                "bullets": [f"Primary languages: {lang_lines or 'unknown'}"],
            },
            "tech_stack": [
                {
                    "layer": "Languages",
                    "technologies": [k for k, _ in langs.most_common(6)],
                    "evidence_file": files[0] if files else "",
                },
            ],
            "business_logic_layer": {
                "summary": "Deep business logic requires Wiki Agent shell (claude CLI) or LLM API.",
                "components": [],
            },
            "analysis_attributes": [],
            "diagrams": {
                "high_level_mermaid": dir_mermaid,
                "low_level_mermaid": dir_mermaid,
                "data_model_mermaid": "erDiagram\n  ENTITY ||--o{ RECORD : stores",
                "request_flow_mermaid": "flowchart LR\n  A[Client] --> B[API] --> C[Service]",
                "e2e_flow_mermaid": "sequenceDiagram\n  participant C as Client\n  participant A as App\n  C->>A: Request\n  A-->>C: Response",
                "deployment_flow_mermaid": "flowchart TD\n  A[Build] --> B[Deploy]",
            },
            "api_surface": [{"file": f, "path": f} for f in api_files],
            "build_deploy": {
                "summary": "Build artifacts detected in the repository index.",
                "artifacts": deploy_files,
            },
            "run_locally": {
                "intro": "See README and package manifests for setup.",
                "prerequisites": list(langs.keys())[:3],
                "commands": "# Check README.md for run instructions",
            },
            "observability": {"summary": "Not detected in index."},
            "data_model": {"summary": "Review ORM models and schema files."},
            "sections_md": {
                "overview": f"# {repo_name}\n\n{loc:,} LOC across {file_count} files.\n",
                "architecture": f"# Architecture\n\n```mermaid\n{dir_mermaid}\n```\n",
                "business_logic": (
                    "# Business Logic Layer\n\n"
                    "Shallow fallback — implementation files detected:\n"
                    + "\n".join(f"- `{f}`" for f in impl_files)
                    + "\n\nRe-index with `claude` CLI on PATH for deep analysis.\n"
                ),
                "api_surface": "\n".join(f"- `{f}`" for f in api_files) or "No API files detected.",
                "build_deploy": "\n".join(f"- `{f}`" for f in deploy_files) or "No build files detected.",
            },
        }

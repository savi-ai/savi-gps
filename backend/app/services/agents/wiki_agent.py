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


def _compile_wiki_md(wiki_json: Dict[str, Any], repo_name: str) -> str:
    sections = wiki_json.get("sections_md") or {}
    order = (
        "overview", "architecture", "business_logic", "api_surface",
        "data_flow", "e2e_flow", "database", "build_deploy",
    )
    parts: List[str] = []
    for key in order:
        content = sections.get(key)
        if content and content.strip():
            parts.append(content.strip())

    if not parts:
        bl = wiki_json.get("business_logic_layer") or {}
        overview = wiki_json.get("overview", {})
        parts.append(f"# {repo_name}\n\n{overview.get('description', '')}")
        if bl.get("summary"):
            parts.append(f"# Business Logic Layer\n\n{bl['summary']}")
        for comp in bl.get("components") or []:
            parts.append(f"## {comp.get('name', 'Component')}\n\n{comp.get('purpose', '')}")

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
        llm_provider = gen_settings.get("llm_provider") or settings.LLM_PROVIDER
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
        allow_api = generation_mode in ("api", "auto")
        allow_fallback = generation_mode != "cli"  # cli-only: no silent heuristic unless API also failed path

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
            shell_result = self._run_shell_agent(
                org_name=org_name,
                repo_slug=repo_name,
                clone_path=clone_path,
                output_dir=output_dir,
                attribute_definitions=attribute_definitions,
            )
            if shell_result and shell_result.get("wiki_json"):
                shell_succeeded = True
                generation_source = "wiki_agent_shell"
                wiki_json = shell_result["wiki_json"]
                wiki_html = shell_result.get("wiki_html")
                wiki_md = shell_result.get("wiki_md")
            elif generation_mode == "cli":
                err = "Wiki CLI generation failed and WIKI_GENERATION_MODE=cli (no API fallback)"
                logger.error(redact_secrets(err))
                mark_failed(output_dir, err)
                raise RuntimeError(err)

        if not wiki_json and allow_api:
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
                "llm_provider": llm_provider,
                "llm_model": llm_model,
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
        state["shell_invoked"] = shell_invoked
        state["shell_succeeded"] = shell_succeeded
        state["analysis_paths"] = paths
        state["git_head"] = git_head
        state["wiki_refresh_mode"] = refresh_mode or "full"
        state["wiki_refresh_reason"] = refresh_reason
        return state

    def _run_shell_agent(
        self,
        org_name: str,
        repo_slug: str,
        clone_path: str,
        output_dir: Path,
        attribute_definitions: List[Dict],
    ) -> Optional[Dict[str, Any]]:
        script = Path(__file__).resolve().parents[2] / "scripts" / "wiki_agent.sh"
        if not script.is_file():
            logger.warning(f"wiki_agent.sh not found at {script}")
            return None

        if not shutil.which("claude"):
            logger.info("claude CLI not on PATH — skipping wiki_agent.sh")
            return None

        config_path = output_dir / CONFIG_NAME
        output_dir.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(attribute_definitions, indent=2), encoding="utf-8")

        if not settings.ANTHROPIC_API_KEY:
            logger.warning("ANTHROPIC_API_KEY not set in settings — wiki_agent.sh will fail")
            return None

        env = _agent_subprocess_env()
        backend_root = Path(__file__).resolve().parents[3]

        try:
            logger.info(
                f"Invoking wiki_agent.sh for {org_name}/{repo_slug} → {output_dir}"
            )
            result = subprocess.run(
                [
                    "bash",
                    str(script),
                    org_name,
                    repo_slug,
                    str(output_dir.resolve()),
                    str(clone_path),
                    str(config_path.resolve()),
                ],
                capture_output=True,
                text=True,
                timeout=900,
                cwd=str(backend_root),
                env=env,
            )
            if result.stdout:
                logger.debug(f"wiki_agent.sh stdout: {result.stdout[:500]}")
            if result.returncode != 0:
                err = result.stderr[:1200] if result.stderr else f"exit code {result.returncode}"
                logger.warning(f"wiki_agent.sh exit {result.returncode}: {err}")
                mark_failed(output_dir, err)
                return None

            json_path = output_dir / WIKI_JSON_NAME
            html_path = output_dir / WIKI_HTML_NAME
            md_path = output_dir / WIKI_MD_NAME
            if not json_path.is_file():
                mark_failed(output_dir, f"Missing {WIKI_JSON_NAME} after shell agent")
                return None

            wiki_json = json.loads(json_path.read_text(encoding="utf-8"))
            wiki_html = html_path.read_text(encoding="utf-8") if html_path.is_file() else None
            wiki_md = md_path.read_text(encoding="utf-8") if md_path.is_file() else None
            return {"wiki_json": wiki_json, "wiki_html": wiki_html, "wiki_md": wiki_md}
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as e:
            logger.warning("Wiki shell agent error: %s", redact_secrets(str(e)))
            mark_failed(output_dir, redact_secrets(str(e)))
            return None

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

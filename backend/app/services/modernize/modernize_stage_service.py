"""Modernize plan stage runners — write into execution workspace (W8.4)."""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.database import ModernizationPlan, Repository
from app.core.logger import logger
from app.services.git_service import GitService
from app.services.intelligence.analysis_storage import sanitize_path_segment
from app.services.intelligence.github_client import GitHubClient, GitHubApiError
from app.services.intelligence.repo_clone_service import RepoCloneService, normalize_github_url
from app.services.llm_routing import get_other_llm_client, resolve_code_generation
from app.services.modernize.execution_service import resolve_execution_root, _resolve_clone_token
from app.services.modernize.execution_storage import MODERNIZE_STAGES, read_manifest, reset_stages_for_rerun, write_manifest
from app.services.savi_coding_agent_adapter import CLI_MODES, SaviCodingAgentAdapter
from app.services.savi_sandbox import SaviSandbox


def _parse_owner_repo(url: str) -> Tuple[str, str]:
    cleaned = normalize_github_url(url or "")
    if "github.com/" not in cleaned:
        raise ValueError("Not a GitHub repository URL")
    path = cleaned.split("github.com/", 1)[1].strip("/")
    parts = path.split("/")
    if len(parts) < 2:
        raise ValueError("GitHub URL must look like https://github.com/owner/repo")
    return parts[0], parts[1]


def _extract_json(text: str) -> Any:
    content = text if isinstance(text, str) else str(text)
    # Prefer fenced JSON
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if fence:
        content = fence.group(1).strip()
    start_obj = content.find("{")
    start_arr = content.find("[")
    if start_obj < 0 and start_arr < 0:
        raise ValueError("No JSON in model response")
    if start_arr >= 0 and (start_obj < 0 or start_arr < start_obj):
        end = content.rfind("]") + 1
        return json.loads(content[start_arr:end])
    end = content.rfind("}") + 1
    return json.loads(content[start_obj:end])


def _slugify_component(value: str) -> str:
    cleaned = sanitize_path_segment(value or "component").lower().replace(".", "-")
    cleaned = re.sub(r"_+", "-", cleaned).strip("-")
    return cleaned[:80] or "component"


def _run_coro_sync(coro, *, timeout: float = 600):
    """Run async work from sync stage handlers (safe if an event loop is already running)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=timeout)


class ModernizeStageService:
    """Copilot-gated modernize stages writing under applications/.../executions/."""

    def __init__(self, db: Session):
        self.db = db
        self._clone = RepoCloneService()
        self._git = GitService()

    def run_stage(self, tenant_id: str, plan_id: str, stage: str) -> Dict[str, Any]:
        self.prepare_stage(tenant_id, plan_id, stage)
        return self.execute_stage(tenant_id, plan_id, stage)

    def prepare_stage(self, tenant_id: str, plan_id: str, stage: str) -> Dict[str, Any]:
        """Validate priors and mark stage running (API returns before execute)."""
        if stage not in MODERNIZE_STAGES:
            raise ValueError(f"Unknown modernize stage: {stage}")

        plan, root, manifest = self._load(plan_id, tenant_id)
        stages = manifest.get("stages") or list(MODERNIZE_STAGES)
        if stage not in stages:
            raise ValueError(f"Stage {stage} not in plan manifest")

        idx = stages.index(stage)
        stage_state = manifest.setdefault("stage_state", {})
        if any(s == "running" for s in stage_state.values()):
            raise ValueError("Wait for the running stage to finish before starting another")

        for prior in stages[:idx]:
            if stage_state.get(prior) != "completed":
                raise ValueError(f"Complete stage '{prior}' before running '{stage}'")

        current = stage_state.get(stage) or "pending"
        if current == "completed":
            reset_stages_for_rerun(manifest, stages, idx)
        elif current == "failed":
            manifest.setdefault("stage_errors", {}).pop(stage, None)
        elif current == "running":
            raise ValueError(f"Stage '{stage}' is already running")

        stage_state[stage] = "running"
        manifest.setdefault("stage_errors", {}).pop(stage, None)
        write_manifest(root, manifest)
        return {"stage": stage, "status": "running", "plan_id": plan_id, "rerun": current == "completed"}

    def execute_stage(self, tenant_id: str, plan_id: str, stage: str) -> Dict[str, Any]:
        """Run stage work after prepare_stage marked it running."""
        if stage not in MODERNIZE_STAGES:
            raise ValueError(f"Unknown modernize stage: {stage}")

        plan, root, manifest = self._load(plan_id, tenant_id)
        stage_state = manifest.setdefault("stage_state", {})

        try:
            handlers = {
                "requirements": self._run_requirements,
                "tasks": self._run_tasks,
                "architecture": self._run_architecture,
                "code": self._run_code,
                "test": self._run_test,
                "push": self._run_push,
            }
            result = handlers[stage](plan, root, manifest)
            stage_state[stage] = "completed"
            manifest.setdefault("stage_results", {})[stage] = result
            write_manifest(root, manifest)
            return {"stage": stage, "status": "completed", "result": result, "manifest": manifest}
        except Exception as exc:
            logger.exception("Modernize stage %s failed for plan %s", stage, plan_id)
            stage_state[stage] = "failed"
            manifest.setdefault("stage_errors", {})[stage] = str(exc)[:800]
            write_manifest(root, manifest)
            raise ValueError(str(exc)) from exc

    def register_target(
        self,
        tenant_id: str,
        plan_id: str,
        *,
        slug: str,
        github_url: str,
        branch: str = "main",
        clone: bool = True,
    ) -> Dict[str, Any]:
        """Register / update a target repo URL after architecture (or before code)."""
        plan, root, manifest = self._load(plan_id, tenant_id)
        slug = _slugify_component(slug)
        url = normalize_github_url(github_url)
        if not url.startswith("https://github.com/") and not url.startswith("git@github.com:"):
            raise ValueError("github_url must be a GitHub repository URL")

        targets: List[Dict[str, Any]] = list(manifest.get("targets") or [])
        existing = next((t for t in targets if t.get("slug") == slug), None)
        target_dir = root / "targets" / slug
        target_dir.mkdir(parents=True, exist_ok=True)

        entry = existing or {
            "slug": slug,
            "local_path": str(target_dir),
            "source": "register",
        }
        entry["github_url"] = url
        entry["branch"] = (branch or "main").strip() or "main"
        entry["local_path"] = str(target_dir)

        if clone:
            token = self._token_for_plan(plan)
            try:
                self._clone.shallow_clone(
                    url,
                    entry["branch"],
                    token=token,
                    target_dir=str(target_dir),
                )
                entry["clone_status"] = "ready"
                entry["clone_error"] = None
            except Exception as exc:
                entry["clone_status"] = "failed"
                entry["clone_error"] = str(exc)[:500]
                if not existing:
                    targets.append(entry)
                else:
                    for i, t in enumerate(targets):
                        if t.get("slug") == slug:
                            targets[i] = entry
                manifest["targets"] = targets
                write_manifest(root, manifest)
                raise ValueError(f"Clone failed: {exc}") from exc
        else:
            entry["clone_status"] = entry.get("clone_status") or "pending"

        if not existing:
            targets.append(entry)
        else:
            for i, t in enumerate(targets):
                if t.get("slug") == slug:
                    targets[i] = entry
        manifest["targets"] = targets
        write_manifest(root, manifest)
        return {"target": entry, "targets": targets}

    def _load(
        self, plan_id: str, tenant_id: str
    ) -> Tuple[ModernizationPlan, Path, Dict[str, Any]]:
        plan = (
            self.db.query(ModernizationPlan)
            .filter(ModernizationPlan.id == plan_id, ModernizationPlan.tenant_id == tenant_id)
            .first()
        )
        if not plan:
            raise ValueError("Plan not found")
        plan_type = getattr(plan, "plan_type", None) or "modernize"
        if plan_type != "modernize":
            raise ValueError("Modernize stage runner requires plan_type=modernize")

        root_path = resolve_execution_root(plan)
        if not root_path:
            raise ValueError(
                "Execution workspace not initialized — spawn execution first "
                "(requires source_application_id)"
            )
        root = Path(root_path)
        manifest = read_manifest(root)
        if not manifest:
            raise ValueError("Execution manifest missing — spawn execution first")
        return plan, root, manifest

    def _token_for_plan(self, plan: ModernizationPlan) -> Optional[str]:
        repo_id = plan.repository_id or (plan.assessment_json or {}).get("repository_id")
        if repo_id:
            repo = (
                self.db.query(Repository)
                .filter(Repository.id == repo_id, Repository.tenant_id == plan.tenant_id)
                .first()
            )
            if repo:
                return _resolve_clone_token(self.db, repo) or os.getenv("GITHUB_TOKEN")
        return os.getenv("GITHUB_TOKEN")

    def _context_blob(self, plan: ModernizationPlan, root: Path) -> str:
        parts: List[str] = [f"# Plan: {plan.title}", ""]
        if plan.plan_md:
            parts.append(plan.plan_md[:6000])
            parts.append("")
        assessment_path = root / "context" / "assessment.json"
        if assessment_path.is_file():
            parts.append("## Assessment")
            parts.append(assessment_path.read_text(encoding="utf-8")[:8000])
        elif plan.assessment_json:
            parts.append("## Assessment")
            parts.append(json.dumps(plan.assessment_json, indent=2)[:8000])
        return "\n".join(parts)

    def _chat(self, tenant_id: str, system: str, user: str) -> str:
        client = get_other_llm_client(self.db, tenant_id)
        return _run_coro_sync(
            client.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
            )
        )

    def _run_requirements(
        self, plan: ModernizationPlan, root: Path, manifest: Dict[str, Any]
    ) -> Dict[str, Any]:
        stages_dir = root / "stages"
        stages_dir.mkdir(parents=True, exist_ok=True)
        context = self._context_blob(plan, root)
        system = (
            "You are a modernization requirements analyst. Produce clear markdown requirements "
            "for migrating a legacy application into a new multi-service architecture. "
            "Include goals, non-goals, acceptance criteria, and constraints."
        )
        user = f"{context}\n\nWrite `requirements.md` content for this modernization plan."
        md = self._chat(plan.tenant_id, system, user)
        path = stages_dir / "requirements.md"
        path.write_text(md.strip() + "\n", encoding="utf-8")
        (root / "agent").mkdir(parents=True, exist_ok=True)
        (root / "agent" / "requirements_summary.md").write_text(
            md[:1500], encoding="utf-8"
        )
        return {"path": str(path), "chars": len(md)}

    def _run_tasks(
        self, plan: ModernizationPlan, root: Path, manifest: Dict[str, Any]
    ) -> Dict[str, Any]:
        stages_dir = root / "stages"
        req_path = stages_dir / "requirements.md"
        if not req_path.is_file():
            raise ValueError("requirements.md missing — run requirements stage first")
        requirements = req_path.read_text(encoding="utf-8")
        system = (
            "You break modernization requirements into implementable tasks. "
            "Return ONLY JSON: {\"tasks\": [{\"id\": \"T1\", \"title\": \"...\", "
            "\"description\": \"...\", \"component_hint\": \"api-service|web-ui|infra|...\"}]}"
        )
        user = f"# Requirements\n\n{requirements[:10000]}\n\nProduce tasks JSON."
        raw = self._chat(plan.tenant_id, system, user)
        try:
            parsed = _extract_json(raw)
        except Exception:
            parsed = {"tasks": [], "raw": raw[:1000]}
        if isinstance(parsed, list):
            parsed = {"tasks": parsed}
        path = stages_dir / "tasks.json"
        path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
        return {"path": str(path), "task_count": len(parsed.get("tasks") or [])}

    def _run_architecture(
        self, plan: ModernizationPlan, root: Path, manifest: Dict[str, Any]
    ) -> Dict[str, Any]:
        stages_dir = root / "stages"
        req = (stages_dir / "requirements.md").read_text(encoding="utf-8") if (stages_dir / "requirements.md").is_file() else ""
        tasks = (stages_dir / "tasks.json").read_text(encoding="utf-8") if (stages_dir / "tasks.json").is_file() else "{}"
        system = (
            "You design a target architecture for modernizing a legacy application into "
            "**new repositories** (one per component). Return ONLY JSON:\n"
            "{\n"
            '  "summary": "...",\n'
            '  "components": [\n'
            '    {"slug": "api-service", "name": "API", "role": "backend", '
            '"description": "...", "github_url": null}\n'
            "  ]\n"
            "}\n"
            "slug must be filesystem-safe kebab-case. github_url may be null "
            "(user registers remotes later). Prefer 2–5 components."
        )
        user = (
            f"# Requirements\n{req[:6000]}\n\n# Tasks\n{tasks[:4000]}\n\n"
            f"{self._context_blob(plan, root)[:4000]}\n\nProduce architecture JSON."
        )
        raw = self._chat(plan.tenant_id, system, user)
        try:
            arch = _extract_json(raw)
        except Exception as exc:
            raise ValueError(f"Architecture agent returned invalid JSON: {exc}") from exc
        if not isinstance(arch, dict):
            raise ValueError("Architecture must be a JSON object")
        components = arch.get("components") or []
        if not isinstance(components, list) or not components:
            raise ValueError("Architecture must declare at least one component")

        # Merge with any spawn-time / registered targets
        existing_by_slug = {
            t.get("slug"): t for t in (manifest.get("targets") or []) if t.get("slug")
        }
        targets: List[Dict[str, Any]] = []
        for comp in components:
            if not isinstance(comp, dict):
                continue
            slug = _slugify_component(comp.get("slug") or comp.get("name") or "component")
            comp["slug"] = slug
            target_dir = root / "targets" / slug
            target_dir.mkdir(parents=True, exist_ok=True)
            prev = existing_by_slug.get(slug) or {}
            github_url = comp.get("github_url") or prev.get("github_url")
            branch = prev.get("branch") or "main"
            entry: Dict[str, Any] = {
                "slug": slug,
                "name": comp.get("name") or slug,
                "role": comp.get("role"),
                "description": comp.get("description"),
                "github_url": github_url,
                "branch": branch,
                "local_path": str(target_dir),
                "source": "architecture",
                "clone_status": prev.get("clone_status") or "pending",
            }
            if github_url and entry["clone_status"] != "ready":
                token = self._token_for_plan(plan)
                try:
                    self._clone.shallow_clone(
                        normalize_github_url(github_url),
                        branch,
                        token=token,
                        target_dir=str(target_dir),
                    )
                    entry["clone_status"] = "ready"
                except Exception as exc:
                    entry["clone_status"] = "failed"
                    entry["clone_error"] = str(exc)[:500]
                    logger.warning("Target clone failed for %s: %s", slug, exc)
            targets.append(entry)

        # Keep spawn-only targets not redefined by architecture
        arch_slugs = {t["slug"] for t in targets}
        for slug, prev in existing_by_slug.items():
            if slug not in arch_slugs:
                targets.append(prev)

        arch["components"] = [
            {
                "slug": t["slug"],
                "name": t.get("name"),
                "role": t.get("role"),
                "description": t.get("description"),
                "github_url": t.get("github_url"),
            }
            for t in targets
            if t.get("source") == "architecture" or t["slug"] in arch_slugs
        ]
        arch_path = stages_dir / "architecture.json"
        arch_path.write_text(json.dumps(arch, indent=2), encoding="utf-8")
        manifest["targets"] = targets
        write_manifest(root, manifest)

        (root / "agent").mkdir(parents=True, exist_ok=True)
        (root / "agent" / "architecture_summary.md").write_text(
            arch.get("summary") or f"{len(targets)} components",
            encoding="utf-8",
        )
        return {
            "path": str(arch_path),
            "component_count": len(targets),
            "targets": targets,
        }

    def _run_code(
        self, plan: ModernizationPlan, root: Path, manifest: Dict[str, Any]
    ) -> Dict[str, Any]:
        targets = manifest.get("targets") or []
        if not targets:
            raise ValueError(
                "No architecture targets — run architecture stage (and register github_url if needed)"
            )

        stages_dir = root / "stages"
        requirements = ""
        if (stages_dir / "requirements.md").is_file():
            requirements = (stages_dir / "requirements.md").read_text(encoding="utf-8")
        tasks = {}
        if (stages_dir / "tasks.json").is_file():
            try:
                tasks = json.loads((stages_dir / "tasks.json").read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                tasks = {}
        arch = {}
        if (stages_dir / "architecture.json").is_file():
            try:
                arch = json.loads((stages_dir / "architecture.json").read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                arch = {}

        per_target: List[Dict[str, Any]] = []
        for target in targets:
            slug = target.get("slug") or "component"
            target_path = Path(target.get("local_path") or (root / "targets" / slug))
            target_path.mkdir(parents=True, exist_ok=True)

            # If not a git checkout yet, init empty repo so coding adapters can work
            if not (target_path / ".git").exists():
                subprocess.run(
                    ["git", "init"],
                    cwd=str(target_path),
                    capture_output=True,
                    text=True,
                    check=False,
                )

            findings = {
                "modernization": True,
                "component": target,
                "requirements_excerpt": requirements[:6000],
                "tasks": tasks,
                "architecture_summary": arch.get("summary"),
            }
            result = _run_coro_sync(
                self._code_target(
                    plan=plan,
                    root=root,
                    target_path=target_path,
                    findings=findings,
                    slug=slug,
                )
            )
            per_target.append({"slug": slug, **result})

        return {"targets": per_target}

    async def _code_target(
        self,
        *,
        plan: ModernizationPlan,
        root: Path,
        target_path: Path,
        findings: Dict[str, Any],
        slug: str,
    ) -> Dict[str, Any]:
        code = resolve_code_generation(self.db, plan.tenant_id)
        mode = (code.get("execution_mode") or "llm").lower()
        agent_dir = root / "agent" / slug
        agent_dir.mkdir(parents=True, exist_ok=True)

        if mode in CLI_MODES or mode == "heuristic":
            adapter = SaviCodingAgentAdapter(mode=mode)
            item = SimpleNamespace(
                id=f"{plan.id}-{slug}",
                title=f"{plan.title} — {slug}",
                description=f"Implement modernization component `{slug}` into this new repository.",
            )
            brief = (
                f"# Modernize component: {slug}\n\n"
                f"{json.dumps(findings, indent=2)[:12000]}\n"
            )
            plan_md, tokens_plan = await adapter.plan(item, {"brief_markdown": brief})
            (agent_dir / "plan.md").write_text(plan_md, encoding="utf-8")
            sandbox = SaviSandbox(root=target_path)
            files, tokens_code = await adapter.propose_files(
                item, {"brief_markdown": brief}, plan_md, sandbox
            )
            return {
                "execution_mode": mode,
                "files": [f.get("path") for f in files if f.get("path")],
                "tokens_estimate": tokens_plan + tokens_code,
            }

        # API path — Code Generation LLM → patches into this component checkout
        from app.services.modernize.fix_remediation_agent import (
            FixRemediationAgent,
            apply_patches,
            _list_repo_tree,
        )
        from app.services.llm_routing import get_build_code_llm_client

        agent = FixRemediationAgent(self.db, plan.tenant_id)
        agent.llm_client = get_build_code_llm_client(self.db, plan.tenant_id)
        agent_result = await agent.process(
            {
                "findings": findings,
                "repo_tree": _list_repo_tree(target_path),
                "plan_title": f"{plan.title} — {slug}",
            }
        )
        written = apply_patches(target_path, agent_result.get("files") or [])
        log_path = agent_dir / "code_result.json"
        log_path.write_text(
            json.dumps({**agent_result, "files_written": written, "execution_mode": mode}, indent=2),
            encoding="utf-8",
        )
        return {
            "execution_mode": mode,
            "files_written": written,
            "summary": agent_result.get("summary"),
            "llm": "build_code_generation",
            "agent_log": str(log_path),
        }

    def _run_test(
        self, plan: ModernizationPlan, root: Path, manifest: Dict[str, Any]
    ) -> Dict[str, Any]:
        targets = manifest.get("targets") or []
        if not targets:
            raise ValueError("No targets to test")

        results: List[Dict[str, Any]] = []
        soft_fail = False
        for target in targets:
            slug = target.get("slug") or "component"
            target_path = Path(target.get("local_path") or (root / "targets" / slug))
            test_dir = root / "agent" / slug
            test_dir.mkdir(parents=True, exist_ok=True)
            output_path = test_dir / "test_output.txt"

            commands: List[List[str]] = []
            if (target_path / "pom.xml").is_file():
                commands.append(["mvn", "-q", "test"])
            if (target_path / "package.json").is_file():
                commands.append(["npm", "test", "--if-present"])
            if (target_path / "pyproject.toml").is_file() or (target_path / "setup.py").is_file():
                commands.append(["pytest", "-q"])
            if (target_path / "go.mod").is_file():
                commands.append(["go", "test", "./..."])

            lines = [f"Target: {slug}", f"Path: {target_path}", ""]
            exit_code = 0
            if not commands:
                lines.append("No test runner detected — soft pass (Alpha).")
                output_path.write_text("\n".join(lines), encoding="utf-8")
                results.append({"slug": slug, "skipped": True, "output": str(output_path)})
                continue

            for cmd in commands:
                lines.append(f"$ {' '.join(cmd)}")
                try:
                    proc = subprocess.run(
                        cmd,
                        cwd=str(target_path),
                        capture_output=True,
                        text=True,
                        timeout=600,
                        check=False,
                    )
                    lines.append(proc.stdout or "")
                    if proc.stderr:
                        lines.append(proc.stderr)
                    lines.append(f"exit code: {proc.returncode}")
                    if proc.returncode != 0:
                        exit_code = proc.returncode
                        soft_fail = True
                except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                    lines.append(str(exc))
                    exit_code = 1
                    soft_fail = True
                lines.append("")

            output_path.write_text("\n".join(lines), encoding="utf-8")
            results.append(
                {
                    "slug": slug,
                    "exit_code": exit_code,
                    "output": str(output_path),
                }
            )

        # Alpha: warn but complete so Copilot can continue to push after review
        return {"targets": results, "soft_fail": soft_fail}

    def _run_push(
        self, plan: ModernizationPlan, root: Path, manifest: Dict[str, Any]
    ) -> Dict[str, Any]:
        targets = manifest.get("targets") or []
        if not targets:
            raise ValueError("No targets to push")

        token = self._token_for_plan(plan)
        push_meta: List[Dict[str, Any]] = []
        for target in targets:
            slug = target.get("slug") or "component"
            github_url = target.get("github_url")
            if not github_url:
                push_meta.append(
                    {
                        "slug": slug,
                        "skipped": True,
                        "reason": "no_github_url — register target remote first",
                    }
                )
                continue

            target_path = Path(target.get("local_path") or (root / "targets" / slug))
            if not target_path.is_dir():
                push_meta.append({"slug": slug, "skipped": True, "reason": "missing_local_path"})
                continue

            branch = f"savi/modernize-{plan.id[:8]}-{slug[:24]}"
            base = target.get("branch") or "main"
            result = self._git.push_workspace_branch(
                str(target_path),
                branch_name=branch,
                commit_message=(
                    f"Savi modernization: {plan.title} — {slug}\n\n"
                    "Generated in execution workspace (W8.4)."
                ),
                remote_url=github_url,
                token=token,
                base_branch=base,
            )
            if not result.get("success"):
                raise ValueError(
                    f"Push failed for {slug}: {result.get('error') or 'unknown error'}"
                )

            pr_info: Dict[str, Any] = {}
            if token:
                try:
                    owner, repo_name = _parse_owner_repo(github_url)
                    client = GitHubClient(token)
                    pr = _run_coro_sync(
                        client.create_pull_request(
                            owner,
                            repo_name,
                            title=f"Savi modernize: {plan.title} ({slug})",
                            body=(
                                f"Automated modernization for component **{slug}**.\n\n"
                                f"Plan: `{plan.title}`\n"
                            ),
                            head=branch,
                            base=base,
                        )
                    )
                    pr_info = {
                        "url": pr.get("html_url"),
                        "number": pr.get("number"),
                    }
                except (GitHubApiError, ValueError) as exc:
                    logger.warning("PR create failed for %s: %s", slug, exc)
                    pr_info = {"error": str(exc)[:300]}

            entry = {
                "slug": slug,
                "branch": branch,
                "commit_sha": result.get("commit_sha"),
                "github_url": github_url,
                "pr": pr_info,
            }
            push_meta.append(entry)

        manifest["push"] = {"targets": push_meta}
        push_dir = root / "push"
        push_dir.mkdir(parents=True, exist_ok=True)
        (push_dir / "result.json").write_text(json.dumps(push_meta, indent=2), encoding="utf-8")
        write_manifest(root, manifest)
        return {"targets": push_meta}

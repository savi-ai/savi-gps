"""Run fix-plan execution stages in workspace (W8.2)."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.database import ModernizationPlan, Repository
from app.core.logger import logger
from app.services.git_service import GitService
from app.services.intelligence.github_client import GitHubClient, GitHubApiError
from app.services.intelligence.repo_clone_service import normalize_github_url
from app.services.modernize.execution_service import resolve_execution_root
from app.services.modernize.execution_storage import FIX_STAGES, read_manifest, reset_stages_for_rerun, write_manifest
from app.services.modernize.fix_code_runner import FixCodeRunner
from app.services.modernize.fix_remediation_agent import build_findings_payload


def _parse_owner_repo(url: str) -> Tuple[str, str]:
    cleaned = normalize_github_url(url or "")
    if "github.com/" not in cleaned:
        raise ValueError("Not a GitHub repository URL")
    path = cleaned.split("github.com/", 1)[1].strip("/")
    parts = path.split("/")
    if len(parts) < 2:
        raise ValueError("GitHub URL must look like https://github.com/owner/repo")
    return parts[0], parts[1]


def _resolve_token(db: Session, repo: Repository) -> Optional[str]:
    try:
        from app.services.intelligence.indexer_service import IndexerService

        return IndexerService(db)._resolve_clone_token(repo)
    except Exception:
        return os.getenv("GITHUB_TOKEN")


class FixStageService:
    def __init__(self, db: Session):
        self.db = db
        self._git = GitService()

    async def run_stage(self, tenant_id: str, plan_id: str, stage: str) -> Dict[str, Any]:
        self.prepare_stage(tenant_id, plan_id, stage)
        return await self.execute_stage(tenant_id, plan_id, stage)

    def prepare_stage(self, tenant_id: str, plan_id: str, stage: str) -> Dict[str, Any]:
        """Validate priors and mark stage running (API returns before execute)."""
        if stage not in FIX_STAGES:
            raise ValueError(f"Unknown fix stage: {stage}")

        plan, repo, root, manifest = self._load(plan_id, tenant_id)
        stages = manifest.get("stages") or list(FIX_STAGES)
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

    async def execute_stage(self, tenant_id: str, plan_id: str, stage: str) -> Dict[str, Any]:
        """Run stage work after prepare_stage marked it running."""
        if stage not in FIX_STAGES:
            raise ValueError(f"Unknown fix stage: {stage}")

        plan, repo, root, manifest = self._load(plan_id, tenant_id)
        stage_state = manifest.setdefault("stage_state", {})

        try:
            if stage in ("fix", "code"):
                result = await self._run_remediation(plan, repo, root, manifest, stage)
            elif stage == "test":
                result = await asyncio.to_thread(self._run_tests, root, manifest)
            elif stage == "push":
                result = await asyncio.to_thread(self._run_push, plan, repo, root, manifest)
            elif stage == "pr":
                result = await self._run_pr(plan, repo, root, manifest)
            else:
                raise ValueError(f"Unsupported stage: {stage}")

            stage_state[stage] = "completed"
            manifest.setdefault("stage_results", {})[stage] = result
            write_manifest(root, manifest)
            return {"stage": stage, "status": "completed", "result": result, "manifest": manifest}
        except Exception as exc:
            logger.exception("Fix stage %s failed for plan %s", stage, plan_id)
            stage_state[stage] = "failed"
            manifest.setdefault("stage_errors", {})[stage] = str(exc)[:800]
            write_manifest(root, manifest)
            raise ValueError(str(exc)) from exc

    def retry_source_clone(self, tenant_id: str, plan_id: str) -> Dict[str, Any]:
        plan, repo, root, manifest = self._load(plan_id, tenant_id)
        if manifest.get("plan_type") != "fix":
            raise ValueError("Retry clone is only for fix plans")

        from app.services.modernize.execution_service import _resolve_clone_token
        from app.services.intelligence.repo_clone_service import RepoCloneService

        if not repo.url:
            raise ValueError("Repository has no clone URL")

        clone = RepoCloneService()
        token = _resolve_clone_token(self.db, repo)
        branch = repo.default_branch or manifest.get("source", {}).get("branch") or "main"
        source_path = root / "source"
        try:
            clone.shallow_clone(repo.url, branch, token=token, target_dir=str(source_path))
            manifest.setdefault("source", {})["clone_status"] = "ready"
            manifest["source"]["clone_error"] = None
        except Exception as exc:
            manifest.setdefault("source", {})["clone_status"] = "failed"
            manifest["source"]["clone_error"] = str(exc)[:500]
            write_manifest(root, manifest)
            raise ValueError(f"Clone failed: {exc}") from exc

        write_manifest(root, manifest)
        return {"clone_status": "ready", "source_path": str(source_path)}

    def _load(
        self, plan_id: str, tenant_id: str
    ) -> Tuple[ModernizationPlan, Repository, Path, Dict[str, Any]]:
        plan = (
            self.db.query(ModernizationPlan)
            .filter(ModernizationPlan.id == plan_id, ModernizationPlan.tenant_id == tenant_id)
            .first()
        )
        if not plan:
            raise ValueError("Plan not found")
        plan_type = getattr(plan, "plan_type", None) or "modernize"
        if plan_type != "fix":
            raise ValueError("Stage runner is only implemented for fix plans in W8.2")

        repo = (
            self.db.query(Repository)
            .filter(Repository.id == plan.repository_id, Repository.tenant_id == tenant_id)
            .first()
        )
        if not repo:
            raise ValueError("Repository not found")

        root_path = resolve_execution_root(plan)
        if not root_path:
            raise ValueError("Execution workspace not initialized — spawn execution first")
        root = Path(root_path)
        manifest = read_manifest(root)
        if not manifest:
            raise ValueError("Execution manifest missing — spawn execution first")
        return plan, repo, root, manifest

    def _source_path(self, root: Path, manifest: Dict[str, Any]) -> Path:
        source = manifest.get("source") or {}
        if source.get("clone_status") != "ready":
            raise ValueError("Source clone is not ready — retry clone first")
        local = source.get("local_path") or str(root / "source")
        path = Path(local)
        if not path.is_dir():
            raise ValueError("Source workspace directory missing")
        return path

    async def _run_remediation(
        self,
        plan: ModernizationPlan,
        repo: Repository,
        root: Path,
        manifest: Dict[str, Any],
        stage: str,
    ) -> Dict[str, Any]:
        source_path = self._source_path(root, manifest)
        findings = build_findings_payload(root, plan.assessment_json or {})
        return await FixCodeRunner(self.db, plan.tenant_id).run(
            plan=plan,
            source_path=source_path,
            root=root,
            findings=findings,
            stage=stage,
        )

    def _run_tests(self, root: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
        source_path = self._source_path(root, manifest)
        test_dir = root / "test"
        test_dir.mkdir(parents=True, exist_ok=True)
        output_path = test_dir / "output.txt"

        commands: List[List[str]] = []
        if (source_path / "pom.xml").is_file():
            commands.append(["mvn", "-q", "test"])
        if (source_path / "package.json").is_file():
            commands.append(["npm", "test", "--if-present"])
        if (source_path / "pyproject.toml").is_file() or (source_path / "setup.py").is_file():
            commands.append(["pytest", "-q"])
        if (source_path / "go.mod").is_file():
            commands.append(["go", "test", "./..."])

        lines = [f"Source: {source_path}", ""]
        exit_code = 0
        if not commands:
            lines.append("No test runner detected — stage marked complete (Alpha soft gate).")
            output_path.write_text("\n".join(lines), encoding="utf-8")
            return {"skipped": True, "reason": "no_test_runner", "output": str(output_path)}

        for cmd in commands:
            lines.append(f"$ {' '.join(cmd)}")
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(source_path),
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
            except subprocess.TimeoutExpired:
                lines.append("Timed out after 600s")
                exit_code = 1
            except FileNotFoundError as exc:
                lines.append(f"Command not found: {exc}")
                exit_code = 1
            lines.append("")

        output_path.write_text("\n".join(lines), encoding="utf-8")
        manifest.setdefault("test", {})["output"] = str(output_path)
        manifest["test"]["exit_code"] = exit_code

        if exit_code != 0:
            raise ValueError("Tests failed — see test/output.txt (Alpha: fix or approve manually)")

        return {"exit_code": exit_code, "output": str(output_path)}

    def _run_push(
        self,
        plan: ModernizationPlan,
        repo: Repository,
        root: Path,
        manifest: Dict[str, Any],
    ) -> Dict[str, Any]:
        source_path = self._source_path(root, manifest)
        token = _resolve_token(self.db, repo)
        branch = f"savi/fix-{plan.id[:8]}"
        base_branch = repo.default_branch or manifest.get("target", {}).get("branch") or "main"
        remote_url = repo.url or manifest.get("source", {}).get("github_url")
        if not remote_url:
            raise ValueError("No repository URL for push")

        push_result = self._git.push_workspace_branch(
            str(source_path),
            branch_name=branch,
            commit_message=f"Savi fix plan: {plan.title}\n\nAssessment-driven remediation (W8).",
            remote_url=remote_url,
            token=token,
            base_branch=base_branch,
        )
        if not push_result.get("success"):
            raise ValueError(push_result.get("error") or "Push failed")

        manifest["push"] = {
            "branch": branch,
            "commit_sha": push_result.get("commit_sha"),
            "base_branch": base_branch,
        }
        write_manifest(root, manifest)
        return push_result

    async def _run_pr(
        self,
        plan: ModernizationPlan,
        repo: Repository,
        root: Path,
        manifest: Dict[str, Any],
    ) -> Dict[str, Any]:
        push_info = manifest.get("push") or {}
        branch = push_info.get("branch")
        if not branch:
            raise ValueError("Push stage must complete before opening a PR")

        remote_url = repo.url or manifest.get("source", {}).get("github_url")
        if not remote_url:
            raise ValueError("No repository URL for PR")
        owner, repo_name = _parse_owner_repo(remote_url)
        base = push_info.get("base_branch") or repo.default_branch or "main"

        token = _resolve_token(self.db, repo)
        if not token:
            raise ValueError("GitHub token required to open a pull request")

        client = GitHubClient(token)
        body = (
            f"Automated fix plan from **Savi GPS**.\n\n"
            f"- Plan: `{plan.title}`\n"
            f"- Assessment run: `{getattr(plan, 'assessment_run_id', '') or 'n/a'}`\n\n"
            "Review agent-generated changes before merge.\n"
        )
        try:
            pr = await client.create_pull_request(
                owner,
                repo_name,
                title=f"Savi fix: {plan.title}",
                body=body,
                head=branch,
                base=base,
            )
        except GitHubApiError as exc:
            raise ValueError(exc.message) from exc

        pr_info = {
            "url": pr.get("html_url"),
            "number": pr.get("number"),
            "branch": branch,
            "base": base,
        }
        manifest["pr"] = pr_info
        push_dir = root / "push"
        push_dir.mkdir(parents=True, exist_ok=True)
        (push_dir / "pr.json").write_text(json.dumps(pr_info, indent=2), encoding="utf-8")
        write_manifest(root, manifest)
        return pr_info

"""Run fix/code stages using tenant Code Generation settings (W8.2)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import ModernizationPlan
from app.core.logger import logger
from app.services.llm_routing import get_build_code_llm_client, resolve_code_generation
from app.services.modernize.fix_remediation_agent import (
    FixRemediationAgent,
    apply_patches,
    build_findings_payload,
    load_fix_plan_md,
    _list_repo_tree,
)
from app.services.savi_coding_agent_adapter import CLI_MODES, SaviCodingAgentAdapter
from app.services.savi_sandbox import SaviSandbox


def _findings_brief(findings: Dict[str, Any], plan_title: str, stage: str, plan_md: str = "") -> str:
    parts = [
        f"# {plan_title}",
        "",
        f"## Execution stage: {stage}",
        "",
        "Apply **minimal safe fixes** from the fix plan and assessment findings. "
        "Edit existing files in this repository; do not scaffold a greenfield app.",
        "",
    ]
    if plan_md.strip():
        parts.extend(["## Fix plan", plan_md.strip()[:8000], ""])
    parts.extend(
        [
            "## Findings JSON",
            f"```json\n{json.dumps(findings, indent=2)[:12000]}\n```",
            "",
        ]
    )
    return "\n".join(parts)


def _git_changed_files(source_path: Path) -> List[str]:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(source_path),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    changed: List[str] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if len(line) < 4:
            continue
        path_part = line[3:].strip()
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1]
        if path_part:
            changed.append(path_part)
    return changed


class FixCodeRunner:
    """Fix + Code stages routed via Admin → Tenant → Code generation provider."""

    def __init__(self, db: Session, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.code_settings = resolve_code_generation(db, tenant_id)
        self.execution_mode = (self.code_settings.get("execution_mode") or "llm").lower()

    async def run(
        self,
        *,
        plan: ModernizationPlan,
        source_path: Path,
        root: Path,
        findings: Dict[str, Any],
        stage: str,
    ) -> Dict[str, Any]:
        if stage not in ("fix", "code"):
            raise ValueError(f"FixCodeRunner only handles fix/code stages, got {stage}")

        meta = {
            "stage": stage,
            "code_generation": self.code_settings,
            "execution_mode": self.execution_mode,
        }

        if self.execution_mode in CLI_MODES or self.execution_mode == "heuristic":
            return await self._run_adapter_path(
                plan=plan,
                source_path=source_path,
                root=root,
                findings=findings,
                stage=stage,
                meta=meta,
            )

        # Server inherit `llm` or API-oriented path — use Code Generation LLM client
        return await self._run_api_path(
            plan=plan,
            source_path=source_path,
            root=root,
            findings=findings,
            stage=stage,
            meta=meta,
        )

    async def _run_adapter_path(
        self,
        *,
        plan: ModernizationPlan,
        source_path: Path,
        root: Path,
        findings: Dict[str, Any],
        stage: str,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        adapter = SaviCodingAgentAdapter(mode=self.execution_mode)
        item = SimpleNamespace(
            id=plan.id,
            title=plan.title,
            description=f"Repository fix plan — {stage} stage",
        )
        plan_text = load_fix_plan_md(root, plan)
        brief = _findings_brief(findings, plan.title, stage, plan_md=plan_text)
        agent_dir = root / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        short = plan.id[:8]

        if stage == "fix":
            # Seed agent plan from brief/plan.md (findings-derived); do not invent a modernize plan
            if plan_text:
                plan_md = plan_text
                tokens = 0
            else:
                plan_md, tokens = await adapter.plan(item, {"brief_markdown": brief})
            (agent_dir / "fix_plan.md").write_text(plan_md, encoding="utf-8")
            savi_plan = source_path / ".savi" / "work" / short / "PLAN.md"
            savi_plan.parent.mkdir(parents=True, exist_ok=True)
            savi_plan.write_text(plan_md, encoding="utf-8")
            return {
                **meta,
                "summary": plan_md[:2000],
                "files_written": [str(savi_plan.relative_to(source_path))],
                "tokens_estimate": tokens,
                "adapter": self.execution_mode,
                "plan_source": "brief/plan.md" if plan_text else "adapter.plan",
            }

        # code — implement prior plan in the real checkout
        plan_md = (agent_dir / "fix_plan.md").read_text(encoding="utf-8") if (agent_dir / "fix_plan.md").is_file() else ""
        if not plan_md.strip():
            savi_plan = source_path / ".savi" / "work" / short / "PLAN.md"
            if savi_plan.is_file():
                plan_md = savi_plan.read_text(encoding="utf-8")
        if not plan_md.strip():
            plan_md = plan_text
        if not plan_md.strip():
            plan_md, _ = await adapter.plan(item, {"brief_markdown": brief})

        sandbox = SaviSandbox(root=source_path)
        before = set(_git_changed_files(source_path))
        files, tokens = await adapter.propose_files(
            item,
            {"brief_markdown": brief},
            plan_md,
            sandbox,
        )
        after = set(_git_changed_files(source_path))
        written = sorted(after - before) or [f["path"] for f in files if f.get("path")]

        log_path = agent_dir / "code_result.json"
        log_path.write_text(
            json.dumps(
                {
                    **meta,
                    "files_proposed": files,
                    "files_written": written,
                    "tokens_estimate": tokens,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            **meta,
            "summary": f"Code stage via {self.execution_mode} ({len(written)} paths touched)",
            "files_written": written,
            "tokens_estimate": tokens,
            "adapter": self.execution_mode,
            "agent_log": str(log_path),
        }

    async def _run_api_path(
        self,
        *,
        plan: ModernizationPlan,
        source_path: Path,
        root: Path,
        findings: Dict[str, Any],
        stage: str,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        agent_dir = root / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        plan_text = load_fix_plan_md(root, plan)
        short = plan.id[:8]

        if stage == "fix":
            # Lock plan only — no source patches until Code stage
            if not plan_text.strip():
                plan_text = _findings_brief(findings, plan.title, stage)
            (agent_dir / "fix_plan.md").write_text(plan_text, encoding="utf-8")
            savi_plan = source_path / ".savi" / "work" / short / "PLAN.md"
            savi_plan.parent.mkdir(parents=True, exist_ok=True)
            savi_plan.write_text(plan_text, encoding="utf-8")
            return {
                **meta,
                "summary": plan_text[:2000],
                "files_written": [str(savi_plan.relative_to(source_path))],
                "plan_source": "brief/plan.md" if (root / "brief" / "plan.md").is_file() else "plan_md",
                "llm": "build_code_generation",
            }

        agent = FixRemediationAgent(self.db, self.tenant_id)
        agent.llm_client = get_build_code_llm_client(self.db, self.tenant_id)

        if not plan_text and (agent_dir / "fix_plan.md").is_file():
            plan_text = (agent_dir / "fix_plan.md").read_text(encoding="utf-8")

        state = {
            "findings": findings,
            "repo_tree": _list_repo_tree(source_path),
            "plan_title": f"{plan.title} ({stage})",
            "plan_md": plan_text,
        }
        agent_result = await agent.process(state)
        written = apply_patches(source_path, agent_result.get("files") or [])

        log_path = agent_dir / f"{stage}_result.json"
        log_path.write_text(
            json.dumps(
                {
                    **meta,
                    **agent_result,
                    "files_written": written,
                    "llm": "build_code_generation",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        summary_path = agent_dir / f"{stage}_summary.md"
        summary_path.write_text(
            agent_result.get("summary") or f"No automated changes for {stage}.",
            encoding="utf-8",
        )
        logger.info(
            "Fix %s stage used code-gen LLM (provider=%s, mode=%s)",
            stage,
            self.code_settings.get("provider"),
            self.execution_mode,
        )
        return {
            **meta,
            "files_written": written,
            "summary": agent_result.get("summary"),
            "agent_log": str(log_path),
            "llm": "build_code_generation",
        }

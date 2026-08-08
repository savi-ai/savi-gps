"""Coding agent adapter for Savi (T6/T7).

Modes (prefer active seat via SaviIdentitySeatService.resolve_execution_mode;
else settings.SAVI_CODING_AGENT Alpha fallback):
- heuristic / llm / claude_cli / copilot_cli / kiro_cli

CLI prompts are shared templates under app/scripts/prompts/savi/ and are the same
files used by scripts/claude|copilot|kiro wrappers.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.config import settings
from app.core.database import SaviWorkItem
from app.core.logger import logger
from app.services.savi_policy_gate import assert_savi_action_allowed
from app.services.savi_sandbox import SaviSandbox, write_files

CLI_MODES = frozenset({"claude_cli", "copilot_cli", "kiro_cli"})

_CLI_BINARIES: Dict[str, Sequence[str]] = {
    "claude_cli": ("claude",),
    "copilot_cli": ("copilot",),
    "kiro_cli": ("kiro-cli", "kiro"),
}

_VENDOR_DIR: Dict[str, str] = {
    "claude_cli": "claude",
    "copilot_cli": "copilot",
    "kiro_cli": "kiro",
}

_SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"
_PROMPTS_DIR = _SCRIPTS_ROOT / "prompts" / "savi"
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Z0-9_]+)\s*\}\}")


def _render_template(template: str, values: Dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        return values.get(match.group(1), "")

    return _PLACEHOLDER.sub(repl, template)


def load_savi_prompt(name: str, values: Optional[Dict[str, str]] = None) -> str:
    """Load prompts/savi/<name>.txt and substitute {{PLACEHOLDERS}}."""
    path = _PROMPTS_DIR / f"{name}.txt"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    if not values:
        return text
    return _render_template(text, values)


class SaviCodingAgentAdapter:
    def __init__(self, mode: Optional[str] = None):
        self.mode = (mode or settings.SAVI_CODING_AGENT or "llm").lower()

    def _resolve_cli_bin(self) -> Optional[str]:
        for name in _CLI_BINARIES.get(self.mode, ()):
            if shutil.which(name):
                return name
        return None

    def _vendor_script(self, script_name: str) -> Optional[Path]:
        vendor = _VENDOR_DIR.get(self.mode)
        if not vendor:
            return None
        path = _SCRIPTS_ROOT / vendor / script_name
        return path if path.is_file() else None

    def _plan_prompt(self, item: SaviWorkItem, brief: str) -> str:
        system = load_savi_prompt("system")
        body = load_savi_prompt(
            "plan",
            {
                "TITLE": item.title or "",
                "DESCRIPTION": item.description or "",
                "BRIEF": (brief or "")[:8000],
            },
        )
        if body:
            return f"{system}\n\n{body}".strip() if system else body
        # Fallback if templates missing
        return (
            f"Write a short implementation plan in markdown for: {item.title}\n\n"
            f"Description:\n{item.description or ''}\n\n"
            f"Context:\n{(brief or '')[:3000]}\n\n"
            "Do not merge or deploy. Output markdown only."
        )

    def _implement_prompt(self, item: SaviWorkItem, short: str) -> str:
        plan_path = f".savi/work/{short}/PLAN.md"
        system = load_savi_prompt("system")
        body = load_savi_prompt(
            "implement",
            {
                "TITLE": item.title or "",
                "PLAN_PATH": plan_path,
                "SHORT_ID": short,
            },
        )
        if body:
            return f"{system}\n\n{body}".strip() if system else body
        return (
            f"In the current directory, implement a minimal change for: {item.title}. "
            f"Follow the plan in {plan_path}. Do not merge or deploy."
        )

    async def plan(
        self, item: SaviWorkItem, context_pack: Optional[Dict[str, Any]]
    ) -> Tuple[str, int]:
        """Return (plan_markdown, tokens_estimate)."""
        assert_savi_action_allowed("plan")
        brief = ""
        if context_pack:
            brief = context_pack.get("brief_markdown") or ""
        if self.mode == "heuristic":
            return self._heuristic_plan(item, brief), 0

        if self.mode in CLI_MODES and self._resolve_cli_bin():
            try:
                return await self._cli_plan(item, brief)
            except Exception as e:
                logger.warning("%s plan failed, falling back: %s", self.mode, e)
        elif self.mode in CLI_MODES:
            logger.warning(
                "%s selected but CLI binary not on PATH — falling back to llm/heuristic",
                self.mode,
            )

        try:
            return await self._llm_plan(item, brief)
        except Exception as e:
            logger.warning("LLM plan failed, using heuristic: %s", e)
            return self._heuristic_plan(item, brief), 0

    async def propose_files(
        self,
        item: SaviWorkItem,
        context_pack: Optional[Dict[str, Any]],
        plan: str,
        sandbox: SaviSandbox,
    ) -> Tuple[List[Dict[str, str]], int]:
        """Return (files [{path,content}], tokens). Writes into sandbox."""
        assert_savi_action_allowed("code")
        short = (item.id or "work")[:8]
        if self.mode == "heuristic":
            files = self._heuristic_files(item, plan, short)
            write_files(sandbox, files)
            return files, 0

        if self.mode in CLI_MODES and self._resolve_cli_bin():
            try:
                files, tokens = await self._cli_code(item, plan, sandbox, short)
                if files:
                    return files, tokens
            except Exception as e:
                logger.warning("%s code failed, falling back: %s", self.mode, e)
        elif self.mode in CLI_MODES:
            logger.warning(
                "%s selected but CLI binary not on PATH — falling back to llm/heuristic",
                self.mode,
            )

        try:
            files, tokens = await self._llm_files(item, plan, short)
            write_files(sandbox, files)
            return files, tokens
        except Exception as e:
            logger.warning("LLM code failed, using heuristic: %s", e)
            files = self._heuristic_files(item, plan, short)
            write_files(sandbox, files)
            return files, 0

    def _heuristic_plan(self, item: SaviWorkItem, brief: str) -> str:
        return (
            f"# Plan: {item.title}\n\n"
            f"## Goal\n{item.description or '(no description)'}\n\n"
            f"## Approach\n"
            f"1. Ground in GPS context pack.\n"
            f"2. Implement the smallest change that satisfies acceptance criteria.\n"
            f"3. Add/adjust tests if a test harness exists.\n"
            f"4. Open a PR for human review (no merge).\n\n"
            f"## Context excerpt\n\n{(brief or '')[:2500]}\n"
        )

    def _heuristic_files(
        self, item: SaviWorkItem, plan: str, short: str
    ) -> List[Dict[str, str]]:
        return [
            {
                "path": f".savi/work/{short}/PLAN.md",
                "content": plan,
            },
            {
                "path": f".savi/work/{short}/IMPLEMENTATION_NOTES.md",
                "content": (
                    f"# Implementation notes — {item.title}\n\n"
                    "Generated by Savi coding adapter (heuristic mode).\n"
                    "Configure an active coding-agent seat (claude_cli / "
                    "copilot_cli / kiro_cli) for real agent runs.\n\n"
                    f"Work item: `{item.id}`\n"
                ),
            },
        ]

    async def _llm_plan(self, item: SaviWorkItem, brief: str) -> Tuple[str, int]:
        from app.core.llm_client import get_llm_client

        client = get_llm_client()
        prompt = self._plan_prompt(item, brief)
        system = load_savi_prompt("system") or "Be concise and actionable."
        text = await client.generate(prompt, system_prompt=system)
        tokens = max(1, len(prompt + (text or "")) // 4)
        return text or self._heuristic_plan(item, brief), tokens

    async def _llm_files(
        self, item: SaviWorkItem, plan: str, short: str
    ) -> Tuple[List[Dict[str, str]], int]:
        from app.core.llm_client import get_llm_client

        client = get_llm_client()
        prompt = (
            "Given this plan, propose 1-3 small markdown or code files as JSON array "
            '[{"path":"...","content":"..."}]. Prefer .savi/work/{id}/ paths if unsure. '
            "No merge/deploy instructions.\n\n"
            f"Work id: {short}\nPlan:\n{plan[:5000]}"
        )
        system = load_savi_prompt("system") or "Return JSON only."
        raw = await client.generate(prompt, system_prompt=system)
        tokens = max(1, len(prompt + (raw or "")) // 4)
        files = self._parse_files_json(raw, short, plan, item)
        return files, tokens

    def _parse_files_json(
        self, raw: Optional[str], short: str, plan: str, item: SaviWorkItem
    ) -> List[Dict[str, str]]:
        if not raw:
            return self._heuristic_files(item, plan, short)
        try:
            m = re.search(r"\[[\s\S]*\]", raw)
            data = json.loads(m.group(0) if m else raw)
            out = []
            for f in data:
                if isinstance(f, dict) and f.get("path") and f.get("content") is not None:
                    out.append(
                        {"path": str(f["path"]), "content": str(f["content"])}
                    )
            return out or self._heuristic_files(item, plan, short)
        except Exception:
            return self._heuristic_files(item, plan, short)

    def _build_cli_argv(self, binary: str, prompt: str) -> List[str]:
        if self.mode == "copilot_cli" or binary == "copilot":
            return [binary, "-p", prompt, "--allow-all-tools", "-s"]
        if self.mode == "kiro_cli" or binary in ("kiro-cli", "kiro"):
            if binary == "kiro-cli":
                return [
                    binary,
                    "chat",
                    "--no-interactive",
                    "--trust-all-tools",
                    prompt,
                ]
            return [binary, "--print", prompt]
        return [binary, "-p", prompt]

    async def _cli_plan(
        self, item: SaviWorkItem, brief: str
    ) -> Tuple[str, int]:
        binary = self._resolve_cli_bin()
        if not binary:
            raise RuntimeError(f"{self.mode}: CLI binary not on PATH")

        # Prefer vendor savi_plan.sh (renders shared prompts)
        plan_script = self._vendor_script("savi_plan.sh")
        if plan_script:
            brief_path = None
            tmp = None
            try:
                if brief:
                    import tempfile

                    tmp = tempfile.NamedTemporaryFile(
                        mode="w", suffix=".md", delete=False, encoding="utf-8"
                    )
                    tmp.write(brief[:8000])
                    tmp.close()
                    brief_path = tmp.name
                argv = [
                    str(plan_script),
                    item.title or "Untitled",
                    item.description or "",
                ]
                if brief_path:
                    argv.append(brief_path)
                proc = subprocess.run(
                    argv, capture_output=True, text=True, timeout=180
                )
                if proc.returncode != 0:
                    raise RuntimeError(
                        (proc.stderr or proc.stdout or "savi_plan.sh failed")[:400]
                    )
                out = (proc.stdout or "").strip()
                return out, max(1, len(out) // 4)
            finally:
                if brief_path:
                    Path(brief_path).unlink(missing_ok=True)

        prompt = self._plan_prompt(item, brief)
        argv = self._build_cli_argv(binary, prompt)
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or f"{binary} failed")[:400])
        out = (proc.stdout or "").strip()
        return out, max(1, len(out) // 4)

    async def _cli_code(
        self,
        item: SaviWorkItem,
        plan: str,
        sandbox: SaviSandbox,
        short: str,
    ) -> Tuple[List[Dict[str, str]], int]:
        binary = self._resolve_cli_bin()
        if not binary:
            raise RuntimeError(f"{self.mode}: CLI binary not on PATH")

        plan_rel = f".savi/work/{short}/PLAN.md"
        plan_path = sandbox.root / plan_rel
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(plan, encoding="utf-8")

        impl_script = self._vendor_script("savi_implement.sh")
        if impl_script:
            proc = subprocess.run(
                [
                    str(impl_script),
                    item.title or "Untitled",
                    str(sandbox.root),
                    plan_rel,
                    short,
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            tokens = max(1, len((proc.stdout or "") + (proc.stderr or "")) // 4)
            if proc.returncode != 0:
                raise RuntimeError(
                    (proc.stderr or proc.stdout or "savi_implement.sh failed")[:400]
                )
            return self._collect_sandbox_files(sandbox, item, plan, short), tokens

        prompt = self._implement_prompt(item, short)
        argv = self._build_cli_argv(binary, prompt)
        proc = subprocess.run(
            argv,
            cwd=str(sandbox.root),
            capture_output=True,
            text=True,
            timeout=600,
        )
        tokens = max(1, len((proc.stdout or "") + (proc.stderr or "")) // 4)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or f"{binary} failed")[:400])
        return self._collect_sandbox_files(sandbox, item, plan, short), tokens

    def _collect_sandbox_files(
        self,
        sandbox: SaviSandbox,
        item: SaviWorkItem,
        plan: str,
        short: str,
    ) -> List[Dict[str, str]]:
        files: List[Dict[str, str]] = []
        for path in sandbox.root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(sandbox.root))
            if rel.startswith(".git"):
                continue
            if not (
                rel.startswith(".savi/")
                or rel.endswith((".md", ".py", ".ts", ".tsx", ".js"))
            ):
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                continue
            if len(content) > 200_000:
                continue
            files.append({"path": rel, "content": content})
        if not files:
            files = self._heuristic_files(item, plan, short)
            write_files(sandbox, files)
        return files

    # --- AgentRun surface (ADR 0010 §3 — extends this adapter, not a parallel type) ---

    @property
    def execution_mode(self) -> str:
        return self.mode

    def metered_by(self) -> str:
        """Seat CLI ⇒ metered_by_seat; API/llm/heuristic ⇒ metered_by_platform (§6a)."""
        if self.mode in CLI_MODES:
            return "seat"
        return "platform"

    def run_versions(self) -> "RunVersions":
        from app.services.agent_runtime.contracts import RunVersions

        model = None
        if self.mode in ("llm", "api"):
            model = getattr(settings, "ANTHROPIC_MODEL", None) or getattr(
                settings, "LLM_PROVIDER", None
            )
        return RunVersions(
            harness_version="savi-coding-adapter/1",
            model_id=str(model) if model else None,
            prompt_version="savi-prompts/1",
            execution_mode=self.mode,
        )

    async def submit(self, job: Dict[str, Any]) -> str:
        run_id = str(job.get("run_id") or job.get("work_item_id") or "local")
        self._pending_job = job
        self._pending_run_id = run_id
        return run_id

    async def stream(self, run_id: str):
        yield {"run_id": run_id, "event": "started", "mode": self.mode}
        yield {"run_id": run_id, "event": "progress", "pct": 50}

    async def result(self, run_id: str) -> "AgentRunResult":
        from app.services.agent_runtime.contracts import AgentRunResult
        from app.services.agent_runtime.outbound_scrub import scrub_structure

        job = getattr(self, "_pending_job", None) or {}
        artifacts = dict(job.get("artifacts") or {})
        trajectory = list(job.get("trajectory") or [])
        scrubbed_art, n1 = scrub_structure(artifacts)
        scrubbed_traj, n2 = scrub_structure(trajectory)
        return AgentRunResult(
            artifacts=scrubbed_art if isinstance(scrubbed_art, dict) else {},
            trajectory=scrubbed_traj if isinstance(scrubbed_traj, list) else [],
            versions=self.run_versions(),
            metered_by=self.metered_by(),  # type: ignore[arg-type]
            tokens_estimate=int(job.get("tokens") or 0),
            scrubbed=(n1 + n2) > 0,
        )

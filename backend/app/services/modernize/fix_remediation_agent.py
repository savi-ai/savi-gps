"""Fix remediation agent — constrained patches for repo fix plans (W8.2)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.logger import logger
from app.services.agents.base_agent import BaseAgent
from app.services.llm_routing import get_build_code_llm_client


def _list_repo_tree(source_path: Path, max_files: int = 40) -> str:
    lines: List[str] = []
    if not source_path.is_dir():
        return ""
    for path in sorted(source_path.rglob("*")):
        if path.is_dir() or ".git" in path.parts:
            continue
        rel = path.relative_to(source_path).as_posix()
        if any(part.startswith(".") for part in path.parts):
            continue
        lines.append(rel)
        if len(lines) >= max_files:
            lines.append("…")
            break
    return "\n".join(lines)


class FixRemediationAgent(BaseAgent):
    """Generate minimal file patches from assessment findings."""

    SYSTEM_PROMPT = """You are a senior engineer applying **minimal, safe fixes** to an existing repository.

Given assessment findings (signals, policy gaps), produce **small targeted changes** — bump versions, add missing config files, fix obvious issues. Do not rewrite the whole app.

Return ONLY valid JSON:
{
  "summary": "One paragraph of what you changed",
  "files": [
    {"path": "relative/path/from/repo/root", "content": "full file content"}
  ]
}

Rules:
- Prefer editing existing files over creating many new ones
- Max 8 files
- Paths must be relative to repo root (no leading slash)
- If nothing can be safely automated, return {"summary": "...", "files": []}
"""

    def __init__(self, db: Session, tenant_id: str):
        super().__init__(db=db, tenant_id=tenant_id, purpose="code")
        # Explicit Code Generation LLM (Admin → Tenant → Code generation)
        self.llm_client = get_build_code_llm_client(db, tenant_id)

    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        findings = state.get("findings") or {}
        tree = state.get("repo_tree") or ""
        plan_title = state.get("plan_title") or "Fix plan"
        plan_md = state.get("plan_md") or ""

        user_prompt = f"""# {plan_title}

## Fix plan (execute these work items)
{plan_md[:8000] if plan_md else "_No plan.md — use findings only._"}

## Findings (source of truth)
```json
{json.dumps(findings, indent=2)[:12000]}
```

## Repository file tree (sample)
```
{tree}
```

Implement the **work items** from the fix plan with minimal patches as JSON."""

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        raw = await self.llm_client.chat(messages, temperature=0.2)
        content = raw if isinstance(raw, str) else str(raw)
        start = content.find("{")
        end = content.rfind("}") + 1
        if start < 0 or end <= start:
            return {"summary": "Could not parse agent response", "files": [], "raw": content[:500]}

        try:
            parsed = json.loads(content[start:end])
        except json.JSONDecodeError:
            logger.warning("FixRemediationAgent JSON parse failed")
            return {"summary": "Invalid JSON from agent", "files": [], "raw": content[:500]}

        files = parsed.get("files") or []
        if not isinstance(files, list):
            files = []
        return {
            "summary": parsed.get("summary") or "",
            "files": files[:8],
        }


def apply_patches(source_path: Path, files: List[Dict[str, Any]]) -> List[str]:
    """Write agent file patches into source checkout. Returns paths written."""
    written: List[str] = []
    for item in files:
        rel = (item.get("path") or "").lstrip("/")
        if not rel or ".." in rel:
            continue
        content = item.get("content")
        if content is None:
            continue
        dest = source_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content if isinstance(content, str) else str(content), encoding="utf-8")
        written.append(rel)
    return written


def build_findings_payload(root: Path, assessment: Dict[str, Any]) -> Dict[str, Any]:
    brief_path = root / "brief" / "findings.json"
    if brief_path.is_file():
        try:
            return json.loads(brief_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    from app.services.modernize.fix_plan_builder import assessment_to_findings

    return assessment_to_findings(assessment)


def load_fix_plan_md(root: Path, plan: Any) -> str:
    """Prefer brief/plan.md (from findings), then plan.plan_md."""
    brief_plan = root / "brief" / "plan.md"
    if brief_plan.is_file():
        text = brief_plan.read_text(encoding="utf-8").strip()
        if text:
            return text
    return (getattr(plan, "plan_md", None) or "").strip()

"""ADR 0010 Phase A — agent runtime contracts (outer-loop moat on Arq)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Protocol, runtime_checkable

MeteredBy = Literal["platform", "seat"]


@dataclass(frozen=True)
class IdempotencyKey:
    """Stable business tuple — never an Arq/Temporal job id (ADR 0010 §5a)."""

    tenant_id: str
    repo_id: str
    work_ref: str
    action_type: str
    attempt: int = 1

    def as_string(self) -> str:
        return "|".join(
            [
                self.tenant_id or "",
                self.repo_id or "",
                self.work_ref or "",
                self.action_type or "",
                str(self.attempt),
            ]
        )

    def branch_name(self, prefix: str = "savi") -> str:
        """Deterministic git branch from the business tuple (ADR 0010 §5b)."""
        import hashlib
        import re

        digest = hashlib.sha256(self.as_string().encode("utf-8")).hexdigest()[:12]
        ref = re.sub(r"[^a-zA-Z0-9._-]+", "-", (self.work_ref or "work")[:24]).strip("-")
        action = re.sub(r"[^a-zA-Z0-9._-]+", "-", (self.action_type or "act")[:20]).strip(
            "-"
        )
        return f"{prefix}/{ref}-{action}-{digest}-a{self.attempt}"[:200]


@dataclass
class RunVersions:
    """Pinned versions for reproducibility (ADR 0010 §5g)."""

    harness_version: str = "savi-coding-adapter/1"
    model_id: Optional[str] = None
    model_version: Optional[str] = None
    prompt_version: str = "savi-prompts/1"
    execution_mode: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "harness_version": self.harness_version,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "execution_mode": self.execution_mode,
        }


@dataclass
class AgentRunResult:
    """Result of an AgentRun (ADR 0010 §3 / checklist Step 1)."""

    artifacts: Dict[str, Any] = field(default_factory=dict)
    trajectory: List[Dict[str, Any]] = field(default_factory=list)
    versions: RunVersions = field(default_factory=RunVersions)
    metered_by: MeteredBy = "platform"
    tokens_estimate: int = 0
    scrubbed: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifacts": self.artifacts,
            "trajectory": self.trajectory,
            "versions": self.versions.to_dict(),
            "metered_by": self.metered_by,
            "tokens_estimate": self.tokens_estimate,
            "scrubbed": self.scrubbed,
            "error": self.error,
        }


@runtime_checkable
class AgentRun(Protocol):
    """
    Extension of the ADR 0009 coding adapter — not a parallel abstraction.

    Shape: submit(job) → stream(events|progress) → result(artifacts, trajectory, versions).
    """

    execution_mode: str

    async def submit(self, job: Dict[str, Any]) -> str:
        """Accept a job; return a run_id (local / work-item scoped)."""
        ...

    async def stream(self, run_id: str):
        """Yield progress/event dicts."""
        ...

    async def result(self, run_id: str) -> AgentRunResult:
        """Final artifacts + trajectory + pinned versions."""
        ...

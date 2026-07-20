"""Policy Injection Agent - Resolves and injects effective policies into workflow state."""
from typing import Dict, Any, List

from app.core.database import SessionLocal
from app.core.models import EffectivePolicySet, ResolvedPolicy
from app.core.logger import logger
from app.services.agents.base_agent import BaseAgent
from app.services.policy_merge_engine import PolicyMergeEngine, STAGE_CATEGORY_MAP


class PolicyInjectionAgent(BaseAgent):
    """Agent that resolves the Effective Policy Set and injects policy context into workflow state.

    Responsibilities (Requirements 3.1, 3.2, 3.3, 8.1–8.5):
    - Resolve effective policies via PolicyMergeEngine and cache in state['policy_bundle']
    - Format resolved policies as structured prompt context for downstream agents
    - Log warnings when no policies are found for a stage category
    """

    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve effective policies and store in state.

        If state['policy_bundle'] is already populated (cached from a prior call
        within the same workflow run), skip resolution and return immediately.
        This satisfies the per-run caching requirement (Req 8.4, P9).
        """
        # Check cache — avoid redundant resolution within a single run
        if state.get("policy_bundle"):
            logger.info("PolicyInjectionAgent: using cached policy_bundle from state")
            return state

        tenant_id = state.get("tenant_id", "")
        project_id = state.get("project_id", "")

        if not tenant_id or not project_id:
            logger.warning(
                "PolicyInjectionAgent: tenant_id or project_id missing from state, "
                "skipping policy resolution"
            )
            return state

        try:
            db = SessionLocal()
            try:
                engine = PolicyMergeEngine(db)
                effective_set: EffectivePolicySet = engine.resolve_effective_policies(
                    tenant_id, project_id
                )

                # Log warnings for stages that have no applicable policies
                for stage, categories in STAGE_CATEGORY_MAP.items():
                    stage_policies = engine.filter_by_stage(effective_set, stage)
                    if not stage_policies:
                        logger.warning(
                            "PolicyInjectionAgent: no policies found for stage '%s' "
                            "(categories: %s)",
                            stage,
                            ", ".join(categories),
                        )

                # Serialize and cache in state
                state["policy_bundle"] = effective_set.model_dump(mode="json")
                logger.info(
                    "PolicyInjectionAgent: resolved %d policies for tenant=%s project=%s",
                    len(effective_set.policies_by_category),
                    tenant_id,
                    project_id,
                )
            finally:
                db.close()
        except Exception as e:
            logger.error("PolicyInjectionAgent: failed to resolve policies — %s", e)
            state["error"] = f"Policy resolution failed: {e}"

        return state

    @staticmethod
    def format_policy_context(policies: List[ResolvedPolicy], stage: str) -> str:
        """Format a list of resolved policies as markdown prompt context.

        Args:
            policies: Resolved policies applicable to the stage.
            stage: The current workflow stage name.

        Returns:
            A markdown-formatted string suitable for injection into an agent's
            system prompt.  Returns an empty string when *policies* is empty.
        """
        if not policies:
            logger.warning(
                "PolicyInjectionAgent.format_policy_context: "
                "no policies to format for stage '%s'",
                stage,
            )
            return ""

        lines: List[str] = [
            f"## Governance Policies for Stage: {stage.capitalize()}",
            "",
        ]

        for policy in policies:
            lines.append(f"### {policy.name}")
            lines.append(f"- **Category:** {policy.category}")
            lines.append(f"- **Level:** {policy.level}")
            if policy.version:
                lines.append(f"- **Version:** {policy.version}")

            # Content may be a dict/list (from JSON) or a plain string
            content = policy.content
            if isinstance(content, dict):
                import json
                content = json.dumps(content, indent=2)
            elif isinstance(content, list):
                import json
                content = json.dumps(content, indent=2)

            lines.append("")
            lines.append(str(content))
            lines.append("")

        return "\n".join(lines)

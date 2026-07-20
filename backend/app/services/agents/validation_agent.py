"""Validation Agent - Unified SOP and policy compliance validation for workflow stages.

Combines SOP validation (via SOP_Service) and policy compliance checking into a
single pass, producing a unified ValidationResult.

Requirements: 3.3, 3.4, 11.1, 11.2, 11.3, 11.4, 11.5
"""
from typing import Dict, Any, List

from app.core.models import (
    ValidationResult,
    Violation,
    PolicyViolation,
    EffectivePolicySet,
    ResolvedPolicy,
    ArtifactType,
    SOPValidationRequest,
)
from app.core.logger import logger
from app.services.agents.base_agent import BaseAgent
from app.services.sop_service import sop_service
from app.services.policy_merge_engine import STAGE_CATEGORY_MAP


# Map workflow stage names to SOP ArtifactType values used by sop_service
STAGE_ARTIFACT_TYPE_MAP: Dict[str, ArtifactType] = {
    "architecture": ArtifactType.ARCHITECTURE,
    "code": ArtifactType.PIPELINE,
    "deploy": ArtifactType.INFRA,
    "story": ArtifactType.STORY,
    "stories": ArtifactType.STORY,
}

# Severities that block progression (Req 11.4)
BLOCKING_SEVERITIES = {"critical", "high"}


class ValidationAgent(BaseAgent):
    """Agent that validates stage output against SOPs and policies.

    After each workflow stage, this agent:
    1. Loads applicable SOPs from SOP_Service (Req 11.1)
    2. Loads applicable policies from state['policy_bundle'] filtered by stage (Req 11.2)
    3. Validates stage output against both
    4. Returns a unified ValidationResult (Req 11.3)
    5. Sets state['validation_blocked'] = True for blocking violations (Req 11.4)
    6. Allows progression for warning-level violations (Req 11.5)
    """

    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Validate the current stage output against SOPs and policies."""
        stage = state.get("stage", "")
        stage_output = self._get_stage_output(state, stage)

        if not stage_output:
            logger.warning(
                "ValidationAgent: no output found for stage '%s', skipping validation",
                stage,
            )
            result = ValidationResult(passed=True)
            state["validation_result"] = result.model_dump(mode="json")
            state["validation_blocked"] = False
            return state

        # 1. Validate against SOPs (Req 11.1)
        sop_violations, sop_warnings = await self._validate_sops(stage, stage_output)

        # 2. Validate against policies (Req 11.2)
        policy_violations, policy_warnings = await self._validate_policies(
            state, stage, stage_output
        )

        # 3. Build unified ValidationResult (Req 11.3)
        all_sop_violations = sop_violations
        all_warnings = sop_warnings + policy_warnings

        remediation_hints: List[str] = []
        for v in sop_violations:
            if v.remediation_hint:
                remediation_hints.append(v.remediation_hint)
        for pv in policy_violations:
            if pv.remediation_hint:
                remediation_hints.append(pv.remediation_hint)
        for w in all_warnings:
            if w.remediation_hint:
                remediation_hints.append(w.remediation_hint)

        has_blocking = len(sop_violations) > 0 or len(policy_violations) > 0
        passed = not has_blocking

        validation_result = ValidationResult(
            passed=passed,
            sop_violations=all_sop_violations,
            policy_violations=policy_violations,
            warnings=all_warnings,
            remediation_hints=remediation_hints,
        )

        # 4/5. Set validation_blocked based on severity (Req 11.4, 11.5)
        state["validation_result"] = validation_result.model_dump(mode="json")
        state["validation_blocked"] = has_blocking

        if has_blocking:
            logger.warning(
                "ValidationAgent: stage '%s' BLOCKED — %d SOP violations, %d policy violations",
                stage,
                len(sop_violations),
                len(policy_violations),
            )
        elif all_warnings:
            logger.info(
                "ValidationAgent: stage '%s' passed with %d warnings",
                stage,
                len(all_warnings),
            )
        else:
            logger.info("ValidationAgent: stage '%s' passed validation", stage)

        return state

    # ------------------------------------------------------------------
    # SOP validation
    # ------------------------------------------------------------------

    async def _validate_sops(
        self, stage: str, stage_output: str
    ) -> tuple[List[Violation], List[Violation]]:
        """Validate stage output against applicable SOPs.

        Returns:
            Tuple of (blocking_violations, warning_violations).
        """
        blocking: List[Violation] = []
        warnings: List[Violation] = []

        artifact_type = STAGE_ARTIFACT_TYPE_MAP.get(stage.lower())
        if not artifact_type:
            logger.info(
                "ValidationAgent: no SOP artifact type mapping for stage '%s'", stage
            )
            return blocking, warnings

        applicable_sops = sop_service.filter_sops(applies_to=artifact_type)
        if not applicable_sops:
            logger.info(
                "ValidationAgent: no applicable SOPs for stage '%s'", stage
            )
            return blocking, warnings

        for sop in applicable_sops:
            for rule in sop.rules:
                violation = await self._check_sop_rule(sop, rule, stage_output)
                if violation:
                    severity = rule.severity.lower() if rule.severity else "medium"
                    if severity in BLOCKING_SEVERITIES:
                        blocking.append(violation)
                    else:
                        warnings.append(violation)

        return blocking, warnings

    async def _check_sop_rule(self, sop, rule, content: str) -> Violation | None:
        """Check a single SOP rule against content using LLM-based analysis."""
        try:
            prompt = (
                f"You are a compliance validator. Check if the following artifact "
                f"complies with this rule.\n\n"
                f"Rule: {rule.title}\n"
                f"Description: {rule.description}\n"
                f"Guidelines:\n"
                + "\n".join(f"- {g}" for g in rule.guidelines)
                + f"\n\nArtifact:\n{content[:3000]}\n\n"
                f"Respond with ONLY 'PASS' if compliant, or 'FAIL: <reason>' if not."
            )
            response = await self.llm_client.generate(
                prompt,
                system_prompt="You are a strict compliance validation agent. Be concise.",
            )

            if response.strip().upper().startswith("FAIL"):
                reason = response.strip()[5:].strip(": ").strip()
                return Violation(
                    sop_id=sop.id,
                    sop_title=sop.title if sop.title else sop.name,
                    check_type="rule",
                    description=reason or f"Failed rule: {rule.title}",
                    remediation_hint=sop.remediation_hints.get(
                        rule.id, f"Address rule: {rule.title}"
                    ),
                )
        except Exception as e:
            logger.error(
                "ValidationAgent: error checking SOP rule '%s' — %s", rule.title, e
            )
        return None

    # ------------------------------------------------------------------
    # Policy validation
    # ------------------------------------------------------------------

    async def _validate_policies(
        self, state: Dict[str, Any], stage: str, stage_output: str
    ) -> tuple[List[PolicyViolation], List[Violation]]:
        """Validate stage output against applicable policies from the policy bundle.

        Returns:
            Tuple of (blocking_policy_violations, warning_violations).
        """
        blocking: List[PolicyViolation] = []
        warnings: List[Violation] = []

        policy_bundle_data = state.get("policy_bundle")
        if not policy_bundle_data:
            logger.info(
                "ValidationAgent: no policy_bundle in state, skipping policy validation"
            )
            return blocking, warnings

        try:
            effective_set = EffectivePolicySet.model_validate(policy_bundle_data)
        except Exception as e:
            logger.error(
                "ValidationAgent: failed to parse policy_bundle — %s", e
            )
            return blocking, warnings

        # Filter policies by stage categories
        applicable_categories = STAGE_CATEGORY_MAP.get(stage.lower(), [])
        applicable_policies: List[ResolvedPolicy] = []
        for cat in applicable_categories:
            policy = effective_set.policies_by_category.get(cat)
            if policy:
                applicable_policies.append(policy)

        if not applicable_policies:
            logger.info(
                "ValidationAgent: no applicable policies for stage '%s'", stage
            )
            return blocking, warnings

        for policy in applicable_policies:
            violation = await self._check_policy(policy, stage_output)
            if violation:
                blocking.append(violation)

        return blocking, warnings

    async def _check_policy(
        self, policy: ResolvedPolicy, content: str
    ) -> PolicyViolation | None:
        """Check stage output against a single resolved policy using LLM analysis."""
        policy_content = policy.content
        if isinstance(policy_content, (dict, list)):
            import json
            policy_content = json.dumps(policy_content, indent=2)

        try:
            prompt = (
                f"You are a governance compliance validator. Check if the following "
                f"artifact complies with this policy.\n\n"
                f"Policy: {policy.name}\n"
                f"Category: {policy.category}\n"
                f"Policy Content:\n{str(policy_content)[:3000]}\n\n"
                f"Artifact:\n{content[:3000]}\n\n"
                f"Respond with ONLY 'PASS' if compliant, or "
                f"'FAIL: <rule_violated> | <remediation_hint>' if not."
            )
            response = await self.llm_client.generate(
                prompt,
                system_prompt="You are a strict governance compliance validator. Be concise.",
            )

            if response.strip().upper().startswith("FAIL"):
                parts = response.strip()[5:].strip(": ").split("|", 1)
                rule_violated = parts[0].strip() if parts else "Policy non-compliance"
                hint = parts[1].strip() if len(parts) > 1 else None
                return PolicyViolation(
                    policy_name=policy.name,
                    rule_violated=rule_violated,
                    remediation_hint=hint,
                )
        except Exception as e:
            logger.error(
                "ValidationAgent: error checking policy '%s' — %s", policy.name, e
            )
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_stage_output(state: Dict[str, Any], stage: str) -> str:
        """Extract the relevant output content from state for the given stage.

        Looks for stage-specific keys in state and serializes to string for
        validation.
        """
        import json

        # Map stage names to state keys that hold their output
        stage_output_keys: Dict[str, List[str]] = {
            "idea": ["vision", "idea"],
            "feature": ["features", "candidate_features"],
            "story": ["stories"],
            "stories": ["stories"],
            "architecture": ["architecture", "domain_model"],
            "code": ["scaffolding"],
            "tests": ["scaffolding"],
            "deploy": ["deployment_url"],
        }

        keys = stage_output_keys.get(stage.lower(), [])
        parts: List[str] = []
        for key in keys:
            value = state.get(key)
            if value:
                if isinstance(value, (dict, list)):
                    parts.append(json.dumps(value, indent=2, default=str))
                else:
                    parts.append(str(value))

        return "\n\n".join(parts)

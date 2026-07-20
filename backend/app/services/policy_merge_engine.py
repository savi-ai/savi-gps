"""Policy Merge Engine - Resolves effective policy sets across Global, Tenant, and Project levels."""
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.core.database import Policy, PolicyVersion
from app.core.models import EffectivePolicySet, ResolvedPolicy
from app.core.logger import logger


# Stage-to-category mapping from the design document
STAGE_CATEGORY_MAP: Dict[str, List[str]] = {
    "idea": ["ideation"],
    "feature": ["requirements", "features"],
    "story": ["stories"],
    "architecture": ["architecture", "infrastructure"],
    "code": ["coding", "security", "building_blocks"],
    "tests": ["testing"],
    "deploy": ["infrastructure", "security"],
}

# Priority ordering: higher index = higher priority
LEVEL_PRIORITY = {"global": 0, "tenant": 1, "project": 2}


class PolicyMergeEngine:
    """Resolves the Effective Policy Set for a project by merging policies across levels.

    Merge strategy: Project > Tenant > Global, per category.
    Conflicts at the same level are resolved by most recently updated policy.
    """

    def __init__(self, db: Session):
        self.db = db

    def resolve_effective_policies(
        self, tenant_id: str, project_id: str
    ) -> EffectivePolicySet:
        """Query Global, Tenant, and Project policies and merge by category.

        Only active policies are considered. For each category the highest-priority
        level wins (Project > Tenant > Global). Within the same level, the most
        recently updated policy wins.

        Args:
            tenant_id: The tenant identifier.
            project_id: The project identifier.

        Returns:
            EffectivePolicySet with policies keyed by category.
        """
        from datetime import datetime

        # Fetch all candidate active policies in a single query
        policies = (
            self.db.query(Policy)
            .filter(
                Policy.status == "active",
                (
                    # Global policies (level="global")
                    (Policy.level == "global")
                    # Tenant policies matching tenant_id
                    | ((Policy.level == "tenant") & (Policy.tenant_id == tenant_id))
                    # Project policies matching project_id
                    | (
                        (Policy.level == "project")
                        & (Policy.project_id == project_id)
                    )
                ),
            )
            .order_by(desc(Policy.updated_at))
            .all()
        )

        # Merge by category with priority resolution
        policies_by_category: Dict[str, ResolvedPolicy] = {}

        for policy in policies:
            category = policy.category.lower() if policy.category else ""
            level = policy.level or "tenant"

            current_priority = LEVEL_PRIORITY.get(level, 0)

            # Resolve version content
            content = self._get_policy_content(policy)

            candidate = ResolvedPolicy(
                policy_id=policy.id,
                name=policy.name,
                category=category,
                level=level,
                content=content,
                version=self._get_version_number(policy),
                updated_at=policy.updated_at,
            )

            if category not in policies_by_category:
                policies_by_category[category] = candidate
            else:
                existing = policies_by_category[category]
                existing_priority = LEVEL_PRIORITY.get(existing.level, 0)

                if current_priority > existing_priority:
                    # Higher-level policy wins
                    policies_by_category[category] = candidate
                elif current_priority == existing_priority:
                    # Same level: most recently updated wins
                    if (
                        candidate.updated_at
                        and existing.updated_at
                        and candidate.updated_at > existing.updated_at
                    ):
                        logger.warning(
                            "Policy conflict at level '%s' for category '%s': "
                            "using '%s' (updated %s) over '%s' (updated %s)",
                            level,
                            category,
                            candidate.name,
                            candidate.updated_at,
                            existing.name,
                            existing.updated_at,
                        )
                        policies_by_category[category] = candidate

        return EffectivePolicySet(
            policies_by_category=policies_by_category,
            tenant_id=tenant_id,
            project_id=project_id,
            resolved_at=datetime.now(),
        )

    def filter_by_stage(
        self, effective_set: EffectivePolicySet, stage: str
    ) -> List[ResolvedPolicy]:
        """Filter the effective set to only policies applicable to the given stage.

        Uses STAGE_CATEGORY_MAP to determine which categories apply.

        Args:
            effective_set: The resolved EffectivePolicySet.
            stage: The workflow stage name (e.g. "idea", "code", "deploy").

        Returns:
            List of ResolvedPolicy objects applicable to the stage.
        """
        applicable_categories = STAGE_CATEGORY_MAP.get(stage.lower(), [])
        result: List[ResolvedPolicy] = []

        for cat in applicable_categories:
            policy = effective_set.policies_by_category.get(cat)
            if policy:
                result.append(policy)

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_policy_content(self, policy: Policy):
        """Extract content from the policy's active version, falling back to description."""
        if policy.active_version_id:
            version = (
                self.db.query(PolicyVersion)
                .filter(PolicyVersion.id == policy.active_version_id)
                .first()
            )
            if version and version.content:
                return version.content
        return policy.description or ""

    def _get_version_number(self, policy: Policy) -> Optional[str]:
        """Get the version number string from the active version."""
        if policy.active_version_id:
            version = (
                self.db.query(PolicyVersion)
                .filter(PolicyVersion.id == policy.active_version_id)
                .first()
            )
            if version:
                return version.version_number
        return None

"""Savi action policy gate (T6) — merge/deploy denied in V1."""
from __future__ import annotations

from typing import FrozenSet

# Coordination + work allowed; merge/deploy human-gated (PRD §8 / plan T6).
ALLOWED_ACTIONS: FrozenSet[str] = frozenset(
    {
        "read_context",
        "assemble_context",
        "plan",
        "code",
        "test",
        "open_pr",
        "comment_jira",
        "transition_jira_in_review",
        "post_slack",
        "ask_slack",
        "fetch_confluence",
        "poll_pr_feedback",
        "iterate_code",
    }
)

DENIED_ACTIONS: FrozenSet[str] = frozenset(
    {
        "merge_pr",
        "merge",
        "deploy",
        "deploy_prod",
        "close_incident",
        "spend_cloud",
        "push_main",
        "force_push",
    }
)


class SaviPolicyDenied(PermissionError):
    """Raised when Savi attempts a human-gated action."""


def assert_savi_action_allowed(action: str) -> None:
    key = (action or "").strip().lower()
    if key in DENIED_ACTIONS:
        raise SaviPolicyDenied(
            f"Savi policy denies '{key}' in V1 — merge/deploy stay human-gated "
            "(open a PR instead; a human merges)."
        )
    if key and key not in ALLOWED_ACTIONS:
        # Unknown actions: deny by default (fail closed for Savi execution)
        raise SaviPolicyDenied(
            f"Savi policy: unknown action '{key}' is not on the allow-list"
        )

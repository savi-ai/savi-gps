"""Default GPS policy content for Savi Teammate governance (Phase B1)."""
from __future__ import annotations

SAVI_GOV_POLICY_KEY = "SAVI-GOV-001"
SAVI_GOV_CATEGORY = "governance"
SAVI_GOV_TAG = "savi-teammate"

DEFAULT_SAVI_GOV_POLICY_CONTENT = {
    "version": "1.0.0",
    "summary": (
        "Savi Teammate V1/Beta: coordination and work actions are allowed; "
        "merge and deploy stay human-gated."
    ),
    "enforcement": {
        "runtime_module": "app.services.savi_policy_gate",
        "fail_closed_unknown_actions": True,
    },
    "allowed_actions": [
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
    ],
    "denied_actions": [
        "merge_pr",
        "merge",
        "deploy",
        "deploy_prod",
        "close_incident",
        "spend_cloud",
        "push_main",
        "force_push",
    ],
    "notes": [
        "Savi opens PRs only; humans merge.",
        "Runtime deny is enforced by savi_policy_gate regardless of this document.",
        "This policy exists for admin visibility and future GPS policy-engine hooks.",
    ],
}

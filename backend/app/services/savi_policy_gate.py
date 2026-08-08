"""Savi action policy gate (T6 + ADR 0010 §5c) — fail closed; submit + apply."""
from __future__ import annotations

from typing import FrozenSet, Optional

from sqlalchemy.orm import Session

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
        "submit_job",
        "apply_side_effect",
        "approve_work",
        "cancel_run",
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
    """Raised when Savi attempts a human-gated or disallowed action."""


def assert_savi_action_allowed(action: str) -> None:
    """Static allowlist gate — unknown/denied ⇒ fail closed."""
    key = (action or "").strip().lower()
    if key in DENIED_ACTIONS:
        raise SaviPolicyDenied(
            f"Savi policy denies '{key}' in V1 — merge/deploy stay human-gated "
            "(open a PR instead; a human merges)."
        )
    if key and key not in ALLOWED_ACTIONS:
        raise SaviPolicyDenied(
            f"Savi policy: unknown action '{key}' is not on the allow-list"
        )


def assert_savi_submit_allowed(
    db: Optional[Session],
    *,
    tenant_id: str,
    team_id: str,
    savi_id: str,
    action: str = "submit_job",
) -> None:
    """Gate at job submit (ADR 0010 §5c) — seat must be usable; fail closed on errors."""
    try:
        assert_savi_action_allowed(action)
        _assert_seat_and_team(db, tenant_id=tenant_id, team_id=team_id, savi_id=savi_id)
    except SaviPolicyDenied:
        raise
    except Exception as e:
        raise SaviPolicyDenied(
            f"Policy submit gate failed closed: {e}"
        ) from e


def assert_savi_apply_allowed(
    db: Optional[Session],
    *,
    tenant_id: str,
    team_id: str,
    savi_id: str,
    action: str,
    cancel_requested: bool = False,
) -> None:
    """
    Re-check immediately before irreversible side effects (ADR 0010 §5c TOCTOU).
    Fail closed if policy/seat check errors or kill switch is set.
    """
    try:
        if cancel_requested:
            raise SaviPolicyDenied("Kill switch: cancel_requested — apply denied")
        assert_savi_action_allowed(action)
        assert_savi_action_allowed("apply_side_effect")
        _assert_seat_and_team(db, tenant_id=tenant_id, team_id=team_id, savi_id=savi_id)
    except SaviPolicyDenied:
        raise
    except Exception as e:
        raise SaviPolicyDenied(
            f"Policy apply gate failed closed: {e}"
        ) from e


def _assert_seat_and_team(
    db: Optional[Session],
    *,
    tenant_id: str,
    team_id: str,
    savi_id: str,
) -> None:
    if db is None:
        return
    from app.core.database import SaviInstance, SaviCodingAgentSeat

    savi = (
        db.query(SaviInstance)
        .filter(
            SaviInstance.id == savi_id,
            SaviInstance.tenant_id == tenant_id,
            SaviInstance.team_id == team_id,
        )
        .first()
    )
    if not savi:
        raise SaviPolicyDenied("Savi instance not found for team — deny")

    # If a seat row exists and is explicitly disabled, deny apply/submit
    seat = (
        db.query(SaviCodingAgentSeat)
        .filter(
            SaviCodingAgentSeat.savi_instance_id == savi_id,
            SaviCodingAgentSeat.tenant_id == tenant_id,
        )
        .first()
    )
    if seat and (seat.status or "").lower() == "disabled":
        raise SaviPolicyDenied("Coding-agent seat is disabled — deny")

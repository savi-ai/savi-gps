"""Build fix-plan markdown from assessment findings (W8 fix track).

The agent-facing plan is derived from the same payload written to
``brief/findings.json`` — actionable work items, not a modernization brief.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def assessment_to_findings(assessment: Dict[str, Any]) -> Dict[str, Any]:
    """Same shape as ``brief/findings.json`` for fix execution."""
    return {
        "assessment_run_id": assessment.get("assessed_at")
        or assessment.get("assessment_run_id"),
        "signals": assessment.get("signals") or [],
        "policy_gaps": assessment.get("policy_gaps") or [],
        "synthesis": assessment.get("synthesis") or {},
        "recommended_plan_type": assessment.get("recommended_plan_type"),
        "recommendation_reason": assessment.get("recommendation_reason"),
    }


def _gap_signals(signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Prefer simple_fix / either gaps; include modernization only if no fix-scoped gaps."""
    gaps = [s for s in signals if s.get("status") in ("bad", "warn")]
    fixish = [
        s
        for s in gaps
        if (s.get("remediation_scope") or "either") in ("simple_fix", "either")
    ]
    if fixish:
        return fixish
    return gaps


def _work_item_title(signal: Dict[str, Any]) -> str:
    rec = (signal.get("recommendation") or "").strip()
    if rec:
        # Keep first sentence / line as the checkbox title
        return rec.split("\n")[0].split(". ")[0][:160]
    label = signal.get("label") or signal.get("id") or "Signal"
    value = signal.get("value") or ""
    return f"Address {label}" + (f" ({value})" if value else "")


def render_fix_plan_md(
    title: str,
    findings: Dict[str, Any],
    *,
    assessment: Optional[Dict[str, Any]] = None,
) -> str:
    """Render an agent-executable fix plan from findings.json-shaped data."""
    assessment = assessment or {}
    signals = findings.get("signals") or []
    gaps = _gap_signals(signals)
    policy_gaps = findings.get("policy_gaps") or []
    synth = findings.get("synthesis") or {}

    lines: List[str] = [
        f"# {title}",
        "",
        "This is a **repository fix plan**. Agents apply minimal, safe patches in "
        "`source/` and open a PR on the **same** repository.",
        "",
        "## Execution stages",
        "1. Fix — lock remediation scope from findings",
        "2. Code — implement patches in the member repo checkout",
        "3. Test — run / add verification",
        "4. Push — push branch to the same remote",
        "5. PR — open pull request",
        "",
    ]

    narrative = synth.get("narrative")
    if narrative:
        lines.extend(
            [
                "## Context (from assessment)",
                narrative.strip()[:2000],
                "",
            ]
        )

    lines.append("## Work items (from findings)")
    if not gaps and not policy_gaps:
        lines.append("- [ ] Review findings — no bad/warn signals; confirm no-op or light hygiene")
    else:
        for sig in gaps:
            scope = sig.get("remediation_scope") or "either"
            status = sig.get("status") or "?"
            lines.append(f"- [ ] {_work_item_title(sig)}")
            detail = sig.get("detail") or ""
            value = sig.get("value") or ""
            bits = [f"signal `{sig.get('id')}`", f"status={status}", f"scope={scope}"]
            if value:
                bits.append(f"value={value}")
            lines.append(f"  - {' · '.join(bits)}")
            if detail:
                lines.append(f"  - {detail[:300]}")
        for gap in policy_gaps:
            msg = gap.get("message") or gap.get("rule_id") or "Policy gap"
            lines.append(f"- [ ] Resolve policy: {msg}")
            if gap.get("policy_name"):
                lines.append(f"  - policy={gap['policy_name']}")
    lines.append("")

    # Explicit out-of-scope for fix track (modernization themes)
    modernize_gaps = [
        s
        for s in signals
        if s.get("status") in ("bad", "warn")
        and (s.get("remediation_scope") or "") == "modernization"
    ]
    if modernize_gaps and gaps != modernize_gaps:
        lines.append("## Out of scope for this fix plan")
        lines.append(
            "Defer these to an application **modernize** plan (new target repos / architecture):"
        )
        for sig in modernize_gaps:
            lines.append(
                f"- {sig.get('label') or sig.get('id')}: {sig.get('value')} "
                f"({sig.get('status')})"
            )
        lines.append("")

    recs = synth.get("prioritized_recommendations") or []
    if recs:
        # Keep recommendations that match fix work items when possible
        gap_ids = {s.get("id") for s in gaps}
        lines.append("## Guidance")
        for r in recs[:8]:
            lines.append(f"- {r}")
        if gap_ids:
            lines.append("")
        else:
            lines.append("")

    effort = assessment.get("agent_effort") or {}
    if effort:
        lines.append("## Agent effort (indicative)")
        lines.append(
            f"- Band: **{effort.get('band')}** · "
            f"**{effort.get('estimated_agent_hours')}** agent-hours "
            f"(confidence: {effort.get('confidence')})"
        )
        lines.append(
            f"- _{effort.get('disclaimer') or 'Agent effort ≠ calendar developer weeks'}_"
        )
        lines.append(
            "- Prefer Fix→Code→Test→Push→PR effort; Requirements/Architecture stages "
            "do not apply to fix plans."
        )
        lines.append("")

    lines.extend(
        [
            "## Agent rules",
            "- Edit existing files in `source/`; do not scaffold a greenfield app",
            "- Prefer small patches (config, CI, tests, dependency bumps) over rewrites",
            "- Skip work items that require new repositories or major architecture changes",
            "- Push and PR target the **same** connected member repository",
            "",
        ]
    )
    return "\n".join(lines)

"""Assessment synthesis + agent-effort estimation.

Rules / Analysis Config signals remain the score source of truth.
This module adds:
  - Deterministic agent_effort (always)
  - Optional LLM narrative + effort refinement (Run assessment / Create plan only)

Agent effort = orchestration effort for Savi agents (Requirements→Push),
NOT calendar developer weeks.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import re
import time
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import Repository, RepositoryWikiSite
from app.core.llm_audit import log_llm_call
from app.core.logger import logger
from app.services.llm_routing import get_other_llm_client, resolve_other_llm
from app.services.modernize.spawn_build_service import _wiki_excerpt

DISCLAIMER = "Agent effort ≠ calendar developer weeks — estimates Savi agent orchestration time for Requirements → Tasks → Code → Test → Push."

STAGES = ("requirements", "tasks", "code", "test", "push")
# Share of total agent hours by pipeline stage
_STAGE_SHARES = {
    "requirements": 0.12,
    "tasks": 0.13,
    "code": 0.40,
    "test": 0.25,
    "push": 0.10,
}


def _parse_json_object(raw: str) -> Optional[Dict[str, Any]]:
    cleaned = (raw or "").strip()
    if not cleaned:
        return None
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _band_for_hours(hours: float) -> str:
    if hours <= 8:
        return "S"
    if hours <= 24:
        return "M"
    if hours <= 60:
        return "L"
    return "XL"


def _run_coro_sync(coro):
    """Run async LLM from sync assessment path (FastAPI may already have a loop)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=120)


def estimate_agent_effort_heuristic(readiness: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic effort from overall score + signal statuses."""
    score = int(readiness.get("overall_score") or 50)
    signals = readiness.get("signals") or []
    level = (readiness.get("readiness_level") or "medium").lower()

    # Base: lower readiness → more agent hours
    base = max(4.0, (100 - score) * 0.55)
    bad = sum(
        1 for s in signals if s.get("status") == "bad" and s.get("applicable", True)
    )
    warn = sum(
        1 for s in signals if s.get("status") == "warn" and s.get("applicable", True)
    )
    weight_penalty = 0.0
    for s in signals:
        if not s.get("applicable", True) or s.get("status") == "na":
            continue
        w = float(s.get("weight") or 1)
        if s.get("status") == "bad":
            weight_penalty += 2.5 * w
        elif s.get("status") == "warn":
            weight_penalty += 1.0 * w

    level_mult = {"high": 0.75, "medium": 1.0, "low": 1.35}.get(level, 1.0)
    total = round((base + bad * 3.0 + warn * 1.5 + weight_penalty) * level_mult, 1)
    total = max(4.0, min(total, 120.0))

    stages: List[Dict[str, Any]] = []
    for stage in STAGES:
        share = _STAGE_SHARES[stage]
        h = round(total * share, 1)
        note = {
            "requirements": "Clarify target stack and acceptance from signals/wiki",
            "tasks": "Decompose modernization work into agent-executable tasks",
            "code": "Implement migrations, dependency upgrades, refactors",
            "test": "Generate/run verification against acceptance criteria",
            "push": "Open PR / push to configured target remote",
        }[stage]
        stages.append({"stage": stage, "agent_hours": h, "notes": note})

    assumptions = [
        "Single repository scope unless application roll-up says otherwise",
        "Target stack and playbook (if any) are already chosen or lightly guided",
        "CI / test harness exists enough for agent verification loops",
        DISCLAIMER,
    ]
    if bad >= 3:
        assumptions.append(f"{bad} critical signals may require extra exploration passes")

    confidence = "high" if score >= 70 and bad <= 1 else "medium" if score >= 40 else "low"

    return {
        "band": _band_for_hours(total),
        "estimated_agent_hours": total,
        "purpose": (
            "Estimated Savi agent orchestration time to run Requirements → Tasks → Code → "
            "Test → Push if you create a modernization or fix plan."
        ),
        "stage_breakdown": stages,
        "confidence": confidence,
        "assumptions": assumptions,
        "disclaimer": DISCLAIMER,
        "source": "heuristic",
    }


def _heuristic_narrative(readiness: Dict[str, Any]) -> Dict[str, Any]:
    score = readiness.get("overall_score")
    level = readiness.get("readiness_level")
    signals = readiness.get("signals") or []
    weak = [s for s in signals if s.get("status") in ("bad", "warn")]
    weak.sort(key=lambda s: (0 if s.get("status") == "bad" else 1, -(s.get("weight") or 1)))

    recs: List[str] = []
    for s in weak[:8]:
        rec = s.get("recommendation") or f"Address {s.get('label')}: {s.get('value')}"
        recs.append(rec)

    risks = []
    for s in weak[:5]:
        if s.get("status") == "bad":
            risks.append(f"{s.get('label')}: {s.get('detail') or s.get('value')}")

    name = readiness.get("repository_name") or readiness.get("application_name") or "this codebase"
    narrative = (
        f"{name} scores {score}/100 ({level} readiness). "
        f"{len([s for s in signals if s.get('status') == 'bad'])} critical and "
        f"{len([s for s in signals if s.get('status') == 'warn'])} warning signals "
        "drive the modernization priority. "
        "Use Analysis Config–backed recommendations below; agent effort is estimated for Savi orchestration, not human calendar weeks."
    )
    return {
        "narrative": narrative,
        "prioritized_recommendations": recs,
        "risks": risks,
        "source": "heuristic",
    }


def _compact_signals(signals: List[Dict[str, Any]], limit: int = 24) -> List[Dict[str, Any]]:
    out = []
    for s in signals:
        if not s.get("applicable", True) or s.get("status") == "na":
            continue
        out.append(
            {
                "id": s.get("id"),
                "label": s.get("label"),
                "value": s.get("value"),
                "score": s.get("score"),
                "status": s.get("status"),
                "recommendation": s.get("recommendation"),
                "weight": s.get("weight"),
            }
        )
        if len(out) >= limit:
            break
    return out


async def _llm_synthesize(
    *,
    db: Session,
    tenant_id: str,
    readiness: Dict[str, Any],
    wiki_excerpt: str,
    entity_type: str,
    entity_id: str,
    heuristic_effort: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    routing = resolve_other_llm(db, tenant_id)
    provider = routing.get("provider") or "claude"
    model = routing.get("model")

    # Skip providers that need keys we clearly don't have / CLI-only
    if provider in ("claude", "anthropic"):
        from app.core.config import settings

        if not settings.ANTHROPIC_API_KEY:
            logger.info("Assessment LLM synthesis skipped: no ANTHROPIC_API_KEY")
            return None
    if provider == "openai":
        from app.core.config import settings

        if not settings.OPENAI_API_KEY:
            return None

    system = (
        "You are a modernization assessment synthesizer for Savi GPS. "
        "Scores and signals are already computed from Analysis Config rules — do not invent new scores. "
        "Return ONLY valid JSON with keys: narrative (string), prioritized_recommendations (string[]), "
        "risks (string[]), agent_effort_adjustment (object with optional estimated_agent_hours number "
        "and optional stage_hours map for requirements/tasks/code/test/push), assumptions (string[]). "
        "Agent effort is Savi agent orchestration hours, NOT human developer weeks. "
        "Keep narrative under 180 words. Ground claims in the provided signals and wiki excerpt."
    )
    payload = {
        "overall_score": readiness.get("overall_score"),
        "readiness_level": readiness.get("readiness_level"),
        "signals": _compact_signals(readiness.get("signals") or []),
        "heuristic_agent_effort": {
            "band": heuristic_effort.get("band"),
            "estimated_agent_hours": heuristic_effort.get("estimated_agent_hours"),
            "stage_breakdown": heuristic_effort.get("stage_breakdown"),
        },
        "wiki_excerpt": (wiki_excerpt or "")[:3500],
    }
    prompt = (
        "Synthesize a modernization assessment narrative and refine agent-effort if needed.\n"
        f"INPUT:\n{json.dumps(payload, indent=2)}\n"
    )

    t0 = time.monotonic()
    try:
        client = get_other_llm_client(db, tenant_id)
        raw = await client.generate(
            prompt,
            system_prompt=system,
            temperature=0.2,
            max_tokens=2000,
        )
        duration_ms = int((time.monotonic() - t0) * 1000)
        parsed = _parse_json_object(raw)
        if not parsed:
            log_llm_call(
                purpose="assessment_synthesis",
                provider=provider,
                model=model,
                tenant_id=tenant_id,
                entity_type=entity_type,
                entity_id=entity_id,
                status="parse_error",
                duration_ms=duration_ms,
            )
            return None
        log_llm_call(
            purpose="assessment_synthesis",
            provider=provider,
            model=model,
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            status="ok",
            duration_ms=duration_ms,
            extra={"hours": parsed.get("agent_effort_adjustment")},
        )
        return parsed
    except Exception as e:
        duration_ms = int((time.monotonic() - t0) * 1000)
        log_llm_call(
            purpose="assessment_synthesis",
            provider=provider,
            model=model,
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            status="error",
            duration_ms=duration_ms,
            error=str(e),
        )
        logger.warning("Assessment LLM synthesis failed: %s", e)
        return None


def _merge_llm_into_effort(
    heuristic: Dict[str, Any],
    llm: Dict[str, Any],
) -> Dict[str, Any]:
    effort = dict(heuristic)
    adj = llm.get("agent_effort_adjustment") or {}
    hours = adj.get("estimated_agent_hours")
    if isinstance(hours, (int, float)) and hours > 0:
        # Clamp LLM adjustment to 0.5x–2x of heuristic
        base = float(heuristic.get("estimated_agent_hours") or hours)
        clamped = max(base * 0.5, min(float(hours), base * 2.0))
        clamped = max(4.0, min(round(clamped, 1), 120.0))
        effort["estimated_agent_hours"] = clamped
        effort["band"] = _band_for_hours(clamped)

        stage_hours = adj.get("stage_hours") if isinstance(adj.get("stage_hours"), dict) else None
        if stage_hours:
            stages = []
            for stage in STAGES:
                h = stage_hours.get(stage)
                if not isinstance(h, (int, float)):
                    h = clamped * _STAGE_SHARES[stage]
                stages.append(
                    {
                        "stage": stage,
                        "agent_hours": round(float(h), 1),
                        "notes": next(
                            (
                                s["notes"]
                                for s in (heuristic.get("stage_breakdown") or [])
                                if s.get("stage") == stage
                            ),
                            "",
                        ),
                    }
                )
            effort["stage_breakdown"] = stages
        else:
            # Re-split total
            effort["stage_breakdown"] = [
                {
                    "stage": stage,
                    "agent_hours": round(clamped * _STAGE_SHARES[stage], 1),
                    "notes": next(
                        (
                            s["notes"]
                            for s in (heuristic.get("stage_breakdown") or [])
                            if s.get("stage") == stage
                        ),
                        "",
                    ),
                }
                for stage in STAGES
            ]

    assumptions = list(effort.get("assumptions") or [])
    for a in llm.get("assumptions") or []:
        if isinstance(a, str) and a not in assumptions:
            assumptions.append(a)
    if DISCLAIMER not in assumptions:
        assumptions.append(DISCLAIMER)
    effort["assumptions"] = assumptions
    effort["source"] = "heuristic+llm"
    effort["disclaimer"] = DISCLAIMER
    return effort


def _wiki_excerpt_for_repo(db: Session, repository: Repository) -> str:
    site = (
        db.query(RepositoryWikiSite)
        .filter(RepositoryWikiSite.repository_id == repository.id)
        .first()
    )
    wiki_json = site.summary_json if site and isinstance(site.summary_json, dict) else None
    return _wiki_excerpt(wiki_json, max_chars=3500)


def enrich_assessment(
    db: Session,
    readiness: Dict[str, Any],
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    repository: Optional[Repository] = None,
    use_llm: bool = True,
    wiki_excerpt: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach synthesis + agent_effort onto a readiness payload (mutates copy)."""
    out = dict(readiness)
    heuristic = estimate_agent_effort_heuristic(out)
    synth = _heuristic_narrative(out)

    if use_llm:
        excerpt = wiki_excerpt
        if excerpt is None and repository is not None:
            excerpt = _wiki_excerpt_for_repo(db, repository)
        excerpt = excerpt or ""

        async def _call():
            return await _llm_synthesize(
                db=db,
                tenant_id=tenant_id,
                readiness=out,
                wiki_excerpt=excerpt,
                entity_type=entity_type,
                entity_id=entity_id,
                heuristic_effort=heuristic,
            )

        try:
            llm_result = _run_coro_sync(_call())
        except Exception as e:
            logger.warning("Assessment synthesis coroutine failed: %s", e)
            llm_result = None

        if llm_result:
            if isinstance(llm_result.get("narrative"), str) and llm_result["narrative"].strip():
                synth["narrative"] = llm_result["narrative"].strip()
            if isinstance(llm_result.get("prioritized_recommendations"), list):
                recs = [r for r in llm_result["prioritized_recommendations"] if isinstance(r, str)]
                if recs:
                    synth["prioritized_recommendations"] = recs
            if isinstance(llm_result.get("risks"), list):
                risks = [r for r in llm_result["risks"] if isinstance(r, str)]
                if risks:
                    synth["risks"] = risks
            synth["source"] = "llm"
            heuristic = _merge_llm_into_effort(heuristic, llm_result)

    out["synthesis"] = synth
    out["agent_effort"] = heuristic
    return out

"""Policy-aware modernization readiness — load tenant rules and overlay scores.

Machine-readable rules live in PolicyVersion.content under category ``modernize``
(or tag ``modernize-readiness``). Heuristic signals still run first; violated
rules clamp scores and attach failed-policy metadata for the UI / spawn brief.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import Policy, PolicyVersion
from app.core.logger import logger

MODERNIZE_CATEGORY = "modernize"
MODERNIZE_TAG = "modernize-readiness"
FAIL_SCORE = 25  # clamp when a hard rule fails


@dataclass
class LoadedModernizePolicy:
    policy_db_id: str
    policy_key: str
    name: str
    version_id: str
    version_number: str
    content: Dict[str, Any]


@dataclass
class PolicyGap:
    signal_id: str
    policy_name: str
    policy_version_id: str
    rule_id: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "policy_name": self.policy_name,
            "policy_version_id": self.policy_version_id,
            "rule_id": self.rule_id,
            "message": self.message,
        }


def _content_as_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return {}


def _has_modernize_tag(tags: Optional[Sequence[str]]) -> bool:
    if not tags:
        return False
    needle = MODERNIZE_TAG.lower()
    return any(str(t).lower() == needle or str(t).lower() == "modernize" for t in tags)


def load_modernize_policies(db: Session, tenant_id: Optional[str]) -> List[LoadedModernizePolicy]:
    """Active global + tenant policies that define readiness rules."""
    query = db.query(Policy).filter(Policy.status == "active")
    if tenant_id:
        query = query.filter(
            or_(
                Policy.level == "global",
                Policy.tenant_id == tenant_id,
            )
        )
    else:
        query = query.filter(Policy.level == "global")

    rows = query.order_by(Policy.updated_at.desc()).all()
    loaded: List[LoadedModernizePolicy] = []

    for policy in rows:
        if (policy.category or "").lower() != MODERNIZE_CATEGORY and not _has_modernize_tag(
            policy.tags
        ):
            continue
        if not policy.active_version_id:
            continue
        version = (
            db.query(PolicyVersion)
            .filter(PolicyVersion.id == policy.active_version_id)
            .first()
        )
        if not version:
            continue
        content = _content_as_dict(version.content)
        rules = content.get("rules")
        if not isinstance(rules, list) or not rules:
            # Allow readiness_rules alias
            rules = content.get("readiness_rules")
        if not isinstance(rules, list) or not rules:
            continue
        content = {**content, "rules": rules}
        loaded.append(
            LoadedModernizePolicy(
                policy_db_id=policy.id,
                policy_key=policy.policy_id,
                name=policy.name,
                version_id=version.id,
                version_number=version.version_number,
                content=content,
            )
        )
    return loaded


def _parse_java_major(runtime: str) -> Optional[int]:
    text = (runtime or "").lower()
    m = re.search(r"java\s*([0-9]{1,2})", text)
    if m:
        return int(m.group(1))
    m = re.search(r"\b1\.([0-9])\b", text)
    if m:
        # 1.8 → 8
        return int(m.group(1))
    m = re.search(r"jdk[-_ ]?([0-9]{1,2})", text)
    if m:
        return int(m.group(1))
    return None


def _citation_pct(pages: Sequence[Any]) -> int:
    verified = sum(getattr(p, "verified_claim_count", 0) or 0 for p in pages)
    total = sum(getattr(p, "total_claim_count", 0) or 0 for p in pages)
    if not total:
        return 0
    return round((verified / total) * 100)


def _page_slugs(pages: Sequence[Any]) -> set:
    return {getattr(p, "slug", None) for p in pages if getattr(p, "slug", None)}


def evaluate_rule(
    rule: Dict[str, Any],
    *,
    context: Dict[str, Any],
) -> Optional[str]:
    """Return failure message if rule is violated, else None."""
    op = (rule.get("op") or rule.get("type") or "").strip().lower()
    value = rule.get("value")
    fail_message = rule.get("fail_message") or rule.get("message")

    if op in ("runtime_min_java", "min_java"):
        required = int(value)
        major = _parse_java_major(str(context.get("runtime") or ""))
        if major is None:
            return fail_message or f"Java version not detected; policy requires Java ≥ {required}"
        if major < required:
            return fail_message or f"Java {major} below required minimum Java {required}"
        return None

    if op in ("required_wiki_sections", "required_sections"):
        required = [str(s) for s in (value or [])]
        present = context.get("page_slugs") or set()
        missing = [s for s in required if s not in present]
        if missing:
            return fail_message or f"Missing wiki sections: {', '.join(missing)}"
        return None

    if op in ("min_citation_pct", "citation_min"):
        floor = int(value)
        pct = int(context.get("citation_pct") or 0)
        if pct < floor:
            return fail_message or f"Citation coverage {pct}% below policy floor {floor}%"
        return None

    if op in ("min_test_files", "min_tests"):
        floor = int(value)
        count = int(context.get("test_file_count") or 0)
        if count < floor:
            return fail_message or f"Only {count} test file(s); policy requires ≥ {floor}"
        return None

    if op in ("deny_frameworks", "forbidden_frameworks"):
        denied = [str(x).lower() for x in (value or [])]
        frameworks = [str(f).lower() for f in (context.get("frameworks") or [])]
        hits = [d for d in denied if any(d in f for f in frameworks)]
        if hits:
            return fail_message or f"Forbidden framework signal(s): {', '.join(hits)}"
        return None

    if op in ("max_index_age_days", "max_index_age"):
        max_days = int(value)
        age = context.get("index_age_days")
        if age is None:
            return fail_message or "Repository never indexed"
        if float(age) > max_days:
            return fail_message or f"Index age {int(age)}d exceeds policy max {max_days}d"
        return None

    if op in ("min_signal_score",):
        signal_id = rule.get("signal") or "documentation"
        floor = int(value)
        scores = context.get("signal_scores") or {}
        current = scores.get(signal_id)
        if current is None:
            return None
        if int(current) < floor:
            return fail_message or f"Signal {signal_id} score {current} below policy floor {floor}"
        return None

    logger.debug("Unknown modernize readiness rule op=%s", op)
    return None


def apply_modernize_policies(
    *,
    signals: List[Dict[str, Any]],
    policies: List[LoadedModernizePolicy],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Mutate signals with policy failures; return audit payload."""
    by_id = {s["id"]: s for s in signals}
    gaps: List[PolicyGap] = []
    version_ids: List[str] = []
    applied: List[Dict[str, str]] = []

    for policy in policies:
        version_ids.append(policy.version_id)
        applied.append(
            {
                "policy_id": policy.policy_key,
                "policy_name": policy.name,
                "version_id": policy.version_id,
                "version_number": policy.version_number,
            }
        )
        for rule in policy.content.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            signal_id = rule.get("signal") or "documentation"
            # Keep score map fresh for min_signal_score ops
            context["signal_scores"] = {s["id"]: s["score"] for s in signals}
            message = evaluate_rule(rule, context=context)
            if not message:
                continue
            gap = PolicyGap(
                signal_id=str(signal_id),
                policy_name=policy.name,
                policy_version_id=policy.version_id,
                rule_id=str(rule.get("id") or rule.get("op") or "rule"),
                message=message,
            )
            gaps.append(gap)
            signal = by_id.get(signal_id)
            if not signal:
                # Attach to documentation as fallback bucket
                signal = by_id.get("documentation")
                if not signal:
                    continue
                gap.signal_id = signal["id"]
            fail_score = int(rule.get("fail_score", FAIL_SCORE))
            signal["score"] = min(int(signal["score"]), fail_score)
            signal["status"] = "bad"
            failed = list(signal.get("failed_policies") or [])
            failed.append(
                {
                    "policy_name": policy.name,
                    "rule_id": gap.rule_id,
                    "message": message,
                    "policy_version_id": policy.version_id,
                }
            )
            signal["failed_policies"] = failed
            prefix = f"Failed policy: {message}"
            detail = signal.get("detail") or ""
            if prefix not in detail:
                signal["detail"] = f"{prefix}. {detail}".strip()

    overall = round(sum(s["score"] for s in signals) / len(signals)) if signals else 0
    if overall >= 75:
        level = "high"
    elif overall >= 50:
        level = "medium"
    else:
        level = "low"

    return {
        "signals": signals,
        "overall_score": overall,
        "readiness_level": level,
        "policy_version_ids": version_ids,
        "policies_applied": applied,
        "policy_gaps": [g.to_dict() for g in gaps],
    }


DEFAULT_MODERNIZE_POLICY_CONTENT: Dict[str, Any] = {
    "source": "savi_default",
    "title": "Modernization Readiness Standards",
    "description": "Machine-readable rules that clamp readiness signals when violated.",
    "rules": [
        {
            "id": "min_java_17",
            "signal": "runtime",
            "op": "runtime_min_java",
            "value": 17,
            "fail_message": "Java runtime must be ≥ 17 for modernization readiness",
        },
        {
            "id": "required_wiki_sections",
            "signal": "documentation",
            "op": "required_wiki_sections",
            "value": ["overview", "architecture", "api_surface", "build_deploy"],
            "fail_message": "Required wiki sections missing for modernization",
        },
        {
            "id": "citation_floor",
            "signal": "documentation",
            "op": "min_citation_pct",
            "value": 50,
            "fail_message": "Wiki citation coverage must be ≥ 50%",
        },
        {
            "id": "min_test_files",
            "signal": "test_coverage",
            "op": "min_test_files",
            "value": 3,
            "fail_message": "At least 3 test-related files required",
        },
        {
            "id": "max_index_age",
            "signal": "index_freshness",
            "op": "max_index_age_days",
            "value": 30,
            "fail_message": "Index must be refreshed within 30 days",
        },
    ],
}

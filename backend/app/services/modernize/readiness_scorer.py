"""Derive modernization readiness from Analysis Config signals + wiki/index metadata."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import (
    CodeChunk,
    ModernizationPlan,
    Repository,
    RepositoryAnalysisAttribute,
    RepositoryWikiSite,
    WikiPage,
)
from app.services.intelligence.analysis_config_service import (
    AnalysisConfigService,
    normalize_remediation_scope,
)
from app.services.intelligence.analysis_storage import load_analysis_artifacts, resolve_analysis_dir
from app.services.modernize.signal_applicability import is_attribute_applicable


def _signal(
    signal_id: str,
    label: str,
    value: str,
    score: Optional[int],
    status: str,
    detail: str,
    *,
    recommendation: Optional[str] = None,
    source: str = "platform",
    weight: int = 1,
    remediation_scope: Optional[str] = None,
    category: str = "platform",
    applicable: bool = True,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": signal_id,
        "label": label,
        "value": value,
        "score": max(0, min(100, score)) if score is not None else None,
        "status": status,
        "detail": detail,
        "source": source,
        "weight": weight,
        "category": category,
        "applicable": applicable,
    }
    if recommendation:
        out["recommendation"] = recommendation
    if remediation_scope:
        out["remediation_scope"] = normalize_remediation_scope(remediation_scope)
    return out


def recommend_plan_type(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Suggest fix vs modernize from warn/bad signal remediation scopes."""
    fix_w = 0.0
    mod_w = 0.0
    for s in signals:
        if s.get("status") not in ("bad", "warn") or not s.get("applicable", True):
            continue
        w = float(s.get("weight") or 1)
        if s.get("status") == "bad":
            w *= 2.0
        scope = normalize_remediation_scope(s.get("remediation_scope"))
        if scope == "simple_fix":
            fix_w += w
        elif scope == "modernization":
            mod_w += w
        else:
            fix_w += w * 0.5
            mod_w += w * 0.5

    if fix_w == 0 and mod_w == 0:
        return {
            "recommended_plan_type": "both",
            "recommendation_reason": (
                "No high-priority remediation signals — choose a fix plan for in-repo "
                "work or a modernize plan for architecture-led rebuilds."
            ),
        }
    if fix_w > mod_w * 1.25:
        return {
            "recommended_plan_type": "fix",
            "recommendation_reason": (
                "Most gap signals are scoped as simple fixes (same-repo PR)."
            ),
        }
    if mod_w > fix_w * 1.25:
        return {
            "recommended_plan_type": "modernize",
            "recommendation_reason": (
                "Most gap signals indicate modernization themes (runtime/framework/architecture)."
            ),
        }
    return {
        "recommended_plan_type": "both",
        "recommendation_reason": (
            "Signals mix simple fixes and modernization themes — you can create either plan type."
        ),
    }


def _status_for_score(score: int) -> str:
    if score >= 70:
        return "good"
    if score >= 45:
        return "warn"
    return "bad"


def _freshness_score(last_indexed_at: Optional[datetime]) -> tuple[int, str, str]:
    if not last_indexed_at:
        return 0, "Never indexed", "Run indexing before starting a modernization plan."
    age_days = (datetime.now() - last_indexed_at).total_seconds() / 86400
    if age_days <= 7:
        return 100, f"{int(age_days)}d ago", "Index is fresh."
    if age_days <= 30:
        return 75, f"{int(age_days)}d ago", "Consider re-indexing before major changes."
    return 45, f"{int(age_days)}d ago", "Index may be stale — re-index recommended."


def _doc_coverage_score(
    wiki_site: Optional[RepositoryWikiSite],
    pages: List[WikiPage],
) -> tuple[int, str]:
    if not wiki_site and not pages:
        return 0, "No wiki documentation"
    page_count = len(pages)
    verified = sum(p.verified_claim_count or 0 for p in pages)
    total_claims = sum(p.total_claim_count or 0 for p in pages)
    citation_pct = round((verified / total_claims) * 100) if total_claims else 0

    score = 40
    if wiki_site:
        score += 25
    if page_count >= 3:
        score += 20
    elif page_count >= 1:
        score += 10
    if citation_pct >= 50:
        score += 15
    elif citation_pct > 0:
        score += 5

    detail = f"{page_count} wiki pages"
    if wiki_site:
        detail += ", unified wiki site"
    if total_claims:
        detail += f", {citation_pct}% citation coverage"
    return min(100, score), detail


def _drift_score(pages: List[WikiPage]) -> tuple[int, str]:
    if not pages:
        return 50, "No wiki pages to assess drift"
    stale = sum(1 for p in pages if p.drift_status == "stale")
    pending = sum(1 for p in pages if p.drift_status == "pending_review")
    if stale:
        return 30, f"{stale} stale wiki page(s)"
    if pending:
        return 60, f"{pending} page(s) pending review"
    return 90, "No drift detected"


def _test_signal_score(db: Session, repository_id: str) -> tuple[int, str, int]:
    test_paths = (
        db.query(func.count(CodeChunk.id))
        .filter(
            CodeChunk.repository_id == repository_id,
            CodeChunk.file_path.ilike("%test%"),
        )
        .scalar()
        or 0
    )
    if test_paths >= 10:
        return 85, f"{test_paths} test-related files", test_paths
    if test_paths >= 3:
        return 65, f"{test_paths} test-related files", test_paths
    if test_paths >= 1:
        return 45, f"{test_paths} test-related file(s)", test_paths
    return 20, "No test files detected", 0


def _match_any(value_lower: str, needles: Optional[List[Any]]) -> Optional[str]:
    if not needles or not value_lower:
        return None
    for n in needles:
        token = str(n).lower().strip()
        if token and token in value_lower:
            return str(n)
    return None


def _na_attribute_signal(definition: Dict[str, Any], reason: str) -> Dict[str, Any]:
    key = definition.get("key") or "attr"
    label = definition.get("label") or key
    return _signal(
        f"attr:{key}",
        label,
        "Not applicable",
        None,
        "na",
        reason,
        source="analysis_config",
        weight=0,
        category=str(definition.get("category") or "general"),
        applicable=False,
    )


def score_attribute_signal(
    definition: Dict[str, Any],
    value_text: Optional[str],
    *,
    source_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Score one Analysis Config attribute for modernization assessment."""
    rules = definition.get("assessment_rules") or {}
    if not isinstance(rules, dict):
        rules = {}
    label = definition.get("label") or definition.get("key") or "Attribute"
    key = definition.get("key") or "attr"
    weight = int(definition.get("assessment_weight") or 1)
    rec_template = definition.get("recommendation_template")
    scope = normalize_remediation_scope(definition.get("remediation_scope"))

    if not value_text or not str(value_text).strip():
        missing = int(rules.get("missing_score", 40))
        return _signal(
            f"attr:{key}",
            label,
            "Not detected",
            missing,
            _status_for_score(missing),
            "Attribute marked for assessment but not extracted — re-index or refine extraction hint.",
            recommendation=rec_template
            or f"Ensure {label} can be detected from the codebase (update Analysis Config hint).",
            source="analysis_config",
            weight=weight,
            remediation_scope=scope,
        )

    value = str(value_text).strip()
    lower = value.lower()
    detail_bits = [f"Extracted value: {value}"]
    if source_file:
        detail_bits.append(f"Evidence: `{source_file}`")

    legacy_hit = _match_any(lower, rules.get("legacy_contains"))
    warn_hit = _match_any(lower, rules.get("warn_contains"))
    good_hit = _match_any(lower, rules.get("good_contains"))

    if legacy_hit:
        score = int(rules.get("legacy_score", 30))
        detail_bits.append(f"Legacy match: {legacy_hit}")
        rec = rec_template
    elif good_hit and not warn_hit:
        score = int(rules.get("good_score", 90))
        detail_bits.append(f"Supported match: {good_hit}")
        rec = None
    elif warn_hit:
        score = int(rules.get("warn_score", 55))
        detail_bits.append(f"Caution match: {warn_hit}")
        rec = rec_template
    elif good_hit:
        score = int(rules.get("good_score", 85))
        detail_bits.append(f"Supported match: {good_hit}")
        rec = None
    else:
        # Unknown value — neutral/slight caution so tenants still see the signal
        score = int(rules.get("unknown_score", 60))
        detail_bits.append("No legacy/good rule matched — review manually.")
        rec = rec_template

    return _signal(
        f"attr:{key}",
        label,
        value[:80],
        score,
        _status_for_score(score),
        "; ".join(detail_bits),
        recommendation=rec,
        source="analysis_config",
        weight=weight,
        remediation_scope=scope,
        category=str(definition.get("category") or "general"),
        applicable=True,
    )


def _attrs_by_key(
    attrs: List[RepositoryAnalysisAttribute],
) -> Dict[str, RepositoryAnalysisAttribute]:
    by_key: Dict[str, RepositoryAnalysisAttribute] = {}
    for a in attrs:
        key = (a.attribute_key or "").lower()
        if key and key not in by_key:
            by_key[key] = a
    return by_key


def compute_readiness(db: Session, repository: Repository) -> Dict[str, Any]:
    """Build readiness panel JSON — platform signals + Analysis Config–driven signals."""
    from datetime import datetime as dt

    from app.services.modernize.policy_readiness import (
        apply_modernize_policies,
        load_modernize_policies,
    )

    config_svc = AnalysisConfigService(db)
    assessment_defs = config_svc.list_assessment_definitions(repository.tenant_id)

    attrs = (
        db.query(RepositoryAnalysisAttribute)
        .filter(RepositoryAnalysisAttribute.repository_id == repository.id)
        .order_by(RepositoryAnalysisAttribute.extracted_at.desc())
        .all()
    )
    attrs_map = _attrs_by_key(attrs)

    pages = db.query(WikiPage).filter(WikiPage.repository_id == repository.id).all()
    wiki_site = (
        db.query(RepositoryWikiSite)
        .filter(RepositoryWikiSite.repository_id == repository.id)
        .order_by(RepositoryWikiSite.updated_at.desc())
        .first()
    )

    artifacts = load_analysis_artifacts(resolve_analysis_dir(repository))
    wiki_json = artifacts.get("wiki_json") if artifacts else None
    if not wiki_json and wiki_site and wiki_site.summary_json:
        wiki_json = wiki_site.summary_json

    fresh_score, fresh_value, fresh_detail = _freshness_score(repository.last_indexed_at)
    doc_score, doc_detail = _doc_coverage_score(wiki_site, pages)
    drift_sc, drift_detail = _drift_score(pages)
    test_score, test_detail, test_count = _test_signal_score(db, repository.id)

    signals: List[Dict[str, Any]] = [
        _signal(
            "index_freshness",
            "Index freshness",
            fresh_value,
            fresh_score,
            _status_for_score(fresh_score),
            fresh_detail,
            recommendation="Re-index before modernization if the index is stale.",
            source="platform",
            weight=2,
            remediation_scope="simple_fix",
        ),
        _signal(
            "documentation",
            "Documentation / wiki",
            f"{len(pages)} pages",
            doc_score,
            _status_for_score(doc_score),
            doc_detail,
            recommendation="Deepen wiki sections (Architecture, Business Logic) before large refactors.",
            source="platform",
            weight=2,
            remediation_scope="either",
        ),
        _signal(
            "test_coverage",
            "Test signal",
            test_detail,
            test_score,
            _status_for_score(test_score),
            "Heuristic based on test-related file paths in the index.",
            recommendation="Improve automated tests before agent Code→Push stages.",
            source="platform",
            weight=2,
            remediation_scope="simple_fix",
        ),
        _signal(
            "drift",
            "Wiki drift",
            drift_detail.split(",")[0],
            drift_sc,
            _status_for_score(drift_sc),
            drift_detail,
            recommendation="Re-verify or re-generate stale wiki pages.",
            source="platform",
            weight=1,
            remediation_scope="simple_fix",
        ),
    ]

    # Analysis Config–driven modernization signals
    for defn in assessment_defs:
        key = (defn.get("key") or "").lower()
        row = attrs_map.get(key)
        value_text = row.value_text if row else None
        applicable, na_reason = is_attribute_applicable(
            defn,
            db=db,
            repository_id=repository.id,
            wiki_json=wiki_json if isinstance(wiki_json, dict) else None,
            attrs_map=attrs_map,
            value_text=value_text,
        )
        if not applicable:
            signals.append(_na_attribute_signal(defn, na_reason))
            continue
        signals.append(
            score_attribute_signal(
                defn,
                value_text,
                source_file=row.source_file if row else None,
            )
        )

    # Alias for legacy modernize policies that target signal id "runtime"
    runtime_keys = ("java_version", "node_version", "python_version")
    runtime_attr = None
    runtime_defn = None
    for rk in runtime_keys:
        row = attrs_map.get(rk)
        defn = next((d for d in assessment_defs if (d.get("key") or "").lower() == rk), None)
        if not defn:
            continue
        applicable, _ = is_attribute_applicable(
            defn,
            db=db,
            repository_id=repository.id,
            wiki_json=wiki_json if isinstance(wiki_json, dict) else None,
            attrs_map=attrs_map,
            value_text=row.value_text if row else None,
        )
        if applicable and row and row.value_text and str(row.value_text).strip():
            runtime_attr = row
            runtime_defn = defn
            break
    if runtime_defn:
        runtime_sig = score_attribute_signal(
            {**runtime_defn, "key": "runtime", "label": "Runtime / language"},
            runtime_attr.value_text if runtime_attr else None,
            source_file=runtime_attr.source_file if runtime_attr else None,
        )
        runtime_sig["id"] = "runtime"
        signals.append(runtime_sig)

    index_age_days = None
    if repository.last_indexed_at:
        index_age_days = (dt.now() - repository.last_indexed_at).total_seconds() / 86400

    verified = sum(p.verified_claim_count or 0 for p in pages)
    total_claims = sum(p.total_claim_count or 0 for p in pages)
    citation_pct = round((verified / total_claims) * 100) if total_claims else 0

    runtime_signal = next((s for s in signals if s["id"] == "runtime"), None)
    runtime = runtime_signal["value"] if runtime_signal else "Unknown"
    frameworks = [
        s["value"]
        for s in signals
        if s["id"] in ("attr:framework", "attr:spring_boot_version")
    ]

    policies = load_modernize_policies(db, repository.tenant_id)
    policy_result = apply_modernize_policies(
        signals=signals,
        policies=policies,
        context={
            "runtime": runtime,
            "page_slugs": {p.slug for p in pages if p.slug},
            "citation_pct": citation_pct,
            "test_file_count": test_count,
            "frameworks": frameworks,
            "index_age_days": index_age_days,
        },
    )
    signals = policy_result["signals"]

    # Prefer unique signals for scoring/UI: drop runtime alias when attr:* runtime exists
    has_attr_runtime = any(
        s.get("id") in ("attr:java_version", "attr:node_version", "attr:python_version")
        and s.get("applicable", True)
        and s.get("status") != "na"
        for s in signals
    )
    for_overall = [
        s
        for s in signals
        if s.get("applicable", True)
        and s.get("status") != "na"
        and s.get("score") is not None
        and not (has_attr_runtime and s.get("id") == "runtime")
    ]
    total_w = sum(int(s.get("weight") or 1) for s in for_overall) or 1
    overall = round(
        sum(int(s.get("score") or 0) * int(s.get("weight") or 1) for s in for_overall) / total_w
    )
    if overall >= 75:
        level = "ready"
    elif overall >= 50:
        level = "partial"
    else:
        level = "blocked"
    signals = for_overall

    plan_rec = recommend_plan_type(signals)

    existing_plans = (
        db.query(ModernizationPlan)
        .filter(
            ModernizationPlan.repository_id == repository.id,
            ModernizationPlan.tenant_id == repository.tenant_id,
            ModernizationPlan.state.notin_(["complete", "cancelled"]),
        )
        .order_by(ModernizationPlan.updated_at.desc())
        .all()
    )

    tech_stack = wiki_json.get("tech_stack") if wiki_json else []
    overview = (wiki_json or {}).get("overview") or {}

    return {
        "repository_id": repository.id,
        "repository_name": repository.name,
        "repository_status": repository.status,
        "overall_score": overall,
        "readiness_level": level,
        "signals": signals,
        "recommended_plan_type": plan_rec["recommended_plan_type"],
        "recommendation_reason": plan_rec["recommendation_reason"],
        "tech_stack": tech_stack,
        "overview": overview,
        "business_logic_summary": (wiki_json or {}).get("business_logic_layer", {}).get("summary"),
        "existing_plans": [
            {
                "id": p.id,
                "title": p.title,
                "state": p.state,
                "spawned_project_id": p.spawned_project_id,
                "plan_type": getattr(p, "plan_type", None) or "modernize",
            }
            for p in existing_plans
        ],
        "indexed": repository.status == "ready",
        "test_file_count": test_count,
        "assessment_definitions_used": [d.get("key") for d in assessment_defs],
        "policy_version_ids": policy_result.get("policy_version_ids") or [],
        "policies_applied": policy_result.get("policies_applied") or [],
        "policy_gaps": policy_result.get("policy_gaps") or [],
    }

"""Per-scope hash-chained audit for agent side effects (ADR 0010 §5f)."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.database import AuditTrail
from app.services.agent_runtime.contracts import IdempotencyKey


def _canonical(details: Dict[str, Any]) -> str:
    return json.dumps(details, sort_keys=True, default=str)


def _hash_event(prev_hash: Optional[str], payload: Dict[str, Any]) -> str:
    material = (prev_hash or "") + "|" + _canonical(payload)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def scope_key(*, tenant_id: str, savi_id: Optional[str] = None) -> str:
    """Per-tenant or per-Savi chain scope (ADR 0010 §5f)."""
    if savi_id:
        return f"savi:{tenant_id}:{savi_id}"
    return f"tenant:{tenant_id}"


def _latest_hash(db: Session, scope: str) -> Optional[str]:
    row = (
        db.query(AuditTrail)
        .filter(AuditTrail.resource_type == "agent_scope", AuditTrail.resource_id == scope)
        .order_by(AuditTrail.created_at.desc())
        .first()
    )
    if not row or not row.details:
        return None
    return (row.details or {}).get("event_hash")


def log_agent_side_effect(
    db: Session,
    *,
    tenant_id: str,
    actor_id: str,
    action_type: str,
    resource_type: str,
    resource_id: str,
    idempotency_key: IdempotencyKey,
    policy_decision: str,
    versions: Optional[Dict[str, Any]] = None,
    savi_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> AuditTrail:
    """
    Immutable audit row with per-scope hash chain.

    Chain tip is stored on resource_type=agent_scope / resource_id=scope_key
    so concurrent tenants/Savis do not share one global chain.
    """
    scope = scope_key(tenant_id=tenant_id, savi_id=savi_id)
    prev = _latest_hash(db, scope)
    details: Dict[str, Any] = {
        "idempotency_key": idempotency_key.as_string(),
        "policy_decision": policy_decision,
        "versions": versions or {},
        "scope_key": scope,
        "prev_hash": prev,
        **(extra or {}),
    }
    event_hash = _hash_event(prev, {**details, "action_type": action_type, "resource_id": resource_id})
    details["event_hash"] = event_hash

    record = AuditTrail(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=actor_id,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        created_at=datetime.utcnow(),
    )
    db.add(record)

    # Chain tip marker (same hash payload) for O(1) prev lookup
    tip = AuditTrail(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=actor_id,
        action_type="agent_audit_chain_tip",
        resource_type="agent_scope",
        resource_id=scope,
        details={"event_hash": event_hash, "prev_hash": prev, "tip_of": record.id},
        created_at=datetime.utcnow(),
    )
    db.add(tip)
    db.commit()
    db.refresh(record)
    return record

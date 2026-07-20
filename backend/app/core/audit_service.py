"""
Audit trail logging service for all v2 operations.

Provides centralized audit logging for:
- Policy lifecycle events (create, update, publish, deprecate)
- Approval decisions
- Workflow run events (start, complete)
- Deployment events (provision, teardown)

RETENTION POLICY: All audit trail records MUST be retained for a minimum of 90 days.
A scheduled cleanup job should purge records older than 90 days. Do NOT delete
audit records within the 90-day retention window. This applies to both
AuditTrail and PolicyAuditLog tables.

Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.database import AuditTrail, PolicyAuditLog


# ---------------------------------------------------------------------------
# Action type constants
# ---------------------------------------------------------------------------

# Policy actions (logged to PolicyAuditLog)
POLICY_CREATED = "policy_created"
POLICY_UPDATED = "policy_updated"
POLICY_PUBLISHED = "policy_published"
POLICY_DEPRECATED = "policy_deprecated"

# Approval actions (logged to AuditTrail)
APPROVAL_APPROVED = "approval_approved"
APPROVAL_REJECTED = "approval_rejected"

# Workflow actions (logged to AuditTrail)
WORKFLOW_STARTED = "workflow_started"
WORKFLOW_COMPLETED = "workflow_completed"

# Deployment actions (logged to AuditTrail)
DEPLOYMENT_PROVISIONED = "deployment_provisioned"
DEPLOYMENT_TORN_DOWN = "deployment_torn_down"


# ---------------------------------------------------------------------------
# Core audit logging functions
# ---------------------------------------------------------------------------

def log_audit_event(
    db: Session,
    tenant_id: str,
    user_id: str,
    action_type: str,
    resource_type: str,
    resource_id: str,
    details: Optional[Dict[str, Any]] = None,
) -> AuditTrail:
    """Create an AuditTrail record for a general v2 operation.

    Used for approval decisions, workflow run events, and deployment events.
    """
    record = AuditTrail(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def log_policy_audit(
    db: Session,
    tenant_id: str,
    user_id: str,
    action_type: str,
    policy_id: str,
    change_details: Optional[Dict[str, Any]] = None,
) -> PolicyAuditLog:
    """Create a PolicyAuditLog record for a policy lifecycle event.

    Used for policy create/update/publish/deprecate events.
    """
    record = PolicyAuditLog(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        policy_id=policy_id,
        action_type=action_type,
        user_id=user_id,
        changes=change_details,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def query_audit_trail(
    db: Session,
    tenant_id: str,
    user_id: Optional[str] = None,
    action_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> List[AuditTrail]:
    """Query AuditTrail records with optional filters.

    Always scoped by tenant_id. Supports filtering by user_id, action_type,
    and date range (start_date / end_date on created_at).
    Validates: Requirement 20.6
    """
    filters = [AuditTrail.tenant_id == tenant_id]

    if user_id is not None:
        filters.append(AuditTrail.user_id == user_id)
    if action_type is not None:
        filters.append(AuditTrail.action_type == action_type)
    if start_date is not None:
        filters.append(AuditTrail.created_at >= start_date)
    if end_date is not None:
        filters.append(AuditTrail.created_at <= end_date)

    return (
        db.query(AuditTrail)
        .filter(and_(*filters))
        .order_by(AuditTrail.created_at.desc())
        .all()
    )

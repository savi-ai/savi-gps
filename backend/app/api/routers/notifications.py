"""Notification and Deployment API endpoints.

Requirements: 12.4, 12.5, 17.1, 17.2
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db, Notification, Deployment, User
from app.core.tenant_isolation import scope_query_by_tenant
from app.core.logger import logger

router = APIRouter(tags=["Notifications & Deployments"])


# ── Notification Endpoints ─────────────────────────────────────────────


@router.get("/notifications")
async def list_notifications(
    unread_only: bool = Query(False, description="Filter to unread notifications only"),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get notifications for the current user, scoped by tenant_id.

    Requirement 12.4: Record each notification with recipient, type, content, sent_at.
    Requirement 12.5: Support in-app notifications stored in the database.
    """
    query = scope_query_by_tenant(
        db.query(Notification), Notification, user.tenant_id
    ).filter(Notification.user_id == user.id)

    if unread_only:
        query = query.filter(Notification.is_read == False)

    notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()

    return {
        "notifications": [
            {
                "id": n.id,
                "notification_type": n.notification_type,
                "title": n.title,
                "message": n.message,
                "context": n.context,
                "is_read": n.is_read,
                "read_at": n.read_at.isoformat() if n.read_at else None,
                "sent_at": n.sent_at.isoformat() if n.sent_at else None,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifications
        ],
        "count": len(notifications),
    }


@router.put("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a notification as read.

    Requirement 12.5: Support in-app notifications stored in the database.
    """
    notification = (
        scope_query_by_tenant(
            db.query(Notification), Notification, user.tenant_id
        )
        .filter(Notification.id == notification_id, Notification.user_id == user.id)
        .first()
    )

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    notification.is_read = True
    notification.read_at = datetime.now()
    db.commit()

    return {"status": "ok", "id": notification_id, "is_read": True}


# ── Deployment Endpoint ────────────────────────────────────────────────


@router.get("/deployments/{run_id}")
async def get_deployment(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get deployment status and URL for a workflow run.

    Requirement 17.1: Display the Ephemeral Environment URL as a clickable link.
    Requirement 17.2: Display deployment status with a visual indicator.
    """
    deployment = (
        scope_query_by_tenant(
            db.query(Deployment), Deployment, user.tenant_id
        )
        .filter(Deployment.workflow_run_id == run_id)
        .first()
    )

    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found for this run")

    return {
        "deployment_id": deployment.id,
        "workflow_run_id": deployment.workflow_run_id,
        "project_id": deployment.project_id,
        "status": deployment.status,
        "provider": deployment.provider,
        "region": deployment.region,
        "resource_type": deployment.resource_type,
        "resource_identifiers": deployment.resource_identifiers,
        "environment_url": deployment.environment_url,
        "health_check_status": deployment.health_check_status,
        "infrastructure_artifacts": deployment.infrastructure_artifacts,
        "failure_reason": deployment.failure_reason,
        "last_successful_step": deployment.last_successful_step,
        "logs": deployment.logs,
        "created_at": deployment.created_at.isoformat() if deployment.created_at else None,
        "updated_at": deployment.updated_at.isoformat() if deployment.updated_at else None,
    }

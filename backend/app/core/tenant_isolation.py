"""Tenant isolation utilities for multi-tenant data scoping.

Provides helpers to ensure all database queries are scoped by tenant_id,
and to verify that a user has access to a given resource. This enforces
Requirement 18 (Multi-Tenant Data Isolation) — a user from tenant A must
never read or modify data belonging to tenant B.

Requirements: 18.1, 18.2, 18.3, 18.4, 18.5
"""
from typing import Any, Optional, Type

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, Query

from app.core.logger import logger


def scope_query_by_tenant(
    query: Query,
    model: Any,
    tenant_id: str,
    *,
    include_global: bool = False,
) -> Query:
    """Add a tenant_id filter to an existing SQLAlchemy query.

    Args:
        query: The SQLAlchemy query to scope.
        model: The ORM model class (must have a ``tenant_id`` column).
        tenant_id: The tenant identifier to filter by.
        include_global: If True, also include rows where
            ``model.level == "global"`` (used for policy queries per Req 18.1).

    Returns:
        The query with the tenant filter applied.
    """
    if include_global and hasattr(model, "level"):
        return query.filter(
            (model.tenant_id == tenant_id) | (model.level == "global")
        )
    return query.filter(model.tenant_id == tenant_id)


def verify_tenant_access(
    resource: Any,
    user_tenant_id: str,
    *,
    allow_global: bool = False,
) -> None:
    """Raise 403 if the resource belongs to a different tenant.

    Args:
        resource: An ORM model instance with a ``tenant_id`` attribute.
        user_tenant_id: The requesting user's tenant_id.
        allow_global: If True, resources with ``level == "global"`` are
            accessible to any tenant (Req 18.1).

    Raises:
        HTTPException: 403 Forbidden when tenant_id does not match.
    """
    resource_tenant_id = getattr(resource, "tenant_id", None)

    # Global-level resources (e.g. global policies) are visible to all tenants
    if allow_global and getattr(resource, "level", None) == "global":
        return

    if resource_tenant_id is None:
        logger.warning(
            "Tenant isolation violation: resource missing tenant_id (type: %s, id: %s)",
            type(resource).__name__,
            getattr(resource, "id", "unknown"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: resource is not tenant-scoped",
        )

    if resource_tenant_id != user_tenant_id:
        logger.warning(
            "Tenant isolation violation: user tenant '%s' attempted to access "
            "resource belonging to tenant '%s' (resource type: %s, id: %s)",
            user_tenant_id,
            resource_tenant_id,
            type(resource).__name__,
            getattr(resource, "id", "unknown"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: resource belongs to a different tenant",
        )


class TenantScopedQuery:
    """Context manager / helper that wraps a DB session with automatic tenant scoping.

    Usage::

        with TenantScopedQuery(db, tenant_id) as tsq:
            policies = tsq.query(Policy, include_global=True).filter(...).all()
            runs = tsq.query(WorkflowRun).filter(...).all()
    """

    def __init__(self, db: Session, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    def __enter__(self) -> "TenantScopedQuery":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # Session lifecycle is managed by the caller; nothing to clean up.
        pass

    def query(self, model: Type, *, include_global: bool = False) -> Query:
        """Start a tenant-scoped query for *model*.

        Args:
            model: The ORM model class (must have a ``tenant_id`` column).
            include_global: If True, also include global-level rows.

        Returns:
            A SQLAlchemy Query already filtered by tenant_id.
        """
        base = self.db.query(model)
        return scope_query_by_tenant(
            base, model, self.tenant_id, include_global=include_global
        )

    def verify_access(self, resource: Any, *, allow_global: bool = False) -> None:
        """Convenience wrapper around :func:`verify_tenant_access`."""
        verify_tenant_access(
            resource, self.tenant_id, allow_global=allow_global
        )

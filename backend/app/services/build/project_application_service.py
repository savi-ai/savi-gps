"""ADR 0006 helpers — Application origin ↔ Project mode / target."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import Application, ApplicationRepository, Project

PROJECT_MODES = ("greenfield", "enhance", "extend")
APPLICATION_ORIGINS = ("imported", "generated", "hybrid")


def normalize_mode(mode: Optional[str], *, default: str = "greenfield") -> str:
    value = (mode or default).strip().lower()
    if value not in PROJECT_MODES:
        raise ValueError(
            f"mode must be one of: {', '.join(PROJECT_MODES)}"
        )
    return value


def normalize_origin(origin: Optional[str], *, default: str = "imported") -> str:
    value = (origin or default).strip().lower()
    if value not in APPLICATION_ORIGINS:
        raise ValueError(
            f"origin must be one of: {', '.join(APPLICATION_ORIGINS)}"
        )
    return value


def application_origin(app: Application) -> str:
    return normalize_origin(getattr(app, "origin", None), default="imported")


def project_mode(project: Project) -> Optional[str]:
    raw = getattr(project, "mode", None)
    if not raw:
        return None
    try:
        return normalize_mode(raw)
    except ValueError:
        return None


def resolve_target_application_id(
    *,
    application_id: Optional[str] = None,
    target_application_id: Optional[str] = None,
) -> Optional[str]:
    """Accept either API name; prefer explicit target_application_id."""
    return target_application_id or application_id or None


def _unique_application_name(db: Session, tenant_id: str, base: str) -> str:
    name = base.strip() or "New Application"
    existing = (
        db.query(Application)
        .filter(Application.tenant_id == tenant_id, Application.name == name)
        .first()
    )
    if not existing:
        return name
    suffix = 2
    while True:
        candidate = f"{name} ({suffix})"
        clash = (
            db.query(Application)
            .filter(Application.tenant_id == tenant_id, Application.name == candidate)
            .first()
        )
        if not clash:
            return candidate
        suffix += 1


def ensure_target_application(
    db: Session,
    *,
    tenant_id: str,
    user_id: Optional[str],
    mode: str,
    project_name: str,
    project_description: Optional[str],
    project_domain: Optional[str],
    application_id: Optional[str],
) -> Application:
    """
    Every Build/Modernize project targets an Application (ADR 0006).

    - greenfield: create Application(origin=generated) unless an empty target is given
    - enhance / extend: require an existing Application
    """
    mode = normalize_mode(mode)

    if mode in ("enhance", "extend"):
        if not application_id:
            raise ValueError(
                f"mode={mode} requires application_id (target Application)"
            )
        app = (
            db.query(Application)
            .filter(Application.id == application_id, Application.tenant_id == tenant_id)
            .first()
        )
        if not app:
            raise ValueError("Application not found")
        if mode == "extend" and application_origin(app) == "imported":
            app.origin = "hybrid"
        return app

    # greenfield
    if application_id:
        app = (
            db.query(Application)
            .filter(Application.id == application_id, Application.tenant_id == tenant_id)
            .first()
        )
        if not app:
            raise ValueError("Application not found")
        # Prefer generated apps for greenfield; don't silently overwrite imported estate
        if application_origin(app) == "imported":
            member_count = (
                db.query(ApplicationRepository)
                .filter(ApplicationRepository.application_id == app.id)
                .count()
            )
            if member_count > 0:
                raise ValueError(
                    "Greenfield cannot target an imported Application that already has repos; "
                    "use enhance or extend"
                )
        if application_origin(app) == "imported":
            app.origin = "generated"
        return app

    app = Application(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=_unique_application_name(db, tenant_id, project_name),
        description=project_description,
        domain=project_domain,
        created_by=user_id,
        origin="generated",
    )
    db.add(app)
    db.flush()
    return app


def maybe_mark_hybrid_after_link(
    app: Application,
    *,
    mode: str,
    linked_repo_count: int,
) -> None:
    """Promote generated → hybrid when brownfield context is attached."""
    if linked_repo_count <= 0:
        return
    if mode in ("enhance", "extend") and application_origin(app) == "generated":
        app.origin = "hybrid"
    elif mode == "extend":
        app.origin = "hybrid"


def resolve_application_for_spawn(
    db: Session,
    *,
    tenant_id: str,
    plan_application_id: Optional[str],
    repository_id: str,
) -> Optional[Application]:
    if plan_application_id:
        app = (
            db.query(Application)
            .filter(
                Application.id == plan_application_id,
                Application.tenant_id == tenant_id,
            )
            .first()
        )
        if app:
            return app
    row = (
        db.query(ApplicationRepository)
        .join(Application, ApplicationRepository.application_id == Application.id)
        .filter(
            ApplicationRepository.repository_id == repository_id,
            Application.tenant_id == tenant_id,
        )
        .first()
    )
    if not row:
        return None
    return (
        db.query(Application)
        .filter(Application.id == row.application_id, Application.tenant_id == tenant_id)
        .first()
    )


def project_target_payload(project: Project, app_name: Optional[str] = None) -> Dict[str, Any]:
    """API fields: keep source_application_id, also expose target aliases."""
    app_id = project.source_application_id
    return {
        "source_application_id": app_id,
        "target_application_id": app_id,
        "source_application_name": app_name,
        "target_application_name": app_name,
    }

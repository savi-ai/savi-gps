"""Estate Application inventory — group repositories into real-world products."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import Application, ApplicationRepository, Repository

REPO_ROLES = ("backend", "frontend", "api", "worker", "infra", "library", "other")


class ApplicationService:
    def __init__(self, db: Session):
        self.db = db

    def list_applications(self, tenant_id: str) -> List[Application]:
        return (
            self.db.query(Application)
            .filter(Application.tenant_id == tenant_id)
            .order_by(Application.name.asc())
            .all()
        )

    def get_application(self, tenant_id: str, application_id: str) -> Optional[Application]:
        return (
            self.db.query(Application)
            .filter(Application.id == application_id, Application.tenant_id == tenant_id)
            .first()
        )

    def get_application_for_repository(
        self, tenant_id: str, repository_id: str
    ) -> Optional[Application]:
        row = (
            self.db.query(ApplicationRepository)
            .join(Application, ApplicationRepository.application_id == Application.id)
            .filter(
                ApplicationRepository.repository_id == repository_id,
                Application.tenant_id == tenant_id,
            )
            .first()
        )
        if not row:
            return None
        return self.get_application(tenant_id, row.application_id)

    def create_application(
        self,
        tenant_id: str,
        name: str,
        description: Optional[str] = None,
        domain: Optional[str] = None,
        created_by: Optional[str] = None,
        repository_ids: Optional[List[str]] = None,
        origin: Optional[str] = None,
    ) -> Application:
        from app.services.build.project_application_service import normalize_origin

        name = name.strip()
        if not name:
            raise ValueError("Application name is required")

        existing = (
            self.db.query(Application)
            .filter(Application.tenant_id == tenant_id, Application.name == name)
            .first()
        )
        if existing:
            raise ValueError(f"Application '{name}' already exists")

        resolved_origin = normalize_origin(origin, default="imported")
        if repository_ids and resolved_origin == "generated":
            # Creating with existing repos is inventory import, not greenfield generation
            resolved_origin = "imported"

        app = Application(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=name,
            description=description,
            domain=domain,
            created_by=created_by,
            origin=resolved_origin,
        )
        self.db.add(app)
        self.db.flush()

        if repository_ids:
            for repo_id in repository_ids:
                repo = (
                    self.db.query(Repository)
                    .filter(Repository.id == repo_id, Repository.tenant_id == tenant_id)
                    .first()
                )
                if not repo:
                    raise ValueError(f"Repository not found: {repo_id}")
                existing = (
                    self.db.query(ApplicationRepository)
                    .filter(ApplicationRepository.repository_id == repo_id)
                    .first()
                )
                if existing:
                    raise ValueError(f"Repository {repo_id} is already in an application")
                self.db.add(
                    ApplicationRepository(
                        id=str(uuid.uuid4()),
                        application_id=app.id,
                        repository_id=repo_id,
                    )
                )

        self.db.commit()
        self.db.refresh(app)
        return app

    def update_application(
        self,
        tenant_id: str,
        application_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> Application:
        app = self.get_application(tenant_id, application_id)
        if not app:
            raise ValueError("Application not found")

        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("Application name cannot be empty")
            clash = (
                self.db.query(Application)
                .filter(
                    Application.tenant_id == tenant_id,
                    Application.name == name,
                    Application.id != application_id,
                )
                .first()
            )
            if clash:
                raise ValueError(f"Application '{name}' already exists")
            app.name = name

        if description is not None:
            app.description = description
        if domain is not None:
            app.domain = domain

        self.db.commit()
        self.db.refresh(app)
        return app

    def delete_application(self, tenant_id: str, application_id: str) -> None:
        app = self.get_application(tenant_id, application_id)
        if not app:
            raise ValueError("Application not found")
        self.db.delete(app)
        self.db.commit()

    def add_repository(
        self,
        tenant_id: str,
        application_id: str,
        repository_id: str,
        role: Optional[str] = None,
    ) -> ApplicationRepository:
        app = self.get_application(tenant_id, application_id)
        if not app:
            raise ValueError("Application not found")

        repo = (
            self.db.query(Repository)
            .filter(Repository.id == repository_id, Repository.tenant_id == tenant_id)
            .first()
        )
        if not repo:
            raise ValueError(f"Repository not found: {repository_id}")

        existing = (
            self.db.query(ApplicationRepository)
            .filter(ApplicationRepository.repository_id == repository_id)
            .first()
        )
        if existing:
            if existing.application_id == application_id:
                if role is not None:
                    existing.role = role
                    self.db.commit()
                    self.db.refresh(existing)
                return existing
            other = self.get_application(tenant_id, existing.application_id)
            other_name = other.name if other else existing.application_id
            raise ValueError(
                f"Repository is already assigned to application '{other_name}'"
            )

        if role and role not in REPO_ROLES:
            raise ValueError(f"role must be one of: {', '.join(REPO_ROLES)}")

        membership = ApplicationRepository(
            id=str(uuid.uuid4()),
            application_id=application_id,
            repository_id=repository_id,
            role=role,
        )
        self.db.add(membership)
        self.db.commit()
        self.db.refresh(membership)
        from app.services.intelligence.application_graph_service import (
            invalidate_application_graph_cache,
        )

        invalidate_application_graph_cache(tenant_id, application_id)
        from app.services.intelligence.application_synthesizer import (
            invalidate_application_wiki_cache,
        )

        invalidate_application_wiki_cache(tenant_id, application_id)
        return membership

    def remove_repository(
        self, tenant_id: str, application_id: str, repository_id: str
    ) -> None:
        app = self.get_application(tenant_id, application_id)
        if not app:
            raise ValueError("Application not found")

        row = (
            self.db.query(ApplicationRepository)
            .filter(
                ApplicationRepository.application_id == application_id,
                ApplicationRepository.repository_id == repository_id,
            )
            .first()
        )
        if not row:
            raise ValueError("Repository is not in this application")
        self.db.delete(row)
        self.db.commit()
        from app.services.intelligence.application_graph_service import (
            invalidate_application_graph_cache,
        )
        from app.services.intelligence.application_synthesizer import (
            invalidate_application_wiki_cache,
        )

        invalidate_application_graph_cache(tenant_id, application_id)
        invalidate_application_wiki_cache(tenant_id, application_id)

    def list_repository_ids(self, tenant_id: str, application_id: str) -> List[str]:
        app = self.get_application(tenant_id, application_id)
        if not app:
            raise ValueError("Application not found")
        rows = (
            self.db.query(ApplicationRepository.repository_id)
            .filter(ApplicationRepository.application_id == application_id)
            .all()
        )
        return [row[0] for row in rows]

    def assign_repositories_to_application(
        self,
        tenant_id: str,
        repository_ids: List[str],
        application_id: Optional[str] = None,
        application_name: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Optional[Application]:
        """Create or use an application and attach repos (used after bulk import)."""
        if not repository_ids:
            return None

        app: Optional[Application] = None
        if application_id:
            app = self.get_application(tenant_id, application_id)
            if not app:
                raise ValueError("Application not found")
        elif application_name and application_name.strip():
            app = self.create_application(
                tenant_id,
                application_name.strip(),
                created_by=created_by,
            )
        else:
            return None

        for repo_id in repository_ids:
            try:
                self.add_repository(tenant_id, app.id, repo_id)
            except ValueError as e:
                if "already assigned" in str(e):
                    continue
                raise
        return app

    def to_summary_dict(self, app: Application) -> Dict[str, Any]:
        memberships = (
            self.db.query(ApplicationRepository, Repository)
            .join(Repository, ApplicationRepository.repository_id == Repository.id)
            .filter(ApplicationRepository.application_id == app.id)
            .all()
        )
        ready = sum(1 for _, repo in memberships if repo.status == "ready")
        return {
            "id": app.id,
            "name": app.name,
            "description": app.description,
            "domain": app.domain,
            "origin": getattr(app, "origin", None) or "imported",
            "repository_count": len(memberships),
            "repositories_ready": ready,
            "created_at": app.created_at.isoformat() if app.created_at else None,
            "updated_at": app.updated_at.isoformat() if app.updated_at else None,
        }

    def to_detail_dict(self, app: Application) -> Dict[str, Any]:
        data = self.to_summary_dict(app)
        memberships = (
            self.db.query(ApplicationRepository, Repository)
            .join(Repository, ApplicationRepository.repository_id == Repository.id)
            .filter(ApplicationRepository.application_id == app.id)
            .order_by(Repository.name.asc())
            .all()
        )
        data["repositories"] = [
            {
                "id": repo.id,
                "name": repo.name,
                "github_full_name": repo.github_full_name,
                "status": repo.status,
                "role": membership.role,
                "last_indexed_at": repo.last_indexed_at.isoformat()
                if repo.last_indexed_at
                else None,
            }
            for membership, repo in memberships
        ]
        return data

    def repository_application_dict(
        self, tenant_id: str, repository_id: str
    ) -> Optional[Dict[str, Any]]:
        app = self.get_application_for_repository(tenant_id, repository_id)
        if not app:
            return None
        membership = (
            self.db.query(ApplicationRepository)
            .filter(ApplicationRepository.repository_id == repository_id)
            .first()
        )
        return {
            "id": app.id,
            "name": app.name,
            "role": membership.role if membership else None,
        }

"""ChatScope — tenant-safe scope for federated retrieval, chat, and search."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional

from sqlalchemy.orm import Session

from app.core.database import Application, ApplicationRepository, Repository

MAX_REPOS_PER_SCOPE = 25


@dataclass(frozen=True)
class ChatScope:
    type: Literal["repo", "application", "tenant"]
    id: Optional[str]
    tenant_id: str

    @classmethod
    def repo(cls, repo_id: str, tenant_id: str) -> "ChatScope":
        return cls(type="repo", id=repo_id, tenant_id=tenant_id)

    @classmethod
    def application(cls, app_id: str, tenant_id: str) -> "ChatScope":
        return cls(type="application", id=app_id, tenant_id=tenant_id)

    @classmethod
    def tenant(cls, tenant_id: str) -> "ChatScope":
        return cls(type="tenant", id=None, tenant_id=tenant_id)

    def label(self, db: Session) -> str:
        if self.type == "repo" and self.id:
            repo = (
                db.query(Repository)
                .filter(Repository.id == self.id, Repository.tenant_id == self.tenant_id)
                .first()
            )
            return repo.github_full_name or repo.name if repo else self.id
        if self.type == "application" and self.id:
            app = (
                db.query(Application)
                .filter(Application.id == self.id, Application.tenant_id == self.tenant_id)
                .first()
            )
            return app.name if app else self.id
        return "tenant"

    def resolve_repo_ids(self, db: Session) -> List[str]:
        if self.type == "repo":
            if not self.id:
                return []
            row = (
                db.query(Repository.id)
                .filter(Repository.id == self.id, Repository.tenant_id == self.tenant_id)
                .first()
            )
            return [row[0]] if row else []

        if self.type == "application":
            if not self.id:
                return []
            app = (
                db.query(Application)
                .filter(Application.id == self.id, Application.tenant_id == self.tenant_id)
                .first()
            )
            if not app:
                return []
            rows = (
                db.query(Repository.id)
                .join(ApplicationRepository, ApplicationRepository.repository_id == Repository.id)
                .filter(
                    ApplicationRepository.application_id == app.id,
                    Repository.tenant_id == self.tenant_id,
                )
                .order_by(Repository.name.asc())
                .all()
            )
            repo_ids = [r[0] for r in rows]
            if len(repo_ids) > MAX_REPOS_PER_SCOPE:
                raise ValueError(
                    f"Application has {len(repo_ids)} repositories; "
                    f"maximum supported is {MAX_REPOS_PER_SCOPE}"
                )
            return repo_ids

        rows = (
            db.query(Repository.id)
            .filter(Repository.tenant_id == self.tenant_id)
            .order_by(Repository.name.asc())
            .limit(MAX_REPOS_PER_SCOPE)
            .all()
        )
        return [r[0] for r in rows]

    def resolve_repositories(self, db: Session) -> List[Repository]:
        repo_ids = self.resolve_repo_ids(db)
        if not repo_ids:
            return []
        repos = (
            db.query(Repository)
            .filter(Repository.id.in_(repo_ids), Repository.tenant_id == self.tenant_id)
            .all()
        )
        order = {rid: i for i, rid in enumerate(repo_ids)}
        return sorted(repos, key=lambda r: order.get(r.id, 999))

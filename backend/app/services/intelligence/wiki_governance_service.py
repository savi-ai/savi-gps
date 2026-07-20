"""Wiki draft→live approval workflow and drift detection."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

from app.core.database import AuditTrail, IndexRun, Repository, WikiClaim, WikiPage
from app.core.logger import logger
from app.services.intelligence.citation_verifier import CitationVerifier


class WikiGovernanceService:
    MIN_COVERAGE_TO_APPROVE = 0.5

    def __init__(self, db: Session):
        self.db = db
        self.verifier = CitationVerifier(db)

    def get_page_with_quality(
        self, repository_id: str, slug: str
    ) -> Optional[Dict[str, Any]]:
        page = (
            self.db.query(WikiPage)
            .filter(WikiPage.repository_id == repository_id, WikiPage.slug == slug)
            .first()
        )
        if not page:
            return None
        repository = (
            self.db.query(Repository).filter(Repository.id == repository_id).first()
        )
        self.refresh_drift_status(page, repository)
        return self._page_dict(page)

    def list_claims(self, page_id: str) -> List[Dict[str, Any]]:
        claims = (
            self.db.query(WikiClaim)
            .filter(WikiClaim.page_id == page_id)
            .order_by(WikiClaim.citation_file.asc())
            .all()
        )
        return [self.verifier.claim_dict(c) for c in claims]

    def verify_page_citations(self, repository_id: str, slug: str) -> Dict[str, Any]:
        page = self._get_page(repository_id, slug)
        if not page:
            raise ValueError("Wiki page not found")
        stats = self.verifier.verify_page(page)
        repository = (
            self.db.query(Repository).filter(Repository.id == repository_id).first()
        )
        self.refresh_drift_status(page, repository)
        self.db.commit()
        return {
            "page_id": page.id,
            "slug": page.slug,
            "verified_claim_count": stats["verified"],
            "total_claim_count": stats["total"],
            "citation_coverage": self._coverage(page),
        }

    def approve_page(
        self,
        repository_id: str,
        slug: str,
        user_id: str,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        page = self._get_page(repository_id, slug)
        if not page:
            raise ValueError("Wiki page not found")
        if page.state == "live":
            raise ValueError("Page is already live")

        coverage = self._coverage(page)
        if page.total_claim_count > 0 and coverage < self.MIN_COVERAGE_TO_APPROVE:
            raise ValueError(
                f"Citation coverage {coverage:.0%} is below minimum "
                f"{self.MIN_COVERAGE_TO_APPROVE:.0%} required for approval"
            )

        page.state = "live"
        page.approved_by = user_id
        page.approved_at = datetime.now()
        page.review_notes = notes
        page.drift_status = "none"
        page.version = (page.version or 1) + 1

        self._audit(
            user_id=user_id,
            tenant_id=self._tenant_id(repository_id),
            action="wiki_page_approved",
            resource_id=page.id,
            details={"slug": slug, "repository_id": repository_id, "coverage": coverage},
        )
        self.db.commit()
        logger.info(f"Wiki page {slug} approved for repository {repository_id}")
        return self._page_dict(page)

    def reject_page(
        self,
        repository_id: str,
        slug: str,
        user_id: str,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        page = self._get_page(repository_id, slug)
        if not page:
            raise ValueError("Wiki page not found")

        page.state = "draft"
        page.review_notes = feedback
        page.drift_status = "pending_review"
        page.approved_by = None
        page.approved_at = None

        self._audit(
            user_id=user_id,
            tenant_id=self._tenant_id(repository_id),
            action="wiki_page_rejected",
            resource_id=page.id,
            details={"slug": slug, "repository_id": repository_id, "feedback": feedback},
        )
        self.db.commit()
        return self._page_dict(page)

    def repo_quality_summary(self, repository_id: str) -> Dict[str, Any]:
        pages = (
            self.db.query(WikiPage)
            .filter(WikiPage.repository_id == repository_id)
            .all()
        )
        repository = (
            self.db.query(Repository).filter(Repository.id == repository_id).first()
        )
        for page in pages:
            self.refresh_drift_status(page, repository)

        total_claims = sum(p.total_claim_count or 0 for p in pages)
        verified_claims = sum(p.verified_claim_count or 0 for p in pages)
        return {
            "repository_id": repository_id,
            "page_count": len(pages),
            "draft_count": sum(1 for p in pages if p.state == "draft"),
            "live_count": sum(1 for p in pages if p.state == "live"),
            "stale_count": sum(1 for p in pages if p.drift_status == "stale"),
            "total_claim_count": total_claims,
            "verified_claim_count": verified_claims,
            "citation_coverage": (
                verified_claims / total_claims if total_claims else 1.0
            ),
            "pages": [self._page_dict(p) for p in pages],
        }

    def refresh_drift_status(
        self, page: WikiPage, repository: Optional[Repository]
    ) -> None:
        if page.state != "live":
            page.drift_status = "pending_review"
            return

        latest_run = self._latest_completed_run(page.repository_id)
        if (
            latest_run
            and page.index_run_id
            and page.index_run_id != latest_run.id
        ):
            page.drift_status = "stale"
            return

        if repository and repository.last_indexed_at and page.approved_at:
            if repository.last_indexed_at > page.approved_at:
                page.drift_status = "stale"
                return

        page.drift_status = "none"

    def _latest_completed_run(self, repository_id: str) -> Optional[IndexRun]:
        return (
            self.db.query(IndexRun)
            .filter(
                IndexRun.repository_id == repository_id,
                IndexRun.status == "completed",
            )
            .order_by(IndexRun.completed_at.desc())
            .first()
        )

    def _get_page(self, repository_id: str, slug: str) -> Optional[WikiPage]:
        return (
            self.db.query(WikiPage)
            .filter(WikiPage.repository_id == repository_id, WikiPage.slug == slug)
            .first()
        )

    def _tenant_id(self, repository_id: str) -> Optional[str]:
        repo = self.db.query(Repository).filter(Repository.id == repository_id).first()
        return repo.tenant_id if repo else None

    def _coverage(self, page: WikiPage) -> float:
        if not page.total_claim_count:
            return 1.0
        return (page.verified_claim_count or 0) / page.total_claim_count

    def _page_dict(self, page: WikiPage) -> Dict[str, Any]:
        coverage = self._coverage(page)
        return {
            "id": page.id,
            "slug": page.slug,
            "title": page.title,
            "template_type": page.template_type,
            "content_md": page.content_md,
            "mermaid": page.mermaid,
            "state": page.state,
            "version": page.version,
            "freshness_at": page.freshness_at.isoformat() if page.freshness_at else None,
            "drift_status": page.drift_status,
            "verified_claim_count": page.verified_claim_count or 0,
            "total_claim_count": page.total_claim_count or 0,
            "citation_coverage": coverage,
            "approved_by": page.approved_by,
            "approved_at": page.approved_at.isoformat() if page.approved_at else None,
            "review_notes": page.review_notes,
            "index_run_id": page.index_run_id,
        }

    def _audit(
        self,
        user_id: str,
        tenant_id: Optional[str],
        action: str,
        resource_id: str,
        details: Dict[str, Any],
    ) -> None:
        self.db.add(
            AuditTrail(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                user_id=user_id,
                action_type=action,
                resource_type="wiki_page",
                resource_id=resource_id,
                details=details,
            )
        )

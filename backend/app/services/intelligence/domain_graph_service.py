"""Domain / object graph views — ERD Mermaid + summary (Phase 2)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.database import RepoAnalysisView, Repository, WikiPage
from app.core.logger import logger
from app.services.intelligence.analysis_storage import get_analysis_views_dir, resolve_analysis_dir
from app.services.intelligence.domain_graph_extractor import (
    DomainGraph,
    build_er_mermaid,
    build_summary_sentence,
    extract_domain_graph,
)

VIEW_TYPE = "domain_graph"
DOMAIN_GRAPH_FILE = "domain_graph.json"


class DomainGraphService:
    def __init__(self, db: Session):
        self.db = db

    def _load_disk(self, repository: Repository) -> Optional[DomainGraph]:
        path = resolve_analysis_dir(repository) / "views" / DOMAIN_GRAPH_FILE
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return DomainGraph.from_dict(data.get("graph") or data)
        except (json.JSONDecodeError, OSError, TypeError):
            return None

    def _load_db(self, repository: Repository) -> Optional[Dict[str, Any]]:
        row = (
            self.db.query(RepoAnalysisView)
            .filter(
                RepoAnalysisView.repository_id == repository.id,
                RepoAnalysisView.view_type == VIEW_TYPE,
            )
            .order_by(RepoAnalysisView.updated_at.desc())
            .first()
        )
        if not row:
            return None
        derivation = row.derivation_json or {}
        return {
            "summary": row.summary_sentence,
            "mermaid": row.mermaid or "",
            "entities": derivation.get("entities") or [],
            "relationships": derivation.get("relationships") or [],
            "sources": derivation.get("sources") or [],
            "entity_count": derivation.get("entity_count", 0),
            "relationship_count": derivation.get("relationship_count", 0),
            "available": derivation.get("entity_count", 0) > 0,
            "cached": True,
        }

    def _persist(
        self,
        repository: Repository,
        graph: DomainGraph,
        *,
        index_run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        summary = build_summary_sentence(graph)
        mermaid = build_er_mermaid(graph)
        from dataclasses import asdict

        derivation = {
            "entities": [asdict(e) for e in graph.entities],
            "relationships": [asdict(r) for r in graph.relationships],
            "sources": graph.sources,
            "entity_count": graph.entity_count,
            "relationship_count": graph.relationship_count,
        }
        payload = {
            "summary": summary,
            "mermaid": mermaid,
            **derivation,
            "available": graph.entity_count > 0,
            "cached": False,
        }

        existing = (
            self.db.query(RepoAnalysisView)
            .filter(
                RepoAnalysisView.repository_id == repository.id,
                RepoAnalysisView.view_type == VIEW_TYPE,
            )
            .first()
        )
        if existing:
            existing.summary_sentence = summary
            existing.mermaid = mermaid
            existing.derivation_json = derivation
            existing.index_run_id = index_run_id or existing.index_run_id
            existing.updated_at = datetime.now()
        else:
            self.db.add(
                RepoAnalysisView(
                    id=str(uuid.uuid4()),
                    tenant_id=repository.tenant_id,
                    repository_id=repository.id,
                    view_type=VIEW_TYPE,
                    anchor_symbol=None,
                    summary_sentence=summary,
                    mermaid=mermaid,
                    derivation_json=derivation,
                    index_run_id=index_run_id,
                )
            )
        self.db.commit()

        views_dir = get_analysis_views_dir(repository)
        views_dir.mkdir(parents=True, exist_ok=True)
        disk_payload = {"graph": graph.to_dict(), "summary": summary, "mermaid": mermaid}
        (views_dir / DOMAIN_GRAPH_FILE).write_text(
            json.dumps(disk_payload, indent=2), encoding="utf-8"
        )

        return payload

    def extract_and_persist(
        self,
        repository: Repository,
        clone_path: str,
        *,
        index_run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        graph = extract_domain_graph(clone_path)
        result = self._persist(repository, graph, index_run_id=index_run_id)
        logger.info(
            "Domain graph for %s: %s entities, %s relationships (sources=%s)",
            repository.id,
            graph.entity_count,
            graph.relationship_count,
            graph.sources,
        )
        return result

    def get(self, repository: Repository) -> Dict[str, Any]:
        cached = self._load_db(repository)
        if cached:
            return cached

        graph = self._load_disk(repository)
        if graph:
            return self._persist(repository, graph)

        return {
            "summary": build_summary_sentence(DomainGraph()),
            "mermaid": "",
            "entities": [],
            "relationships": [],
            "sources": [],
            "entity_count": 0,
            "relationship_count": 0,
            "available": False,
            "cached": False,
        }

    def enrich_architecture_page(self, repository: Repository) -> bool:
        """Append extracted domain model to the architecture wiki page (merge, don't replace)."""
        result = self.get(repository)
        if not result.get("available") or not result.get("mermaid"):
            return False

        page = (
            self.db.query(WikiPage)
            .filter(
                WikiPage.repository_id == repository.id,
                WikiPage.slug == "architecture",
            )
            .first()
        )
        if not page:
            return False

        marker = "## Domain model (extracted)"
        if marker in page.content_md:
            return False

        block = (
            f"\n\n{marker}\n\n"
            f"{result['summary']}\n\n"
            f"```mermaid\n{result['mermaid']}\n```\n"
        )
        page.content_md = page.content_md.rstrip() + block
        if not page.mermaid:
            page.mermaid = result["mermaid"]
        page.updated_at = datetime.now()
        self.db.commit()
        logger.info("Enriched architecture wiki page with domain model for %s", repository.id)
        return True

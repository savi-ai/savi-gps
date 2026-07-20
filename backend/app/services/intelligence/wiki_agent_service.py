"""Orchestrates Wiki Agent during repository indexing."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import Repository, RepositoryWikiSite, WikiClaim, WikiPage
from app.core.logger import logger
from app.services.agents.wiki_agent import WikiAgent
from app.services.intelligence.analysis_config_service import AnalysisConfigService
from app.services.intelligence.analysis_storage import (
    get_analysis_dir,
    mark_failed,
    mark_started,
    write_analysis_config,
)
from app.services.intelligence.citation_verifier import CitationVerifier
from app.services.intelligence.code_chunker import FileChunk
from app.services.intelligence.repo_attribute_extractor import extract_attributes


class WikiAgentService:
    SECTION_SLUGS = [
        ("overview", "Overview", "overview"),
        ("architecture", "Architecture", "architecture"),
        ("business_logic", "Business Logic Layer", "business_logic"),
        ("api_surface", "API Surface", "api_surface"),
        ("build_deploy", "Build & Deploy", "build_deploy"),
    ]

    def __init__(self, db: Session):
        self.db = db
        self.analysis_svc = AnalysisConfigService(db)
        self.verifier = CitationVerifier(db)

    async def generate_for_repository(
        self,
        repository: Repository,
        chunks: List[FileChunk],
        loc: int,
        index_run_id: Optional[str] = None,
        clone_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.analysis_svc.seed_defaults(repository.tenant_id)
        definitions = self.analysis_svc.list_definitions(repository.tenant_id)

        analysis_dir = get_analysis_dir(repository)
        mark_started(analysis_dir)
        write_analysis_config(analysis_dir, definitions)

        logger.info(
            f"Wiki Agent starting for {repository.github_full_name or repository.name} "
            f"→ {analysis_dir}"
        )

        # Deterministic attribute extraction from clone
        extracted = []
        if clone_path:
            extracted = extract_attributes(clone_path, definitions)

        agent = WikiAgent()
        try:
            state = await agent.process({
                "repository": {
                    "name": repository.name,
                    "url": repository.url,
                    "github_full_name": repository.github_full_name,
                    "github_org": repository.github_org,
                    "github_owner": repository.github_owner,
                    "default_branch": repository.default_branch,
                },
                "repository_id": repository.id,
                "chunks": chunks,
                "loc": loc,
                "clone_path": clone_path,
                "output_dir": analysis_dir,
                "index_run_id": index_run_id,
                "attribute_definitions": definitions,
            })
        except Exception:
            mark_failed(analysis_dir)
            raise

        wiki_json = state.get("wiki_json", {})
        wiki_html = state.get("wiki_html", "")
        sections_md = state.get("sections_md") or wiki_json.get("sections_md") or {}
        generation_source = state.get("generation_source", "wiki_agent")
        analysis_paths = state.get("analysis_paths", {})

        # Merge deterministic + LLM analysis attributes
        merged_attrs = self._merge_attributes(
            extracted, wiki_json.get("analysis_attributes") or [], definitions
        )
        wiki_json["analysis_attributes"] = merged_attrs

        # Persist analysis attributes (searchable fleet metadata)
        self.analysis_svc.save_repository_attributes(
            repository.tenant_id,
            repository.id,
            index_run_id,
            merged_attrs,
        )

        # Replace prior wiki site + pages
        self._clear_prior_wiki(repository.id)

        wiki_json["_storage"] = {
            "analysis_dir": str(analysis_dir),
            "generation_source": generation_source,
            "shell_invoked": state.get("shell_invoked", False),
            "shell_succeeded": state.get("shell_succeeded", False),
            **analysis_paths,
        }

        site = RepositoryWikiSite(
            id=str(uuid.uuid4()),
            repository_id=repository.id,
            index_run_id=index_run_id,
            title=f"{repository.name} Wiki",
            html_content=wiki_html,
            summary_json=wiki_json,
            state="draft",
            version=1,
            generated_by=generation_source,
        )
        self.db.add(site)

        for slug, title, template_type in self.SECTION_SLUGS:
            content = sections_md.get(slug) or self._default_section(slug, wiki_json)
            page = WikiPage(
                id=str(uuid.uuid4()),
                repository_id=repository.id,
                index_run_id=index_run_id,
                slug=slug,
                title=title,
                template_type=template_type,
                content_md=content,
                state="draft",
                version=1,
                freshness_at=datetime.now(),
                drift_status="pending_review",
            )
            self.db.add(page)

        self.db.flush()
        pages = (
            self.db.query(WikiPage)
            .filter(WikiPage.repository_id == repository.id)
            .all()
        )
        for page in pages:
            self.verifier.verify_page(page)

        self.db.commit()
        logger.info(
            f"Wiki Agent completed for {repository.id}: "
            f"{len(merged_attrs)} attributes, source={generation_source}, "
            f"artifacts={analysis_dir}"
        )
        return {
            "wiki_site_id": site.id,
            "attribute_count": len(merged_attrs),
            "page_count": len(pages),
            "analysis_dir": str(analysis_dir),
            "generation_source": generation_source,
            "shell_succeeded": state.get("shell_succeeded", False),
        }

    def get_wiki_site(self, repository_id: str) -> Optional[RepositoryWikiSite]:
        return (
            self.db.query(RepositoryWikiSite)
            .filter(RepositoryWikiSite.repository_id == repository_id)
            .order_by(RepositoryWikiSite.created_at.desc())
            .first()
        )

    def _clear_prior_wiki(self, repository_id: str) -> None:
        page_ids = [
            row[0]
            for row in self.db.query(WikiPage.id)
            .filter(WikiPage.repository_id == repository_id)
            .all()
        ]
        if page_ids:
            self.db.query(WikiClaim).filter(WikiClaim.page_id.in_(page_ids)).delete(
                synchronize_session=False
            )
        self.db.query(WikiPage).filter(WikiPage.repository_id == repository_id).delete()
        self.db.query(RepositoryWikiSite).filter(
            RepositoryWikiSite.repository_id == repository_id
        ).delete()

    def _merge_attributes(
        self,
        extracted: List[Any],
        llm_attrs: List[Dict],
        definitions: List[Dict],
    ) -> List[Dict[str, Any]]:
        by_key: Dict[str, Dict[str, Any]] = {}
        label_map = {d["key"]: d["label"] for d in definitions}

        for e in extracted:
            by_key[e.key] = {
                "key": e.key,
                "label": e.label or label_map.get(e.key, e.key),
                "value": e.value,
                "source_file": e.source_file,
                "line_start": e.line_start,
                "confidence": e.confidence,
            }

        for a in llm_attrs:
            key = a.get("key", "")
            if not key:
                continue
            if key in by_key and by_key[key].get("confidence") == "high":
                continue
            by_key[key] = {
                "key": key,
                "label": a.get("label") or label_map.get(key, key),
                "value": a.get("value", ""),
                "source_file": a.get("source_file"),
                "line_start": a.get("line_start"),
                "confidence": a.get("confidence", "medium"),
            }

        return list(by_key.values())

    def _default_section(self, slug: str, wiki_json: Dict) -> str:
        if slug == "overview":
            o = wiki_json.get("overview", {})
            return f"# Overview\n\n{o.get('description', '')}\n"
        if slug == "architecture":
            d = wiki_json.get("diagrams", {}).get("high_level_mermaid", "graph TD\n  A[App]")
            return f"# Architecture\n\n```mermaid\n{d}\n```\n"
        if slug == "business_logic":
            bl = wiki_json.get("business_logic_layer") or {}
            lines = [f"# Business Logic Layer\n\n{bl.get('summary', '')}\n"]
            for comp in bl.get("components") or []:
                lines.append(f"## {comp.get('name', 'Component')}\n")
                if comp.get("purpose"):
                    lines.append(f"**Purpose:** {comp['purpose']}\n")
                for wf in comp.get("workflows") or []:
                    steps = " → ".join(wf.get("steps") or [])
                    lines.append(f"- **{wf.get('operation', 'Workflow')}:** {steps}\n")
                for rule in comp.get("business_rules") or []:
                    text = rule.get("rule", rule) if isinstance(rule, dict) else rule
                    lines.append(f"- {text}\n")
            return "".join(lines) or "# Business Logic Layer\n\nNot detected.\n"
        if slug == "api_surface":
            items = wiki_json.get("api_surface") or []
            lines = "\n".join(f"- `{i.get('file', '')}`" for i in items)
            return f"# API Surface\n\n{lines or 'Not detected'}\n"
        if slug == "build_deploy":
            b = wiki_json.get("build_deploy", {})
            arts = "\n".join(f"- `{a}`" for a in (b.get("artifacts") or []))
            return f"# Build & Deploy\n\n{b.get('summary', '')}\n\n{arts}\n"
        return f"# {slug}\n"

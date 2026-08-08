"""Orchestrates Wiki Agent during repository indexing."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import Repository, RepositoryWikiSite, WikiClaim, WikiPage
from app.core.logger import logger
from app.core.secret_redaction import redact_secrets
from app.services.agents.wiki_agent import WikiAgent
from app.services.intelligence.analysis_config_service import AnalysisConfigService
from app.services.intelligence.analysis_storage import (
    META_NAME,
    get_analysis_dir,
    mark_completed,
    mark_failed,
    mark_started,
    write_analysis_config,
)
from app.services.intelligence.citation_verifier import CitationVerifier
from app.services.intelligence.code_chunker import FileChunk
from app.services.intelligence.github_credential_service import GitHubCredentialService
from app.services.intelligence.repo_attribute_extractor import extract_attributes
from app.services.intelligence.repo_clone_service import RepoCloneService
from app.services.intelligence.wiki_git_refresh import (
    load_previous_wiki_json,
    plan_wiki_refresh,
)


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

    def _resolve_clone_token(self, repository: Repository) -> Optional[str]:
        if not repository.github_credential_id:
            return None
        cred_svc = GitHubCredentialService(self.db)
        cred = cred_svc.get_credential(repository.tenant_id, repository.github_credential_id)
        if not cred:
            return None
        return cred_svc.get_token(cred)

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

        # Load prior wiki BEFORE mark_started so incremental planning can use it.
        previous_wiki = load_previous_wiki_json(analysis_dir)

        clone_svc = RepoCloneService()
        owned_clone = False
        try:
            clone_path, owned_clone = clone_svc.ensure_clone(
                repository.url,
                repository.default_branch or "main",
                token=self._resolve_clone_token(repository),
                clone_path=clone_path,
            )

            refresh_plan = plan_wiki_refresh(
                clone_path=clone_path,
                analysis_dir=analysis_dir,
            )
            git_head = refresh_plan.current_head or clone_svc.get_head_sha(clone_path)

            logger.info(
                "Wiki refresh plan for %s: mode=%s reason=%s head=%s prior=%s",
                repository.github_full_name or repository.name,
                refresh_plan.mode,
                refresh_plan.reason,
                (git_head or "")[:12],
                (refresh_plan.previous_head or "")[:12],
            )

            if refresh_plan.mode == "unchanged" and previous_wiki:
                return self._skip_unchanged_wiki(
                    repository=repository,
                    analysis_dir=analysis_dir,
                    previous_wiki=previous_wiki,
                    git_head=git_head,
                    index_run_id=index_run_id,
                    refresh_reason=refresh_plan.reason,
                )

            mark_started(analysis_dir)
            write_analysis_config(analysis_dir, definitions)

            logger.info(
                f"Wiki Agent starting for {repository.github_full_name or repository.name} "
                f"→ {analysis_dir}"
            )

            extracted = []
            if clone_path:
                extracted = extract_attributes(clone_path, definitions)

            agent = WikiAgent()
            from app.services.intelligence.wiki_generation_settings import (
                resolve_wiki_generation_settings,
            )

            gen_settings = resolve_wiki_generation_settings(self.db, repository.tenant_id)
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
                    "tenant_id": repository.tenant_id,
                    "chunks": chunks,
                    "loc": loc,
                    "clone_path": clone_path,
                    "output_dir": analysis_dir,
                    "index_run_id": index_run_id,
                    "attribute_definitions": definitions,
                    "wiki_generation_settings": gen_settings,
                    "wiki_refresh_plan": refresh_plan,
                    "previous_wiki_json": previous_wiki,
                    "git_head": git_head,
                })
            except Exception as e:
                # Preserve detail already written by WikiAgent; never wipe with empty marker
                mark_failed(analysis_dir, redact_secrets(str(e))[:4000])
                raise

            return await self._persist_wiki_result(
                repository=repository,
                state=state,
                extracted=extracted,
                definitions=definitions,
                analysis_dir=analysis_dir,
                index_run_id=index_run_id,
                git_head=git_head,
                refresh_plan=refresh_plan,
            )
        finally:
            if owned_clone and clone_path:
                clone_svc.cleanup(clone_path)

    def _skip_unchanged_wiki(
        self,
        *,
        repository: Repository,
        analysis_dir: Path,
        previous_wiki: Dict[str, Any],
        git_head: Optional[str],
        index_run_id: Optional[str],
        refresh_reason: str,
    ) -> Dict[str, Any]:
        """HEAD matches last wiki — keep existing DB wiki and bump meta only."""
        mark_completed(analysis_dir)
        meta_path = analysis_dir / META_NAME
        meta: Dict[str, Any] = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        meta.update({
            "git_head": git_head,
            "wiki_refresh_mode": "unchanged",
            "wiki_refresh_reason": refresh_reason,
            "index_run_id": index_run_id or meta.get("index_run_id"),
            "written_at": datetime.now().isoformat(),
            "generation_source": meta.get("generation_source") or "wiki_unchanged",
        })
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        site = self.get_wiki_site(repository.id)
        page_count = (
            self.db.query(WikiPage)
            .filter(WikiPage.repository_id == repository.id)
            .count()
        )
        logger.info(
            "Wiki unchanged for %s (git_head=%s) — skipped regeneration",
            repository.id,
            (git_head or "")[:12],
        )
        return {
            "wiki_site_id": site.id if site else None,
            "attribute_count": len(previous_wiki.get("analysis_attributes") or []),
            "page_count": page_count,
            "analysis_dir": str(analysis_dir),
            "generation_source": "wiki_unchanged",
            "shell_succeeded": False,
            "wiki_refresh_mode": "unchanged",
            "git_head": git_head,
        }

    async def _persist_wiki_result(
        self,
        *,
        repository: Repository,
        state: Dict[str, Any],
        extracted: List[Any],
        definitions: List[Dict],
        analysis_dir: Path,
        index_run_id: Optional[str],
        git_head: Optional[str],
        refresh_plan: Any,
    ) -> Dict[str, Any]:
        wiki_json = state.get("wiki_json", {})
        wiki_html = state.get("wiki_html", "")
        sections_md = state.get("sections_md") or wiki_json.get("sections_md") or {}
        generation_source = state.get("generation_source", "wiki_agent")
        analysis_paths = state.get("analysis_paths", {})
        wiki_md = state.get("wiki_md")

        merged_attrs = self._merge_attributes(
            extracted, wiki_json.get("analysis_attributes") or [], definitions
        )
        wiki_json["analysis_attributes"] = merged_attrs

        self.analysis_svc.save_repository_attributes(
            repository.tenant_id,
            repository.id,
            index_run_id,
            merged_attrs,
        )

        site = self._upsert_wiki_pages(
            repository=repository,
            wiki_json=wiki_json,
            wiki_html=wiki_html,
            sections_md=sections_md,
            analysis_dir=analysis_dir,
            analysis_paths=analysis_paths,
            generation_source=generation_source,
            index_run_id=index_run_id,
            git_head=git_head,
            refresh_plan=refresh_plan,
            state=state,
        )

        pages = (
            self.db.query(WikiPage)
            .filter(WikiPage.repository_id == repository.id)
            .all()
        )
        for page in pages:
            self.verifier.verify_page(page)

        self.db.commit()

        export_result = None
        try:
            from app.services.intelligence.wiki_github_export_service import (
                WikiGitHubExportService,
            )

            export_result = await WikiGitHubExportService(self.db).maybe_export_after_wiki(
                repository,
                analysis_dir=analysis_dir,
                wiki_md=wiki_md,
                sections_md=sections_md if isinstance(sections_md, dict) else None,
                index_run_id=index_run_id,
            )
        except Exception as export_err:
            logger.warning(
                "Wiki GitHub export hook failed for %s: %s",
                repository.id,
                export_err,
            )

        logger.info(
            f"Wiki Agent completed for {repository.id}: "
            f"{len(merged_attrs)} attributes, source={generation_source}, "
            f"refresh={getattr(refresh_plan, 'mode', None)}, "
            f"artifacts={analysis_dir}"
        )
        result = {
            "wiki_site_id": site.id,
            "attribute_count": len(merged_attrs),
            "page_count": len(pages),
            "analysis_dir": str(analysis_dir),
            "generation_source": generation_source,
            "shell_succeeded": state.get("shell_succeeded", False),
            "wiki_refresh_mode": getattr(refresh_plan, "mode", None),
            "git_head": git_head,
        }
        if export_result:
            result["github_export"] = export_result
        return result

    def get_wiki_site(self, repository_id: str) -> Optional[RepositoryWikiSite]:
        return (
            self.db.query(RepositoryWikiSite)
            .filter(RepositoryWikiSite.repository_id == repository_id)
            .order_by(RepositoryWikiSite.created_at.desc())
            .first()
        )


    def _upsert_wiki_pages(
        self,
        *,
        repository: Repository,
        wiki_json: Dict[str, Any],
        wiki_html: str,
        sections_md: Dict[str, Any],
        analysis_dir: Path,
        analysis_paths: Dict[str, Any],
        generation_source: str,
        index_run_id: Optional[str],
        git_head: Optional[str],
        refresh_plan: Any,
        state: Dict[str, Any],
    ) -> RepositoryWikiSite:
        """Upsert wiki by (repo, slug, content_hash) — ADR 0010 §5b."""
        import hashlib

        wiki_json["_storage"] = {
            "analysis_dir": str(analysis_dir),
            "generation_source": generation_source,
            "shell_invoked": state.get("shell_invoked", False),
            "shell_succeeded": state.get("shell_succeeded", False),
            "git_head": git_head,
            "wiki_refresh_mode": getattr(refresh_plan, "mode", None),
            **analysis_paths,
        }

        site = (
            self.db.query(RepositoryWikiSite)
            .filter(RepositoryWikiSite.repository_id == repository.id)
            .order_by(RepositoryWikiSite.created_at.desc())
            .first()
        )
        if site:
            site.index_run_id = index_run_id
            site.html_content = wiki_html
            site.summary_json = wiki_json
            site.generated_by = generation_source
            site.version = (site.version or 1) + 1
            site.state = "draft"
        else:
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

        keep_slugs = set()
        for slug, title, template_type in self.SECTION_SLUGS:
            content = sections_md.get(slug) or self._default_section(slug, wiki_json)
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            keep_slugs.add(slug)
            page = (
                self.db.query(WikiPage)
                .filter(
                    WikiPage.repository_id == repository.id,
                    WikiPage.slug == slug,
                )
                .first()
            )
            if page and (page.content_hash or "") == content_hash:
                page.index_run_id = index_run_id
                page.freshness_at = datetime.now()
                continue
            if page:
                self.db.query(WikiClaim).filter(WikiClaim.page_id == page.id).delete(
                    synchronize_session=False
                )
                page.title = title
                page.template_type = template_type
                page.content_md = content
                page.content_hash = content_hash
                page.index_run_id = index_run_id
                page.version = (page.version or 1) + 1
                page.freshness_at = datetime.now()
                page.drift_status = "pending_review"
                page.state = "draft"
            else:
                self.db.add(
                    WikiPage(
                        id=str(uuid.uuid4()),
                        repository_id=repository.id,
                        index_run_id=index_run_id,
                        slug=slug,
                        title=title,
                        template_type=template_type,
                        content_md=content,
                        content_hash=content_hash,
                        state="draft",
                        version=1,
                        freshness_at=datetime.now(),
                        drift_status="pending_review",
                    )
                )

        stale = (
            self.db.query(WikiPage)
            .filter(
                WikiPage.repository_id == repository.id,
                ~WikiPage.slug.in_(keep_slugs),
            )
            .all()
        )
        for page in stale:
            self.db.query(WikiClaim).filter(WikiClaim.page_id == page.id).delete(
                synchronize_session=False
            )
            self.db.delete(page)

        self.db.flush()
        return site

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

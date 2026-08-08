"""Repository indexing orchestration — clone, chunk, embed, wiki."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

from app.core.database import CodeChunk, IndexRun, Repository, WikiPage
from app.core.logger import logger
from app.services.intelligence.code_chunker import chunk_repository, scan_for_secrets
from app.services.intelligence.embeddings_client import get_embeddings_client
from app.services.intelligence.github_credential_service import GitHubCredentialService
from app.services.intelligence.repo_clone_service import RepoCloneService
from app.services.intelligence.wiki_agent_service import WikiAgentService


class IndexerService:
    def __init__(self, db: Session):
        self.db = db

    def start_index(self, repository: Repository) -> IndexRun:
        run = IndexRun(
            id=str(uuid.uuid4()),
            repository_id=repository.id,
            status="pending",
            progress=0,
            started_at=datetime.now(),
        )
        repository.status = "indexing"
        repository.last_index_error = None
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        logger.info(f"Index run {run.id} queued for repository {repository.id}")

        from app.services.savi_job_queue import arq_enabled, schedule_index_run

        if arq_enabled():
            schedule_index_run(run.id)

        return run

    def get_latest_run(self, repository_id: str) -> Optional[IndexRun]:
        return (
            self.db.query(IndexRun)
            .filter(IndexRun.repository_id == repository_id)
            .order_by(IndexRun.created_at.desc())
            .first()
        )

    def get_pending_runs(self, limit: int = 1) -> List[IndexRun]:
        return (
            self.db.query(IndexRun)
            .filter(IndexRun.status == "pending")
            .order_by(IndexRun.created_at.asc())
            .limit(limit)
            .all()
        )

    def _resolve_clone_token(self, repository: Repository) -> Optional[str]:
        if repository.github_credential_id:
            cred_svc = GitHubCredentialService(self.db)
            cred = cred_svc.get_credential(repository.tenant_id, repository.github_credential_id)
            if cred:
                token = cred_svc.get_token(cred)
                if token:
                    return token
        # Fallback for Build-graduated repos that used env GITHUB_TOKEN for push
        import os

        return os.getenv("GITHUB_TOKEN") or None

    async def execute_index_run(self, run: IndexRun) -> None:
        repository = self.db.query(Repository).filter(Repository.id == run.repository_id).first()
        if not repository:
            run.status = "failed"
            run.error = "Repository not found"
            run.completed_at = datetime.now()
            self.db.commit()
            return

        clone_svc = RepoCloneService()
        clone_path: Optional[str] = None
        try:
            run.status = "running"
            run.progress = 5
            repository.status = "indexing"
            self.db.commit()

            token = self._resolve_clone_token(repository)
            clone_path = clone_svc.shallow_clone(
                repository.url,
                repository.default_branch,
                token=token,
            )
            run.progress = 20
            self.db.commit()

            secrets = scan_for_secrets(clone_path)
            if secrets:
                msg = (
                    f"Secret scan failed: {len(secrets)} high-confidence finding(s). "
                    f"First: {secrets[0].file_path}:{secrets[0].line} ({secrets[0].kind})"
                )
                raise RuntimeError(msg)

            run.progress = 30
            self.db.commit()

            chunks, loc = chunk_repository(
                clone_path,
                include_globs=repository.include_globs,
                exclude_globs=repository.exclude_globs,
            )
            run.progress = 50
            run.loc = loc
            self.db.commit()

            # Replace prior chunks
            self.db.query(CodeChunk).filter(CodeChunk.repository_id == repository.id).delete()

            embedder = get_embeddings_client()
            batch_size = 32
            texts = [c.content for c in chunks]
            all_embeddings: List[List[float]] = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                vecs = await embedder.embed_texts(batch)
                all_embeddings.extend(vecs)
                run.progress = 50 + int(30 * min(i + batch_size, len(texts)) / max(len(texts), 1))
                self.db.commit()

            for chunk, embedding in zip(chunks, all_embeddings):
                self.db.add(
                    CodeChunk(
                        id=str(uuid.uuid4()),
                        repository_id=repository.id,
                        file_path=chunk.file_path,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        content=chunk.content,
                        content_hash=chunk.content_hash,
                        language=chunk.language,
                        embedding=embedding,
                    )
                )

            run.progress = 85
            self.db.commit()

            analysis_dir = None
            graph_index = None
            if clone_path:
                from app.services.intelligence.analysis_storage import (
                    get_analysis_dir,
                    migrate_legacy_analysis_dir,
                    persist_graph_index,
                )
                from app.services.intelligence.structural_extractor import (
                    build_graph_index,
                    format_call_graph_for_wiki,
                )
                from app.services.intelligence.neo4j_graph_writer import sync_graph_to_neo4j
                from app.services.intelligence.spec_drift_service import (
                    persist_specs_index,
                    scan_specs,
                )
                from app.services.tenant_config_service import TenantConfigService

                migrate_legacy_analysis_dir(repository)
                analysis_dir = get_analysis_dir(repository)
                graph_index = build_graph_index(clone_path)
                persist_graph_index(analysis_dir, graph_index.to_dict())
                sync_graph_to_neo4j(repository, run.id, graph_index)

                layer = TenantConfigService(self.db).get_spec_layer_settings(
                    repository.tenant_id
                )
                if layer["enabled"]:
                    specs = scan_specs(
                        clone_path,
                        folder=layer["specs_folder"],
                        coding_agent=layer["coding_agent"],
                    )
                    persist_specs_index(analysis_dir, specs)
                else:
                    persist_specs_index(analysis_dir, [])

                call_graph_md = format_call_graph_for_wiki(graph_index)
                if call_graph_md:
                    (analysis_dir / "call_graph_context.md").write_text(
                        call_graph_md, encoding="utf-8"
                    )

                from app.services.intelligence.blast_radius_service import BlastRadiusService

                BlastRadiusService(self.db).precompute_for_repository(
                    repository,
                    graph_index,
                    index_run_id=run.id,
                )

                from app.services.intelligence.domain_graph_service import DomainGraphService

                DomainGraphService(self.db).extract_and_persist(
                    repository,
                    clone_path,
                    index_run_id=run.id,
                )

            wiki_svc = WikiAgentService(self.db)
            await wiki_svc.generate_for_repository(
                repository, chunks, loc, index_run_id=run.id, clone_path=clone_path
            )

            if clone_path:
                DomainGraphService(self.db).enrich_architecture_page(repository)

            run.status = "completed"
            run.progress = 100
            run.completed_at = datetime.now()
            repository.status = "ready"
            repository.last_indexed_at = datetime.now()
            repository.last_index_error = None
            self.db.commit()
            logger.info(f"Index run {run.id} completed — {len(chunks)} chunks, {loc} LOC")

            try:
                from app.services.modernize.assessment_service import AssessmentService

                AssessmentService(self.db).maybe_auto_assess_repo_after_index(repository)
            except Exception as assess_err:
                logger.warning(
                    "Optional auto-assessment after index failed for %s: %s",
                    repository.id,
                    assess_err,
                )

        except Exception as e:
            logger.error(f"Index run {run.id} failed: {e}")
            run.status = "failed"
            run.error = str(e)[:2000]
            run.completed_at = datetime.now()
            repository.status = "error"
            repository.last_index_error = str(e)[:2000]
            self.db.commit()
        finally:
            if clone_path:
                clone_svc.cleanup(clone_path)

    def to_status_dict(self, repository: Repository, run: Optional[IndexRun]) -> Dict[str, Any]:
        chunk_count = (
            self.db.query(CodeChunk).filter(CodeChunk.repository_id == repository.id).count()
        )
        page_count = (
            self.db.query(WikiPage).filter(WikiPage.repository_id == repository.id).count()
        )
        return {
            "repository_id": repository.id,
            "repository_status": repository.status,
            "chunk_count": chunk_count,
            "wiki_page_count": page_count,
            "graph_stats": self._graph_stats(repository),
            "index_run": {
                "id": run.id,
                "status": run.status,
                "progress": run.progress,
                "loc": run.loc,
                "error": run.error,
                "started_at": run.started_at.isoformat() if run and run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run and run.completed_at else None,
            }
            if run
            else None,
        }

    def _graph_stats(self, repository: Repository) -> Dict[str, Any]:
        from app.services.intelligence.graph_query_service import GraphQueryService

        return GraphQueryService(self.db).get_graph_stats(repository)

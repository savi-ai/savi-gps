"""Hybrid search — vector + BM25 keyword + wiki with RRF fusion (Phase 4)."""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import CodeChunk, Repository, WikiPage
from app.services.intelligence.chat_scope import ChatScope
from app.services.intelligence.retrieval_service import RetrievalService


def _tokenize(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9_]+", text.lower()) if len(t) > 2]


def _bm25_score(query_tokens: List[str], text: str, avg_len: float, k1: float = 1.2, b: float = 0.75) -> float:
    if not query_tokens:
        return 0.0
    doc_tokens = _tokenize(text)
    if not doc_tokens:
        return 0.0
    doc_len = len(doc_tokens)
    tf_map: Dict[str, int] = {}
    for t in doc_tokens:
        tf_map[t] = tf_map.get(t, 0) + 1
    score = 0.0
    for qt in query_tokens:
        tf = tf_map.get(qt, 0)
        if tf == 0:
            continue
        idf = math.log(1 + 1)  # simplified idf per query term
        denom = tf + k1 * (1 - b + b * doc_len / max(avg_len, 1))
        score += idf * (tf * (k1 + 1)) / denom
    return score


def _rrf_merge(ranked_lists: List[List[str]], k: int = 60) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


class HybridSearchService:
    def __init__(self, db: Session):
        self.db = db
        self.retrieval = RetrievalService(db)

    async def search(
        self,
        tenant_id: str,
        query: str,
        *,
        repository_id: Optional[str] = None,
        application_id: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        if not query.strip():
            return {"query": query, "results": [], "total": 0}

        if repository_id and application_id:
            raise ValueError("Specify repository_id or application_id, not both")

        if application_id:
            scope = ChatScope.application(application_id, tenant_id)
            repo_ids = scope.resolve_repo_ids(self.db)
            if not repo_ids:
                return {"query": query, "results": [], "total": 0, "scope": "application"}
            repo_query = self.db.query(Repository).filter(
                Repository.tenant_id == tenant_id,
                Repository.id.in_(repo_ids),
            )
        else:
            repo_query = self.db.query(Repository).filter(Repository.tenant_id == tenant_id)
            if repository_id:
                repo_query = repo_query.filter(Repository.id == repository_id)

        repos = repo_query.all()

        query_tokens = _tokenize(query)
        all_results: List[Dict[str, Any]] = []
        result_map: Dict[str, Dict[str, Any]] = {}

        for repo in repos:
            if repo.status != "ready":
                continue

            vector_sources = await self.retrieval.retrieve(repo.id, query, top_k=limit)
            vector_ranked = [f"{repo.id}:{s.file_path}:{s.start_line or 0}" for s in vector_sources]

            chunks = (
                self.db.query(CodeChunk)
                .filter(CodeChunk.repository_id == repo.id)
                .all()
            )
            avg_len = sum(len(_tokenize(c.content or "")) for c in chunks) / max(len(chunks), 1)
            bm25_scored: List[tuple[float, CodeChunk]] = []
            for chunk in chunks:
                sc = _bm25_score(query_tokens, f"{chunk.file_path}\n{chunk.content}", avg_len)
                if sc > 0:
                    bm25_scored.append((sc, chunk))
            bm25_scored.sort(key=lambda x: x[0], reverse=True)
            bm25_ranked = [
                f"{repo.id}:{c.file_path}:{c.start_line}" for _, c in bm25_scored[:limit]
            ]

            wiki_pages = (
                self.db.query(WikiPage)
                .filter(WikiPage.repository_id == repo.id)
                .all()
            )
            wiki_scored: List[tuple[float, WikiPage]] = []
            for page in wiki_pages:
                sc = _bm25_score(query_tokens, f"{page.title}\n{page.content_md or ''}", 200)
                if sc > 0:
                    wiki_scored.append((sc, page))
            wiki_scored.sort(key=lambda x: x[0], reverse=True)
            wiki_ranked = [f"{repo.id}:wiki:{p.slug}" for _, p in wiki_scored[:limit]]

            fused = _rrf_merge([vector_ranked, bm25_ranked, wiki_ranked])

            for src in vector_sources:
                key = f"{repo.id}:{src.file_path}:{src.start_line or 0}"
                result_map[key] = {
                    "repository_id": repo.id,
                    "repository_name": repo.github_full_name or repo.name,
                    "type": src.source_type,
                    "title": src.title or src.file_path,
                    "file_path": src.file_path,
                    "start_line": src.start_line,
                    "end_line": src.end_line,
                    "excerpt": src.excerpt[:500],
                    "score": round(fused.get(key, 0), 4),
                }

            for sc, chunk in bm25_scored[:limit]:
                key = f"{repo.id}:{chunk.file_path}:{chunk.start_line}"
                if key not in result_map:
                    result_map[key] = {
                        "repository_id": repo.id,
                        "repository_name": repo.github_full_name or repo.name,
                        "type": "code",
                        "title": chunk.file_path,
                        "file_path": chunk.file_path,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "excerpt": (chunk.content or "")[:500],
                        "score": round(fused.get(key, sc), 4),
                    }
                else:
                    result_map[key]["score"] = round(
                        max(result_map[key]["score"], fused.get(key, 0)), 4
                    )

            for sc, page in wiki_scored[:limit]:
                key = f"{repo.id}:wiki:{page.slug}"
                path = f"wiki/{page.slug}"
                result_map[key] = {
                    "repository_id": repo.id,
                    "repository_name": repo.github_full_name or repo.name,
                    "type": "wiki",
                    "title": page.title,
                    "file_path": path,
                    "start_line": None,
                    "end_line": None,
                    "excerpt": (page.content_md or "")[:500],
                    "score": round(fused.get(key, sc), 4),
                }

        all_results = sorted(result_map.values(), key=lambda r: r["score"], reverse=True)[:limit]
        payload: Dict[str, Any] = {
            "query": query,
            "results": all_results,
            "total": len(all_results),
            "fusion": "rrf",
        }
        if application_id:
            payload["application_id"] = application_id
            payload["scope"] = "application"
        elif repository_id:
            payload["repository_id"] = repository_id
            payload["scope"] = "repository"
        else:
            payload["scope"] = "tenant"
        return payload

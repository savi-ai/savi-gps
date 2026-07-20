"""Retrieve relevant code chunks and wiki content for grounded Q&A."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import CodeChunk, RepositoryWikiSite, WikiPage
from app.services.intelligence.chat_scope import ChatScope
from app.services.intelligence.embeddings_client import get_embeddings_client


@dataclass
class RetrievedSource:
    source_type: str  # code | wiki
    file_path: str
    start_line: Optional[int]
    end_line: Optional[int]
    title: Optional[str]
    excerpt: str
    score: float
    repository_id: Optional[str] = None
    repository_name: Optional[str] = None


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _keyword_score(query: str, text: str) -> float:
    tokens = {t for t in re.findall(r"[a-z0-9_]+", query.lower()) if len(t) > 2}
    if not tokens:
        return 0.0
    hay = text.lower()
    hits = sum(1 for t in tokens if t in hay)
    return hits / len(tokens)


class RetrievalService:
    def __init__(self, db: Session):
        self.db = db

    async def retrieve(
        self,
        repository_id: str,
        query: str,
        *,
        top_k: int = 8,
        min_score: float = 0.05,
        repository_name: Optional[str] = None,
    ) -> List[RetrievedSource]:
        embedder = get_embeddings_client()
        query_vec = await embedder.embed_query(query)

        sources: List[RetrievedSource] = []

        chunks = (
            self.db.query(CodeChunk)
            .filter(
                CodeChunk.repository_id == repository_id,
                CodeChunk.embedding.isnot(None),
            )
            .all()
        )
        scored_chunks: List[tuple[float, CodeChunk]] = []
        for chunk in chunks:
            embedding = chunk.embedding
            if not embedding:
                continue
            score = _cosine_similarity(query_vec, embedding)
            if score >= min_score:
                scored_chunks.append((score, chunk))

        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        for score, chunk in scored_chunks[:top_k]:
            excerpt = (chunk.content or "")[:1200]
            sources.append(
                RetrievedSource(
                    source_type="code",
                    file_path=chunk.file_path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    title=None,
                    excerpt=excerpt,
                    score=round(score, 4),
                    repository_id=repository_id,
                    repository_name=repository_name,
                )
            )

        wiki_pages = (
            self.db.query(WikiPage)
            .filter(WikiPage.repository_id == repository_id)
            .all()
        )
        wiki_scored: List[tuple[float, WikiPage]] = []
        for page in wiki_pages:
            text = f"{page.title}\n{page.content_md or ''}"
            score = _keyword_score(query, text)
            if score > 0:
                wiki_scored.append((score, page))

        wiki_scored.sort(key=lambda x: x[0], reverse=True)
        wiki_limit = max(2, top_k // 2)
        for score, page in wiki_scored[:wiki_limit]:
            excerpt = (page.content_md or "")[:2000]
            sources.append(
                RetrievedSource(
                    source_type="wiki",
                    file_path=f"wiki/{page.slug}",
                    start_line=None,
                    end_line=None,
                    title=page.title,
                    excerpt=excerpt,
                    score=round(score, 4),
                    repository_id=repository_id,
                    repository_name=repository_name,
                )
            )

        if not sources and wiki_pages:
            for page in wiki_pages[:2]:
                sources.append(
                    RetrievedSource(
                        source_type="wiki",
                        file_path=f"wiki/{page.slug}",
                        start_line=None,
                        end_line=None,
                        title=page.title,
                        excerpt=(page.content_md or "")[:2000],
                        score=0.0,
                        repository_id=repository_id,
                        repository_name=repository_name,
                    )
                )

        return sources

    async def retrieve_for_scope(
        self,
        scope: ChatScope,
        query: str,
        *,
        top_k: int = 8,
    ) -> List[RetrievedSource]:
        repos = scope.resolve_repositories(self.db)
        ready_repos = [r for r in repos if r.status == "ready"]
        if not ready_repos:
            return []

        per_repo_k = max(2, (top_k + len(ready_repos) - 1) // len(ready_repos))
        all_sources: List[RetrievedSource] = []

        for repo in ready_repos:
            name = repo.github_full_name or repo.name
            batch = await self.retrieve(
                repo.id,
                query,
                top_k=per_repo_k,
                repository_name=name,
            )
            all_sources.extend(batch)

        all_sources.sort(key=lambda s: s.score, reverse=True)
        return all_sources[:top_k]

    def get_wiki_summary_context(self, repository_id: str) -> str:
        site = (
            self.db.query(RepositoryWikiSite)
            .filter(RepositoryWikiSite.repository_id == repository_id)
            .order_by(RepositoryWikiSite.created_at.desc())
            .first()
        )
        if not site or not site.summary_json:
            return ""
        summary = site.summary_json
        parts: List[str] = []
        overview = summary.get("overview") or {}
        if overview.get("description"):
            parts.append(f"Overview: {overview['description']}")
        bl = summary.get("business_logic_layer") or {}
        if bl.get("summary"):
            parts.append(f"Business logic: {bl['summary']}")
        for comp in (bl.get("components") or [])[:5]:
            parts.append(f"- {comp.get('name')}: {comp.get('purpose', '')}")
        return "\n".join(parts)[:4000]

    def get_wiki_summary_context_for_scope(self, scope: ChatScope) -> str:
        parts: List[str] = []
        for repo in scope.resolve_repositories(self.db):
            block = self.get_wiki_summary_context(repo.id)
            if block:
                name = repo.github_full_name or repo.name
                parts.append(f"### {name}\n{block}")
        return "\n\n".join(parts)[:8000]

    @staticmethod
    def sources_to_dicts(sources: List[RetrievedSource]) -> List[Dict[str, Any]]:
        return [
            {
                "type": s.source_type,
                "file_path": s.file_path,
                "start_line": s.start_line,
                "end_line": s.end_line,
                "title": s.title,
                "excerpt": s.excerpt,
                "score": s.score,
                "repository_id": s.repository_id,
                "repository_name": s.repository_name,
            }
            for s in sources
        ]

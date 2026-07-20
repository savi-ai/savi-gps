"""Grounded wiki chat — RAG over indexed code + wiki pages."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import Repository
from app.core.llm_client import get_llm_client
from app.core.logger import logger
from app.services.intelligence.chat_scope import ChatScope
from app.services.intelligence.graph_query_service import GraphQueryService
from app.services.intelligence.retrieval_service import RetrievalService, RetrievedSource

CITATION_PATTERN = re.compile(r"`([^`\n]+?)(?::(\d+)(?:-(\d+))?)?`")


class WikiChatService:
    SYSTEM_PROMPT_REPO = """You are a helpful assistant answering questions about a software repository and its wiki documentation.

Rules:
- Answer ONLY using the provided context (code excerpts, wiki pages, summary).
- Cite evidence inline using backticks: `path/to/file.ext:42` or `wiki/slug`.
- If the context does not contain enough information, say "I don't have enough indexed information to answer that" and suggest re-indexing or checking a specific file.
- Be concise but thorough. Use bullet lists for multi-step flows.
- Do not invent APIs, files, or business rules not present in the context."""

    SYSTEM_PROMPT_SCOPE = """You are a helpful assistant answering questions about a software application that may span multiple repositories.

Rules:
- Answer ONLY using the provided context (code excerpts, wiki pages, summaries).
- Cite evidence inline with repository provenance: `repo_name:path/to/file.ext:42` or `repo_name:wiki/slug`.
- When describing cross-repo flows, explicitly name which repository each piece comes from.
- If the context does not contain enough information, say so and suggest which repository may need re-indexing.
- Be concise but thorough. Use bullet lists for multi-step flows.
- Do not invent APIs, files, or business rules not present in the context."""

    def __init__(self, db: Session):
        self.db = db
        self.retrieval = RetrievalService(db)

    async def ask(
        self,
        repository: Repository,
        messages: List[Dict[str, str]],
        *,
        top_k: int = 8,
        page_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        scope = ChatScope.repo(repository.id, repository.tenant_id)
        return await self.ask_scope(scope, messages, top_k=top_k, page_context=page_context)

    async def ask_scope(
        self,
        scope: ChatScope,
        messages: List[Dict[str, str]],
        *,
        top_k: int = 8,
        page_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not messages:
            raise ValueError("messages required")

        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        if not last_user.strip():
            raise ValueError("Last user message is empty")

        repos = scope.resolve_repositories(self.db)
        if not repos:
            raise ValueError("No repositories in scope")

        sources = await self.retrieval.retrieve_for_scope(scope, last_user, top_k=top_k)
        wiki_summary = self.retrieval.get_wiki_summary_context_for_scope(scope)

        graph_block = ""
        graph_svc = GraphQueryService(self.db)
        if graph_svc.is_graph_question(last_user):
            symbol = graph_svc.extract_symbol_from_question(last_user)
            if symbol:
                for repo in repos:
                    if repo.status != "ready":
                        continue
                    block = graph_svc.format_callers_context(repo, symbol)
                    if block:
                        name = repo.github_full_name or repo.name
                        graph_block = f"### Graph ({name})\n{block}"
                        break

        if not sources and not wiki_summary and not graph_block:
            label = scope.label(self.db)
            return {
                "answer": (
                    f"Scope '{label}' has no indexed content yet. "
                    "Run indexing on member repositories, then try again."
                ),
                "sources": [],
                "citations": [],
                "scope": {"type": scope.type, "id": scope.id},
            }

        multi_repo = len(repos) > 1 or scope.type != "repo"
        context_block = self._build_context(sources, wiki_summary, page_context, graph_block, multi_repo)
        system_prompt = self.SYSTEM_PROMPT_SCOPE if multi_repo else self.SYSTEM_PROMPT_REPO
        scope_label = scope.label(self.db)

        llm_messages = [{"role": "system", "content": system_prompt}]
        for msg in messages[:-1]:
            if msg.get("role") in ("user", "assistant") and msg.get("content"):
                llm_messages.append({"role": msg["role"], "content": msg["content"]})

        llm_messages.append({
            "role": "user",
            "content": (
                f"Scope: {scope_label}\n\n"
                f"--- CONTEXT ---\n{context_block}\n--- END CONTEXT ---\n\n"
                f"Question: {last_user}"
            ),
        })

        try:
            llm = get_llm_client()
            answer = await llm.chat(llm_messages, max_tokens=4096, temperature=0.3)
        except Exception as e:
            logger.error(f"Wiki chat LLM error: {e}")
            raise

        citations = self._extract_citations(answer)
        return {
            "answer": answer.strip(),
            "sources": RetrievalService.sources_to_dicts(sources),
            "citations": citations,
            "scope": {"type": scope.type, "id": scope.id, "label": scope_label},
        }

    def _build_context(
        self,
        sources: List[RetrievedSource],
        wiki_summary: str,
        page_context: Optional[str],
        graph_block: str = "",
        multi_repo: bool = False,
    ) -> str:
        parts: List[str] = []
        if graph_block:
            parts.append(graph_block + "\n")
        if wiki_summary:
            parts.append(f"## Wiki summary\n{wiki_summary}\n")
        if page_context:
            parts.append(f"## Current wiki page\n{page_context[:3000]}\n")

        for src in sources:
            repo_prefix = ""
            if multi_repo and src.repository_name:
                repo_prefix = f"[{src.repository_name}] "
            if src.source_type == "wiki":
                cite = f"{src.repository_name}:{src.file_path}" if multi_repo and src.repository_name else src.file_path
                parts.append(
                    f"## Wiki: {repo_prefix}{src.title or src.file_path}\n"
                    f"Source: `{cite}`\n{src.excerpt}\n"
                )
            else:
                loc = f":{src.start_line}" if src.start_line else ""
                cite_path = src.file_path
                if multi_repo and src.repository_name:
                    cite_path = f"{src.repository_name}:{src.file_path}"
                parts.append(
                    f"## Code: `{cite_path}{loc}`\n{src.excerpt}\n"
                )
        return "\n".join(parts)[:24000]

    @staticmethod
    def _extract_citations(text: str) -> List[str]:
        found: List[str] = []
        for match in CITATION_PATTERN.finditer(text):
            path = match.group(1)
            line = match.group(2)
            cite = f"{path}:{line}" if line else path
            if cite not in found:
                found.append(cite)
        return found

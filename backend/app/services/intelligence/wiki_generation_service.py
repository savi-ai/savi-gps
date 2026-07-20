"""Wiki page generation from indexed repository content."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

from app.core.database import Repository, WikiClaim, WikiPage
from app.core.logger import logger
from app.services.intelligence.code_chunker import FileChunk
from app.services.intelligence.citation_verifier import CitationVerifier

WIKI_TEMPLATES = [
    ("overview", "Overview"),
    ("architecture", "Architecture"),
    ("api_surface", "API Surface"),
    ("build_deploy", "Build & Deploy"),
]


class WikiGenerationService:
    def __init__(self, db: Optional[Session] = None):
        self.db = db

    def list_page_templates(self) -> List[str]:
        return [t[0] for t in WIKI_TEMPLATES]

    def list_pages_for_repo(self, repository_id: str) -> List[Dict[str, Any]]:
        if not self.db:
            return self._stub_pages()
        pages = (
            self.db.query(WikiPage)
            .filter(WikiPage.repository_id == repository_id)
            .order_by(WikiPage.title.asc())
            .all()
        )
        return [self._page_dict(p) for p in pages]

    def get_page(self, repository_id: str, slug: str) -> Optional[WikiPage]:
        if not self.db:
            return None
        return (
            self.db.query(WikiPage)
            .filter(WikiPage.repository_id == repository_id, WikiPage.slug == slug)
            .first()
        )

    def _page_dict(self, page: WikiPage) -> Dict[str, Any]:
        return {
            "slug": page.slug,
            "title": page.title,
            "template_type": page.template_type,
            "content_md": page.content_md,
            "mermaid": page.mermaid,
            "state": page.state,
            "version": page.version,
            "freshness_at": page.freshness_at.isoformat() if page.freshness_at else None,
        }

    def _stub_pages(self) -> List[Dict[str, Any]]:
        return [
            {
                "slug": tpl,
                "title": title,
                "template_type": tpl,
                "state": "draft",
                "message": "Run indexing to generate wiki pages",
            }
            for tpl, title in WIKI_TEMPLATES
        ]

    async def generate_for_repository(
        self,
        repository: Repository,
        chunks: List[FileChunk],
        loc: int,
        index_run_id: Optional[str] = None,
    ) -> None:
        if not self.db:
            return

        page_ids = [
            row[0]
            for row in self.db.query(WikiPage.id)
            .filter(WikiPage.repository_id == repository.id)
            .all()
        ]
        if page_ids:
            self.db.query(WikiClaim).filter(WikiClaim.page_id.in_(page_ids)).delete(
                synchronize_session=False
            )
        self.db.query(WikiPage).filter(WikiPage.repository_id == repository.id).delete()

        lang_counts = Counter(c.language or "unknown" for c in chunks)
        top_dirs = Counter(c.file_path.split("/")[0] for c in chunks if "/" in c.file_path)
        file_count = len({c.file_path for c in chunks})

        overview_md = self._build_overview(repository, loc, file_count, lang_counts, top_dirs)
        self._upsert_page(repository.id, "overview", "Overview", "overview", overview_md, index_run_id)

        arch_md = self._build_architecture(top_dirs, chunks)
        self._upsert_page(repository.id, "architecture", "Architecture", "architecture", arch_md, index_run_id)

        api_md = self._build_api_surface(chunks)
        self._upsert_page(repository.id, "api_surface", "API Surface", "api_surface", api_md, index_run_id)

        deploy_md = self._build_deploy_hints(chunks)
        self._upsert_page(repository.id, "build_deploy", "Build & Deploy", "build_deploy", deploy_md, index_run_id)

        verifier = CitationVerifier(self.db)
        pages = (
            self.db.query(WikiPage)
            .filter(WikiPage.repository_id == repository.id)
            .all()
        )
        for page in pages:
            verifier.verify_page(page)

        self.db.commit()
        logger.info(f"Generated wiki pages for repository {repository.id}")

    def _upsert_page(
        self,
        repository_id: str,
        slug: str,
        title: str,
        template_type: str,
        content_md: str,
        index_run_id: Optional[str] = None,
    ) -> None:
        page = WikiPage(
            id=str(uuid.uuid4()),
            repository_id=repository_id,
            index_run_id=index_run_id,
            slug=slug,
            title=title,
            template_type=template_type,
            content_md=content_md,
            state="draft",
            version=1,
            freshness_at=datetime.now(),
            drift_status="pending_review",
        )
        self.db.add(page)

    def _build_overview(
        self,
        repo: Repository,
        loc: int,
        file_count: int,
        langs: Counter,
        dirs: Counter,
    ) -> str:
        lang_lines = "\n".join(f"- **{lang}**: {count} chunks" for lang, count in langs.most_common(8))
        dir_lines = "\n".join(f"- `{d}/` ({c} files)" for d, c in dirs.most_common(12))
        return f"""# {repo.name}

> Auto-generated overview from indexed source at `{repo.github_full_name or repo.url}`.

## Repository facts

| Field | Value |
|-------|-------|
| URL | {repo.url} |
| Default branch | `{repo.default_branch}` |
| Lines of code (approx) | {loc:,} |
| Indexed files | {file_count} |

## Languages detected

{lang_lines or "- No language metadata"}

## Top-level directories

{dir_lines or "- Flat repository structure"}

## Next steps

- Review **Architecture** and **API Surface** pages for structural detail.
- Use **Chat** (Phase 1) for grounded Q&A with citations.
"""

    def _build_architecture(self, dirs: Counter, chunks: List[FileChunk]) -> str:
        mermaid = "graph TD\n"
        for d, _ in dirs.most_common(8):
            safe = d.replace("-", "_").replace(".", "_")
            mermaid += f"  root --> {safe}[{d}]\n"
        if mermaid == "graph TD\n":
            mermaid += "  root[Repository Root]\n"

        sample_files = sorted({c.file_path for c in chunks})[:20]
        file_list = "\n".join(f"- `{f}`" for f in sample_files)
        return f"""# Architecture

## Component map (inferred from directories)

```mermaid
{mermaid.strip()}
```

## Key files (sample)

{file_list}
"""

    def _build_api_surface(self, chunks: List[FileChunk]) -> str:
        api_files = [
            c.file_path
            for c in chunks
            if any(
                x in c.file_path.lower()
                for x in ("router", "routes", "api/", "controller", "endpoint", "handler")
            )
        ]
        unique = sorted(set(api_files))[:25]
        if not unique:
            return "# API Surface\n\nNo obvious API/router files detected in the index. Review manually or re-index after adding route modules.\n"
        lines = "\n".join(f"- `{f}`" for f in unique)
        return f"""# API Surface

Files likely related to HTTP/API endpoints:

{lines}
"""

    def _build_deploy_hints(self, chunks: List[FileChunk]) -> str:
        deploy_files = sorted(
            {
                c.file_path
                for c in chunks
                if any(
                    x in c.file_path.lower()
                    for x in (
                        "dockerfile",
                        "docker-compose",
                        "helm/",
                        "terraform/",
                        ".github/workflows",
                        "Makefile",
                        "requirements.txt",
                        "package.json",
                    )
                )
            }
        )[:20]
        if not deploy_files:
            return "# Build & Deploy\n\nNo Dockerfile, CI, or IaC files detected in the index.\n"
        lines = "\n".join(f"- `{f}`" for f in deploy_files)
        return f"""# Build & Deploy

Detected build/deploy artifacts:

{lines}
"""

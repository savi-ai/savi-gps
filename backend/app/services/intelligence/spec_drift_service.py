"""Kiro spec discovery and drift signals (Phase 4 MVP)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import Repository, WikiPage
from app.services.intelligence.analysis_storage import SPECS_INDEX_NAME, resolve_analysis_dir


@dataclass
class SpecFile:
    path: str
    name: str
    category: str  # requirements, design, tasks, other
    size_bytes: int
    excerpt: str = ""


def scan_kiro_specs(clone_path: str, max_files: int = 50) -> List[SpecFile]:
    root = Path(clone_path)
    specs: List[SpecFile] = []

    for pattern in (".kiro/specs/**", ".kiro/**/*.md", "kiro/specs/**"):
        for path in root.glob(pattern):
            if not path.is_file() or path.suffix.lower() not in (".md", ".txt", ".yaml", ".yml"):
                continue
            rel = path.relative_to(root).as_posix()
            category = "other"
            lower = rel.lower()
            if "requirement" in lower:
                category = "requirements"
            elif "design" in lower:
                category = "design"
            elif "task" in lower:
                category = "tasks"

            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            specs.append(
                SpecFile(
                    path=rel,
                    name=path.name,
                    category=category,
                    size_bytes=path.stat().st_size,
                    excerpt=text[:400].strip(),
                )
            )
            if len(specs) >= max_files:
                break
        if len(specs) >= max_files:
            break

    return specs


def persist_specs_index(analysis_dir: Path, specs: List[SpecFile]) -> None:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    payload = {"specs": [asdict(s) for s in specs], "count": len(specs)}
    (analysis_dir / SPECS_INDEX_NAME).write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def load_specs_index(repository: Repository) -> List[Dict[str, Any]]:
    path = resolve_analysis_dir(repository) / SPECS_INDEX_NAME
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("specs") or []
    except (json.JSONDecodeError, OSError):
        return []


class SpecDriftService:
    def __init__(self, db: Session):
        self.db = db

    def list_specs_for_tenant(
        self, tenant_id: str, repository_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        from app.core.database import Repository as RepoModel

        query = self.db.query(RepoModel).filter(RepoModel.tenant_id == tenant_id)
        if repository_id:
            query = query.filter(RepoModel.id == repository_id)

        rows: List[Dict[str, Any]] = []
        for repo in query.all():
            for spec in load_specs_index(repo):
                rows.append(
                    {
                        **spec,
                        "repository_id": repo.id,
                        "repository_name": repo.github_full_name or repo.name,
                    }
                )
        return rows

    def drift_summary(self, repository: Repository) -> Dict[str, Any]:
        specs = load_specs_index(repository)
        pages = (
            self.db.query(WikiPage)
            .filter(WikiPage.repository_id == repository.id)
            .all()
        )
        stale_pages = sum(1 for p in pages if p.drift_status == "stale")
        pending = sum(1 for p in pages if p.drift_status == "pending_review")

        return {
            "repository_id": repository.id,
            "spec_count": len(specs),
            "specs": specs,
            "wiki_pages": len(pages),
            "wiki_stale": stale_pages,
            "wiki_pending_review": pending,
            "has_kiro_specs": len(specs) > 0,
            "drift_status": (
                "stale"
                if stale_pages
                else "pending_review"
                if pending
                else "none"
                if pages
                else "unknown"
            ),
        }

"""Spec discovery and drift signals (agent-aware, folder-configurable)."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import Repository, WikiPage
from app.services.intelligence.analysis_storage import SPECS_INDEX_NAME, resolve_analysis_dir

CODING_AGENTS = ("kiro", "github_copilot", "cursor", "claude_code")

# Suggested roots when the admin picks an agent (folder remains overridable).
AGENT_DEFAULT_FOLDERS = {
    "kiro": ".kiro",
    "github_copilot": ".github",
    "cursor": ".cursor",
    "claude_code": ".claude",
}

_ALLOWED_SUFFIXES = {".md", ".txt", ".yaml", ".yml", ".mdc"}


@dataclass
class SpecFile:
    path: str
    name: str
    category: str  # requirements, design, tasks, other
    size_bytes: int
    excerpt: str = ""


def normalize_specs_folder(folder: Optional[str], default: str = ".github") -> str:
    """Sanitize a repo-relative specs folder (no abs paths / traversal)."""
    raw = (folder or default).strip().replace("\\", "/")
    if not raw or raw.startswith("/") or raw.startswith("~"):
        return default
    while raw.startswith("./"):
        raw = raw[2:]
    while "//" in raw:
        raw = raw.replace("//", "/")
    raw = raw.rstrip("/")
    if not raw or ".." in raw.split("/"):
        return default
    # Allow leading dot-dirs like .github / .kiro
    if not re.fullmatch(r"\.?[A-Za-z0-9._\-]+(?:/\.?[A-Za-z0-9._\-]+)*", raw):
        return default
    return raw


def _categorize(rel: str) -> str:
    lower = rel.lower()
    if "requirement" in lower:
        return "requirements"
    if "design" in lower:
        return "design"
    if "task" in lower:
        return "tasks"
    if "prompt" in lower or "instruction" in lower or "rule" in lower:
        return "instructions"
    return "other"


def _collect_from_glob(
    root: Path, pattern: str, specs: List[SpecFile], max_files: int, seen: set
) -> None:
    for path in root.glob(pattern):
        if len(specs) >= max_files:
            return
        if not path.is_file() or path.suffix.lower() not in _ALLOWED_SUFFIXES:
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel in seen:
            continue
        seen.add(rel)
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        specs.append(
            SpecFile(
                path=rel,
                name=path.name,
                category=_categorize(rel),
                size_bytes=path.stat().st_size,
                excerpt=text[:400].strip(),
            )
        )


def scan_specs(
    clone_path: str,
    folder: str = ".github",
    coding_agent: str = "github_copilot",
    max_files: int = 50,
) -> List[SpecFile]:
    """Scan the configured specs folder (plus light agent-specific extras)."""
    root = Path(clone_path)
    if not root.is_dir():
        return []

    folder = normalize_specs_folder(folder)
    agent = coding_agent if coding_agent in CODING_AGENTS else "github_copilot"
    specs: List[SpecFile] = []
    seen: set = set()

    patterns = [
        f"{folder}/**/*.md",
        f"{folder}/**/*.txt",
        f"{folder}/**/*.yaml",
        f"{folder}/**/*.yml",
        f"{folder}/**/*.mdc",
    ]

    # Agent-specific extras outside the folder (common convention files).
    if agent == "kiro" and folder != ".kiro":
        patterns.extend([".kiro/specs/**/*.md", ".kiro/steering/**/*.md"])
    elif agent == "claude_code":
        patterns.append("CLAUDE.md")
        if folder != ".claude":
            patterns.extend([".claude/**/*.md", ".claude/**/*.mdc"])
    elif agent == "cursor":
        patterns.append(".cursorrules")
        if folder != ".cursor":
            patterns.extend([".cursor/rules/**/*.md", ".cursor/rules/**/*.mdc"])
    elif agent == "github_copilot" and folder != ".github":
        patterns.extend(
            [
                ".github/copilot-instructions.md",
                ".github/prompts/**/*.md",
                ".github/instructions/**/*.md",
            ]
        )

    for pattern in patterns:
        _collect_from_glob(root, pattern, specs, max_files, seen)
        if len(specs) >= max_files:
            break

    return specs


def scan_kiro_specs(clone_path: str, max_files: int = 50) -> List[SpecFile]:
    """Backward-compatible alias — scans ``.kiro`` as Kiro specs."""
    return scan_specs(
        clone_path, folder=".kiro", coding_agent="kiro", max_files=max_files
    )


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
        from app.services.tenant_config_service import TenantConfigService

        specs = load_specs_index(repository)
        pages = (
            self.db.query(WikiPage)
            .filter(WikiPage.repository_id == repository.id)
            .all()
        )
        stale_pages = sum(1 for p in pages if p.drift_status == "stale")
        pending = sum(1 for p in pages if p.drift_status == "pending_review")
        layer = TenantConfigService(self.db).get_spec_layer_settings(
            repository.tenant_id
        )
        has_specs = len(specs) > 0

        return {
            "repository_id": repository.id,
            "spec_count": len(specs),
            "specs": specs,
            "wiki_pages": len(pages),
            "wiki_stale": stale_pages,
            "wiki_pending_review": pending,
            "has_specs": has_specs,
            "has_kiro_specs": has_specs,  # backward-compatible alias
            "spec_layer": layer,
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

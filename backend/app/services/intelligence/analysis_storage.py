"""Filesystem layout for repository analysis artifacts.

Canonical layout (Phase 0+):
  {STORAGE_BASE_PATH}/tenants/{tenant_id}/repos/{repository_id}/analysis/

Legacy layout (read fallback only):
  backend/app/scripts/temp_store/analysis/<ORG>/<REPO>/

Files in analysis/:
  wiki_result.json, wiki_site.html, wiki_site.md
  graph_index.json, specs_index.json, call_graph_context.md
  analysis_config.json, index_run_meta.json
  views/  — derived analysis views (blast-radius, domain graph, …)
  WIKI_STARTED | WIKI_COMPLETED | WIKI_FAILED
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings
from app.core.database import Repository
from app.core.logger import logger

# Legacy path used before Phase 0 (read fallback + one-time migration)
LEGACY_ANALYSIS_ROOT = (
    Path(__file__).resolve().parents[2] / "scripts" / "temp_store" / "analysis"
)

WIKI_JSON_NAME = "wiki_result.json"
WIKI_HTML_NAME = "wiki_site.html"
WIKI_MD_NAME = "wiki_site.md"
CONFIG_NAME = "analysis_config.json"
GRAPH_INDEX_NAME = "graph_index.json"
SPECS_INDEX_NAME = "specs_index.json"
META_NAME = "index_run_meta.json"
CALL_GRAPH_CONTEXT_NAME = "call_graph_context.md"
VIEWS_DIR_NAME = "views"


def _iso_timestamp() -> str:
    return datetime.now().isoformat()


def sanitize_path_segment(value: str) -> str:
    """Safe folder name segment."""
    cleaned = re.sub(r"[^\w\-.]", "_", (value or "").strip())
    return (cleaned[:120] or "unknown")


def get_storage_root() -> Path:
    """Align with StorageService default: STORAGE_BASE_PATH or backend/storage."""
    if settings.STORAGE_BASE_PATH:
        return Path(settings.STORAGE_BASE_PATH)
    backend_root = Path(__file__).resolve().parents[3]
    return backend_root / "storage"


def resolve_org_repo(repository: Repository) -> Tuple[str, str]:
    """Resolve ORG and REPO folder names from repository metadata (legacy paths)."""
    if repository.github_full_name and "/" in repository.github_full_name:
        owner, repo = repository.github_full_name.split("/", 1)
        org = repository.github_org or owner
        return sanitize_path_segment(org), sanitize_path_segment(repo)

    org = repository.github_org or repository.github_owner or "unknown-org"
    repo = repository.github_repo or repository.name or "unknown-repo"
    return sanitize_path_segment(org), sanitize_path_segment(repo)


def get_legacy_analysis_dir(repository: Repository) -> Path:
    """Legacy temp_store/analysis/<ORG>/<REPO> (pre–Phase 0)."""
    org, repo = resolve_org_repo(repository)
    return LEGACY_ANALYSIS_ROOT / org / repo


def get_analysis_dir(repository: Repository) -> Path:
    """Canonical write path: tenants/{tenant_id}/repos/{repo_id}/analysis/"""
    tenant_id = sanitize_path_segment(repository.tenant_id or "unknown-tenant")
    repo_id = sanitize_path_segment(repository.id)
    return (
        get_storage_root()
        / "tenants"
        / tenant_id
        / "repos"
        / repo_id
        / "analysis"
    )


def get_analysis_views_dir(repository: Repository) -> Path:
    """Subdirectory for derived analysis views (blast-radius, domain graph, …)."""
    return get_analysis_dir(repository) / VIEWS_DIR_NAME


def get_application_root(tenant_id: str, application_id: str) -> Path:
    """Root for application-scoped storage: tenants/{tid}/applications/{aid}/."""
    tid = sanitize_path_segment(tenant_id or "unknown-tenant")
    aid = sanitize_path_segment(application_id)
    return get_storage_root() / "tenants" / tid / "applications" / aid


def get_application_analysis_dir(tenant_id: str, application_id: str) -> Path:
    """Application-scoped analysis artifacts (service map, wiki, …)."""
    return get_application_root(tenant_id, application_id) / "analysis"


def get_application_workspace_dir(tenant_id: str, application_id: str) -> Path:
    """Multi-repo clone root for application wiki generation."""
    return get_application_root(tenant_id, application_id) / "workspace"


def get_application_workspace_repos_dir(tenant_id: str, application_id: str) -> Path:
    """Member clones live under workspace/repos/{slug}/."""
    return get_application_workspace_dir(tenant_id, application_id) / "repos"


def get_application_wiki_status(tenant_id: str, application_id: str) -> Dict[str, Any]:
    """Return wiki marker status for an application analysis dir."""
    analysis_dir = get_application_analysis_dir(tenant_id, application_id)
    status = "idle"
    detail = ""
    if (analysis_dir / "WIKI_STARTED").is_file():
        status = "running"
        detail = (analysis_dir / "WIKI_STARTED").read_text(encoding="utf-8").strip()
    elif (analysis_dir / "WIKI_FAILED").is_file():
        status = "failed"
        detail = (analysis_dir / "WIKI_FAILED").read_text(encoding="utf-8").strip()
    elif (analysis_dir / "WIKI_COMPLETED").is_file():
        status = "completed"
        detail = (analysis_dir / "WIKI_COMPLETED").read_text(encoding="utf-8").strip()
    return {
        "status": status,
        "detail": detail,
        "analysis_dir": str(analysis_dir),
        "has_wiki_json": (analysis_dir / WIKI_JSON_NAME).is_file(),
        "has_wiki_html": (analysis_dir / WIKI_HTML_NAME).is_file(),
        "has_wiki_md": (analysis_dir / WIKI_MD_NAME).is_file(),
    }


def _dir_has_artifacts(path: Path) -> bool:
    if not path.is_dir():
        return False
    markers = (
        WIKI_JSON_NAME,
        GRAPH_INDEX_NAME,
        SPECS_INDEX_NAME,
        WIKI_HTML_NAME,
        "WIKI_COMPLETED",
    )
    return any((path / name).exists() for name in markers)


def resolve_analysis_dir(repository: Repository) -> Path:
    """Read path: prefer canonical tenant storage; fall back to legacy temp_store."""
    canonical = get_analysis_dir(repository)
    if _dir_has_artifacts(canonical):
        return canonical
    legacy = get_legacy_analysis_dir(repository)
    if _dir_has_artifacts(legacy):
        return legacy
    return canonical


def migrate_legacy_analysis_dir(repository: Repository, *, dry_run: bool = False) -> bool:
    """Copy legacy analysis artifacts into canonical tenant storage if needed."""
    legacy = get_legacy_analysis_dir(repository)
    if not _dir_has_artifacts(legacy):
        return False

    canonical = get_analysis_dir(repository)
    if _dir_has_artifacts(canonical):
        logger.info(
            "Skip migrate %s: canonical analysis dir already has artifacts",
            repository.id,
        )
        return False

    if dry_run:
        logger.info("Would migrate %s: %s -> %s", repository.id, legacy, canonical)
        return True

    canonical.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(legacy, canonical, dirs_exist_ok=True)
    logger.info("Migrated analysis artifacts for %s: %s -> %s", repository.id, legacy, canonical)
    return True


def mark_started(analysis_dir: Path) -> None:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "WIKI_STARTED").write_text(_iso_timestamp(), encoding="utf-8")
    for marker in ("WIKI_COMPLETED", "WIKI_FAILED"):
        path = analysis_dir / marker
        if path.exists():
            path.unlink()


def mark_completed(analysis_dir: Path) -> None:
    (analysis_dir / "WIKI_STARTED").unlink(missing_ok=True)
    (analysis_dir / "WIKI_FAILED").unlink(missing_ok=True)
    (analysis_dir / "WIKI_COMPLETED").write_text(_iso_timestamp(), encoding="utf-8")


def mark_failed(analysis_dir: Path, error: str = "") -> None:
    (analysis_dir / "WIKI_STARTED").unlink(missing_ok=True)
    content = _iso_timestamp()
    if error:
        content = f"{content}\n{error}"
    (analysis_dir / "WIKI_FAILED").write_text(content, encoding="utf-8")


def write_analysis_config(analysis_dir: Path, definitions: list) -> Path:
    path = analysis_dir / CONFIG_NAME
    path.write_text(json.dumps(definitions, indent=2), encoding="utf-8")
    return path


def persist_analysis_artifacts(
    analysis_dir: Path,
    wiki_json: Dict[str, Any],
    wiki_html: str,
    *,
    wiki_md: Optional[str] = None,
    index_run_id: Optional[str] = None,
    generation_source: str = "wiki_agent",
    shell_invoked: bool = False,
    shell_succeeded: bool = False,
    repository_id: Optional[str] = None,
    mark_complete: bool = True,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Write wiki JSON/HTML/MD and metadata to the analysis directory."""
    analysis_dir.mkdir(parents=True, exist_ok=True)

    json_path = analysis_dir / WIKI_JSON_NAME
    html_path = analysis_dir / WIKI_HTML_NAME
    md_path = analysis_dir / WIKI_MD_NAME
    meta_path = analysis_dir / META_NAME

    json_path.write_text(json.dumps(wiki_json, indent=2), encoding="utf-8")
    html_path.write_text(wiki_html, encoding="utf-8")
    if wiki_md:
        md_path.write_text(wiki_md, encoding="utf-8")

    meta = {
        "repository_id": repository_id,
        "index_run_id": index_run_id,
        "generation_source": generation_source,
        "shell_invoked": shell_invoked,
        "shell_succeeded": shell_succeeded,
        "written_at": datetime.now().isoformat(),
        "storage_layout": "tenant_scoped",
        "paths": {
            "wiki_json": str(json_path),
            "wiki_html": str(html_path),
            "wiki_md": str(md_path) if wiki_md else None,
            "analysis_dir": str(analysis_dir),
        },
    }
    if extra_meta:
        meta.update(extra_meta)
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    if mark_complete:
        mark_completed(analysis_dir)
    elif generation_source == "wiki_agent_fallback":
        mark_failed(analysis_dir, "Wiki generation used shallow fallback — shell and LLM paths failed")

    logger.info(
        f"Wiki artifacts saved to {analysis_dir} "
        f"(source={generation_source}, shell_ok={shell_succeeded})"
    )
    return {
        "analysis_dir": str(analysis_dir),
        "wiki_json": str(json_path),
        "wiki_html": str(html_path),
        "wiki_md": str(md_path) if wiki_md else "",
        "index_run_meta": str(meta_path),
    }


def load_analysis_artifacts(analysis_dir: Path) -> Optional[Dict[str, Any]]:
    """Load wiki artifacts from disk if present."""
    json_path = analysis_dir / WIKI_JSON_NAME
    html_path = analysis_dir / WIKI_HTML_NAME
    if not json_path.is_file():
        return None
    result: Dict[str, Any] = {
        "wiki_json": json.loads(json_path.read_text(encoding="utf-8")),
        "wiki_html": html_path.read_text(encoding="utf-8") if html_path.is_file() else None,
        "analysis_dir": str(analysis_dir),
    }
    meta_path = analysis_dir / META_NAME
    if meta_path.is_file():
        result["meta"] = json.loads(meta_path.read_text(encoding="utf-8"))
    return result


def persist_graph_index(analysis_dir: Path, graph_dict: Dict[str, Any]) -> Path:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    path = analysis_dir / GRAPH_INDEX_NAME
    path.write_text(json.dumps(graph_dict, indent=2), encoding="utf-8")
    return path

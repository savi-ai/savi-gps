"""Filesystem layout for fix and modernization execution workspaces (W8).

Fix plan (repo-scoped):
  tenants/{tenant_id}/repos/{repository_id}/executions/{plan_id}/

Modernization plan (application-scoped):
  tenants/{tenant_id}/applications/{application_id}/executions/{plan_id}/
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from app.services.intelligence.analysis_storage import get_storage_root, sanitize_path_segment

MANIFEST_NAME = "MANIFEST.json"
MANIFEST_VERSION = 1

FIX_SUBDIRS = ("brief", "source", "agent", "test", "push")
MODERNIZE_SUBDIRS = ("context", "stages", "targets", "agent", "push")

FIX_STAGES = ("fix", "code", "test", "push", "pr")
MODERNIZE_STAGES = ("requirements", "tasks", "architecture", "code", "test", "push")


def reset_stages_for_rerun(
    manifest: Dict[str, Any], stages: list[str], from_index: int
) -> list[str]:
    """Reset target stage and downstream stages so a completed stage can run again."""
    downstream = list(stages[from_index:])
    stage_state = manifest.setdefault("stage_state", {})
    stage_errors = manifest.setdefault("stage_errors", {})
    stage_results = manifest.setdefault("stage_results", {})
    for name in downstream:
        stage_state[name] = "pending"
        stage_errors.pop(name, None)
        stage_results.pop(name, None)
    if any(s in downstream for s in ("push", "pr")):
        manifest.pop("push", None)
        manifest.pop("pr", None)
    return downstream


def _iso_timestamp() -> str:
    return datetime.now().isoformat()


def get_fix_execution_root(tenant_id: str, repository_id: str, plan_id: str) -> Path:
    tid = sanitize_path_segment(tenant_id or "unknown-tenant")
    rid = sanitize_path_segment(repository_id)
    pid = sanitize_path_segment(plan_id)
    return (
        get_storage_root()
        / "tenants"
        / tid
        / "repos"
        / rid
        / "executions"
        / pid
    )


def get_modernize_execution_root(tenant_id: str, application_id: str, plan_id: str) -> Path:
    tid = sanitize_path_segment(tenant_id or "unknown-tenant")
    aid = sanitize_path_segment(application_id)
    pid = sanitize_path_segment(plan_id)
    return (
        get_storage_root()
        / "tenants"
        / tid
        / "applications"
        / aid
        / "executions"
        / pid
    )


def manifest_path(root: Path) -> Path:
    return root / MANIFEST_NAME


def read_manifest(root: Path) -> Optional[Dict[str, Any]]:
    path = manifest_path(root)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_manifest(root: Path, manifest: Dict[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest.setdefault("version", MANIFEST_VERSION)
    manifest.setdefault("updated_at", _iso_timestamp())
    path = manifest_path(root)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def ensure_subdirs(root: Path, names: tuple[str, ...]) -> Dict[str, str]:
    created: Dict[str, str] = {}
    for name in names:
        sub = root / name
        sub.mkdir(parents=True, exist_ok=True)
        created[name] = str(sub)
    return created

"""Git-grounded wiki refresh planning (Savi-native; not an OpenWiki port).

Compares the last successful wiki ``git_head`` (from analysis meta) to the
current clone HEAD and decides: full regen, incremental update, or unchanged.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.core.config import settings
from app.core.logger import logger
from app.services.intelligence.analysis_storage import META_NAME, WIKI_JSON_NAME


RefreshMode = str  # "full" | "incremental" | "unchanged"


@dataclass
class WikiFileChange:
    status: str  # A | M | D | R | …
    path: str
    old_path: Optional[str] = None


@dataclass
class WikiRefreshPlan:
    mode: RefreshMode
    current_head: Optional[str]
    previous_head: Optional[str]
    reason: str
    changed_files: List[WikiFileChange] = field(default_factory=list)
    commit_summaries: List[str] = field(default_factory=list)

    @property
    def changed_paths(self) -> List[str]:
        paths: List[str] = []
        for c in self.changed_files:
            paths.append(c.path)
            if c.old_path:
                paths.append(c.old_path)
        # preserve order, unique
        seen = set()
        out: List[str] = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out


def load_previous_wiki_meta(analysis_dir: Path) -> Dict[str, Any]:
    meta_path = Path(analysis_dir) / META_NAME
    if not meta_path.is_file():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_previous_git_head(analysis_dir: Path) -> Optional[str]:
    meta = load_previous_wiki_meta(analysis_dir)
    head = meta.get("git_head") or meta.get("gitHead")
    if isinstance(head, str) and head.strip():
        return head.strip()
    return None


def load_previous_wiki_json(analysis_dir: Path) -> Optional[Dict[str, Any]]:
    path = Path(analysis_dir) / WIKI_JSON_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _run_git(clone_path: str, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", clone_path, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def get_repo_head(clone_path: str) -> Optional[str]:
    """Return current HEAD SHA, or None if not a usable git work tree."""
    if not clone_path or not Path(clone_path).is_dir():
        return None
    result = _run_git(clone_path, "rev-parse", "HEAD")
    if result.returncode != 0:
        logger.warning("git rev-parse HEAD failed: %s", (result.stderr or "")[:300])
        return None
    sha = (result.stdout or "").strip()
    return sha or None


def commit_exists(clone_path: str, sha: str) -> bool:
    if not sha:
        return False
    result = _run_git(clone_path, "cat-file", "-e", f"{sha}^{{commit}}")
    return result.returncode == 0


def deepen_until_commit(
    clone_path: str,
    sha: str,
    *,
    step: int = 50,
    max_depth: int = 500,
) -> bool:
    """Fetch more history into a shallow clone until ``sha`` is reachable."""
    if commit_exists(clone_path, sha):
        return True

    depth = 0
    while depth < max_depth:
        deepen_by = min(step, max_depth - depth)
        result = _run_git(clone_path, "fetch", "--deepen", str(deepen_by), timeout=180)
        depth += deepen_by
        if result.returncode != 0:
            # Some remotes reject deepen; try fetching the commit directly.
            break
        if commit_exists(clone_path, sha):
            return True

    # Best-effort: ask remote for the specific object (may fail on shallow policies).
    fetch_one = _run_git(clone_path, "fetch", "origin", sha, timeout=180)
    if fetch_one.returncode == 0 and commit_exists(clone_path, sha):
        return True

    logger.info(
        "Could not make commit %s reachable in shallow clone (last fetch rc=%s)",
        sha[:12],
        fetch_one.returncode,
    )
    return False


def _parse_name_status(raw: str) -> List[WikiFileChange]:
    changes: List[WikiFileChange] = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0].strip()
        if status.startswith("R") or status.startswith("C"):
            if len(parts) >= 3:
                changes.append(
                    WikiFileChange(status=status[0], path=parts[2], old_path=parts[1])
                )
            else:
                changes.append(WikiFileChange(status=status[0], path=parts[1]))
        else:
            changes.append(WikiFileChange(status=status[0], path=parts[1]))
    return changes


def list_changed_files(clone_path: str, old_sha: str, new_sha: str) -> List[WikiFileChange]:
    result = _run_git(clone_path, "diff", "--name-status", f"{old_sha}..{new_sha}")
    if result.returncode != 0:
        logger.warning("git diff --name-status failed: %s", (result.stderr or "")[:300])
        return []
    return _parse_name_status(result.stdout)


def list_commit_summaries(
    clone_path: str,
    old_sha: str,
    new_sha: str,
    *,
    limit: int = 20,
) -> List[str]:
    result = _run_git(
        clone_path,
        "log",
        f"--max-count={limit}",
        "--pretty=format:%h %s",
        f"{old_sha}..{new_sha}",
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def collect_diff_text(
    clone_path: str,
    old_sha: str,
    new_sha: str,
    paths: Sequence[str],
    *,
    max_chars: int,
) -> str:
    if not paths or max_chars <= 0:
        return ""
    # Cap path list to keep the command manageable
    path_args = list(paths)[:80]
    result = _run_git(
        clone_path,
        "diff",
        f"{old_sha}..{new_sha}",
        "--",
        *path_args,
        timeout=180,
    )
    if result.returncode != 0:
        return ""
    text = result.stdout or ""
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n… [diff truncated] …\n"
    return text


def wiki_export_path_prefix() -> str:
    """Normalized repo-relative export folder (no leading/trailing slashes)."""
    raw = (settings.WIKI_GITHUB_EXPORT_PATH or "docs/savi-wiki").strip().strip("/")
    return raw or "docs/savi-wiki"


def path_is_under_wiki_export(path: Optional[str]) -> bool:
    """True if path is inside the configured wiki export directory."""
    if not path:
        return False
    normalized = path.replace("\\", "/").lstrip("./").strip()
    prefix = wiki_export_path_prefix()
    return normalized == prefix or normalized.startswith(prefix + "/")


def changes_only_in_wiki_export(changes: Sequence[WikiFileChange]) -> bool:
    if not changes:
        return False
    for ch in changes:
        if not path_is_under_wiki_export(ch.path):
            return False
        if ch.old_path and not path_is_under_wiki_export(ch.old_path):
            return False
    return True


def filter_non_wiki_export_changes(
    changes: Sequence[WikiFileChange],
) -> List[WikiFileChange]:
    """Drop paths under the wiki export folder (used for regen / incremental)."""
    out: List[WikiFileChange] = []
    for ch in changes:
        under_new = path_is_under_wiki_export(ch.path)
        under_old = path_is_under_wiki_export(ch.old_path) if ch.old_path else False
        if under_new and (not ch.old_path or under_old):
            continue
        if under_new and ch.old_path and not under_old:
            # Rename into export folder — still counts as a real change via old_path
            out.append(WikiFileChange(status=ch.status, path=ch.old_path))
            continue
        out.append(ch)
    return out


def plan_wiki_refresh(
    *,
    clone_path: Optional[str],
    analysis_dir: Path,
    incremental_enabled: Optional[bool] = None,
    max_files: Optional[int] = None,
) -> WikiRefreshPlan:
    """Decide full / incremental / unchanged for this wiki run."""
    enabled = (
        settings.WIKI_INCREMENTAL_ENABLED
        if incremental_enabled is None
        else incremental_enabled
    )
    file_limit = (
        settings.WIKI_INCREMENTAL_MAX_FILES if max_files is None else max_files
    )

    previous_head = load_previous_git_head(analysis_dir)
    previous_wiki = load_previous_wiki_json(analysis_dir)

    if not clone_path or not Path(clone_path).is_dir():
        return WikiRefreshPlan(
            mode="full",
            current_head=None,
            previous_head=previous_head,
            reason="no_local_clone",
        )

    current_head = get_repo_head(clone_path)
    if not current_head:
        return WikiRefreshPlan(
            mode="full",
            current_head=None,
            previous_head=previous_head,
            reason="head_unavailable",
        )

    if not previous_head or not previous_wiki:
        return WikiRefreshPlan(
            mode="full",
            current_head=current_head,
            previous_head=previous_head,
            reason="no_prior_wiki_baseline",
        )

    if previous_head == current_head:
        return WikiRefreshPlan(
            mode="unchanged",
            current_head=current_head,
            previous_head=previous_head,
            reason="same_git_head",
        )

    if not deepen_until_commit(clone_path, previous_head):
        return WikiRefreshPlan(
            mode="full",
            current_head=current_head,
            previous_head=previous_head,
            reason="prior_commit_unreachable",
            # Still capture that we could not compare; caller may full-regen.
        )

    all_changes = list_changed_files(clone_path, previous_head, current_head)
    commits = list_commit_summaries(clone_path, previous_head, current_head)

    if not all_changes:
        return WikiRefreshPlan(
            mode="unchanged",
            current_head=current_head,
            previous_head=previous_head,
            reason="empty_path_diff",
            commit_summaries=commits,
        )

    # Always skip regen when the only commits touch the Savi wiki export folder
    # (avoids re-analyzing after merging a wiki export PR).
    if changes_only_in_wiki_export(all_changes):
        return WikiRefreshPlan(
            mode="unchanged",
            current_head=current_head,
            previous_head=previous_head,
            reason="wiki_export_path_only",
            changed_files=list(all_changes),
            commit_summaries=commits,
        )

    # Code/doc changes outside the export folder drive regen decisions.
    changes = filter_non_wiki_export_changes(all_changes)
    if not changes:
        return WikiRefreshPlan(
            mode="unchanged",
            current_head=current_head,
            previous_head=previous_head,
            reason="wiki_export_path_only",
            changed_files=list(all_changes),
            commit_summaries=commits,
        )

    if not enabled:
        return WikiRefreshPlan(
            mode="full",
            current_head=current_head,
            previous_head=previous_head,
            reason="incremental_disabled",
            changed_files=changes,
            commit_summaries=commits,
        )

    if len(changes) > file_limit:
        return WikiRefreshPlan(
            mode="full",
            current_head=current_head,
            previous_head=previous_head,
            reason=f"too_many_files:{len(changes)}>{file_limit}",
            changed_files=changes,
            commit_summaries=commits,
        )

    return WikiRefreshPlan(
        mode="incremental",
        current_head=current_head,
        previous_head=previous_head,
        reason="within_incremental_budget",
        changed_files=changes,
        commit_summaries=commits,
    )


def format_incremental_prompt_context(
    plan: WikiRefreshPlan,
    clone_path: str,
    *,
    max_diff_chars: Optional[int] = None,
) -> str:
    """Human-readable change context for the incremental LLM prompt."""
    limit = (
        settings.WIKI_INCREMENTAL_MAX_DIFF_CHARS
        if max_diff_chars is None
        else max_diff_chars
    )
    lines = [
        f"Previous wiki git_head: {plan.previous_head}",
        f"Current git_head: {plan.current_head}",
        f"Commits ({len(plan.commit_summaries)}):",
    ]
    for c in plan.commit_summaries[:20]:
        lines.append(f"  - {c}")
    lines.append("Changed files:")
    for ch in plan.changed_files[:80]:
        if ch.old_path:
            lines.append(f"  {ch.status}\t{ch.old_path} -> {ch.path}")
        else:
            lines.append(f"  {ch.status}\t{ch.path}")

    if plan.previous_head and plan.current_head:
        diff = collect_diff_text(
            clone_path,
            plan.previous_head,
            plan.current_head,
            plan.changed_paths,
            max_chars=limit,
        )
        if diff:
            lines.append("\nUnified diff (may be truncated):")
            lines.append(diff)

    return "\n".join(lines)

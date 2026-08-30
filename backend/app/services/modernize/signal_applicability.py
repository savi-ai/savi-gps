"""Determine whether Analysis Config assessment signals apply to a repository stack."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.core.database import CodeChunk, RepositoryAnalysisAttribute

# Marker files used to infer primary stack families from the index.
_STACK_MARKERS: Dict[str, List[str]] = {
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "node": ["package.json"],
    "python": ["pyproject.toml", "requirements.txt", "setup.py", "pipfile", ".python-version"],
}

_NA_VALUE_PATTERNS = (
    r"^n/a\b",
    r"\bn/a\b",
    r"not applicable",
    r"not detected for",
    r"java-only",
    r"python-only",
    r"node-only",
    r"nodejs-only",
    r"frontend only",
    r"backend only",
    r"no python",
    r"no node",
    r"no java",
)

_NA_VALUE_RE = re.compile("|".join(_NA_VALUE_PATTERNS), re.IGNORECASE)


def default_applies_when_for_key(key: str) -> Optional[Dict[str, Any]]:
    from app.services.intelligence.analysis_config_service import DEFAULT_ATTRIBUTES

    for item in DEFAULT_ATTRIBUTES:
        if item.get("key") == key:
            raw = item.get("applies_when")
            return raw if isinstance(raw, dict) else None
    return None


def enrich_definition(defn: Dict[str, Any]) -> Dict[str, Any]:
    """Attach applies_when from seed defaults when missing on stored definitions."""
    out = dict(defn)
    if not out.get("applies_when"):
        seed = default_applies_when_for_key(str(out.get("key") or ""))
        if seed:
            out["applies_when"] = seed
    return out


def is_na_extracted_value(value_text: Optional[str]) -> bool:
    if not value_text or not str(value_text).strip():
        return False
    return bool(_NA_VALUE_RE.search(str(value_text).strip()))


def detect_stack_markers(db: Session, repository_id: str) -> Set[str]:
    """Return stack families inferred from indexed file paths (java, node, python)."""
    found: Set[str] = set()
    for stack, markers in _STACK_MARKERS.items():
        for marker in markers:
            hit = (
                db.query(CodeChunk.id)
                .filter(
                    CodeChunk.repository_id == repository_id,
                    CodeChunk.file_path.ilike(f"%{marker}%"),
                )
                .first()
            )
            if hit:
                found.add(stack)
                break
    return found


def _stack_tokens_from_wiki(wiki_json: Optional[Dict[str, Any]]) -> Set[str]:
    tokens: Set[str] = set()
    if not wiki_json:
        return tokens
    tech_stack = wiki_json.get("tech_stack") or []
    if isinstance(tech_stack, list):
        for item in tech_stack:
            if isinstance(item, str):
                tokens.add(item.lower())
            elif isinstance(item, dict):
                for part in (item.get("name"), item.get("category"), item.get("version")):
                    if part:
                        tokens.add(str(part).lower())
    overview = wiki_json.get("overview") or {}
    if isinstance(overview, dict):
        for key in ("primary_language", "framework", "runtime"):
            val = overview.get(key)
            if val:
                tokens.add(str(val).lower())
    return tokens


def _file_matches(markers: List[str], indexed_paths: Set[str]) -> bool:
    lowered = {p.lower() for p in indexed_paths}
    for marker in markers:
        token = marker.lower().strip()
        if not token:
            continue
        for path in lowered:
            if path.endswith(token) or f"/{token}" in path or path == token:
                return True
    return False


def _stack_matches(needles: List[str], stack_tokens: Set[str], marker_stacks: Set[str]) -> bool:
    for needle in needles:
        token = str(needle).lower().strip()
        if not token:
            continue
        if token in marker_stacks:
            return True
        for st in stack_tokens:
            if token in st:
                return True
    return False


def _indexed_paths_sample(db: Session, repository_id: str, *, limit: int = 400) -> Set[str]:
    rows = (
        db.query(CodeChunk.file_path)
        .filter(CodeChunk.repository_id == repository_id)
        .distinct()
        .limit(limit)
        .all()
    )
    return {str(r[0]) for r in rows if r and r[0]}


def is_attribute_applicable(
    definition: Dict[str, Any],
    *,
    db: Session,
    repository_id: str,
    wiki_json: Optional[Dict[str, Any]],
    attrs_map: Dict[str, RepositoryAnalysisAttribute],
    value_text: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Return (applicable, reason).
    Platform-wide attributes without applies_when are always applicable.
    """
    defn = enrich_definition(definition)
    key = (defn.get("key") or "").lower()

    if value_text is None:
        row = attrs_map.get(key)
        value_text = row.value_text if row else None

    if is_na_extracted_value(value_text):
        return False, "Extracted value indicates this check does not apply to this repository."

    applies_when = defn.get("applies_when")
    if not applies_when or not isinstance(applies_when, dict):
        return True, "Universal assessment signal."

    any_files = applies_when.get("any_file") or applies_when.get("any_file_glob") or []
    any_stack = applies_when.get("any_stack") or applies_when.get("any_stack_contains") or []

    marker_stacks = detect_stack_markers(db, repository_id)
    stack_tokens = _stack_tokens_from_wiki(wiki_json)
    indexed_paths = _indexed_paths_sample(db, repository_id)

    file_ok = _file_matches(list(any_files), indexed_paths) if any_files else False
    stack_ok = _stack_matches(list(any_stack), stack_tokens, marker_stacks) if any_stack else False

    if file_ok or stack_ok:
        return True, "Matches repository stack markers."

    # Positive extraction from a relevant source file still applies (e.g. engines.node in package.json)
    row = attrs_map.get(key)
    if row and row.value_text and str(row.value_text).strip():
        src = (row.source_file or "").lower()
        if any_files and src:
            for marker in any_files:
                m = str(marker).lower()
                if m in src or src.endswith(m):
                    return True, f"Extracted from applicable source `{row.source_file}`."

    if not any_files and not any_stack:
        return True, "No applicability constraints configured."

    parts: List[str] = []
    if any_files:
        parts.append(f"expected files like {', '.join(str(f) for f in any_files[:3])}")
    if any_stack:
        parts.append(f"expected stack hints like {', '.join(str(s) for s in any_stack[:3])}")
    reason = "Not applicable — " + "; ".join(parts) + "."
    return False, reason

"""Lightweight Mermaid fence validation / degrade (OpenWiki-inspired, no mermaid dep)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

_FENCE_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)

# Very light heuristics — catch empty / obviously broken diagrams
_BAD_HINTS = (
    "undefined",
    "null",
    "{{",
    "}}",
)


def heuristic_mermaid_error(body: str) -> str | None:
    text = (body or "").strip()
    if not text:
        return "empty mermaid diagram"
    if len(text) < 8:
        return "mermaid diagram too short"
    first = text.splitlines()[0].strip().lower()
    known_starts = (
        "graph",
        "flowchart",
        "sequencediagram",
        "classdiagram",
        "statediagram",
        "erdiagram",
        "journey",
        "gantt",
        "pie",
        "mindmap",
        "timeline",
        "gitgraph",
        "c4context",
        "c4container",
        "c4component",
    )
    if not any(first.startswith(s) or first.replace(" ", "").startswith(s) for s in known_starts):
        # Allow diagram type on same line with args
        if not any(s in first for s in ("graph", "flowchart", "sequence", "erdiagram", "class")):
            return f"unrecognized mermaid start: {first[:40]}"
    lowered = text.lower()
    for hint in _BAD_HINTS:
        if hint in lowered:
            return f"suspicious mermaid content ({hint})"
    return None


def degrade_mermaid_fences(markdown: str) -> Tuple[str, int]:
    """Replace invalid ```mermaid fences with ```text fences. Returns (md, degraded_count)."""
    if not markdown or "```mermaid" not in markdown.lower():
        return markdown or "", 0

    degraded = 0

    def _repl(match: re.Match) -> str:
        nonlocal degraded
        body = match.group(1)
        err = heuristic_mermaid_error(body)
        if not err:
            return match.group(0)
        degraded += 1
        return f"```text\n[Invalid mermaid diagram: {err}]\n{body.strip()}\n```"

    return _FENCE_RE.sub(_repl, markdown), degraded


def sanitize_wiki_json_mermaid(wiki_json: Dict[str, Any]) -> Dict[str, Any]:
    """Degrade bad mermaid strings in wiki JSON diagram fields and sections_md."""
    if not isinstance(wiki_json, dict):
        return wiki_json

    diagrams = wiki_json.get("diagrams")
    if isinstance(diagrams, dict):
        for key, val in list(diagrams.items()):
            if isinstance(val, str):
                err = heuristic_mermaid_error(val)
                if err:
                    diagrams[key] = f"[Invalid mermaid: {err}]\n{val}"

    # Common top-level mermaid keys
    for key in list(wiki_json.keys()):
        if key.endswith("_mermaid") and isinstance(wiki_json[key], str):
            err = heuristic_mermaid_error(wiki_json[key])
            if err:
                wiki_json[key] = f"[Invalid mermaid: {err}]\n{wiki_json[key]}"

    sections = wiki_json.get("sections_md")
    if isinstance(sections, dict):
        for slug, md in list(sections.items()):
            if isinstance(md, str):
                sections[slug], _ = degrade_mermaid_fences(md)

    return wiki_json

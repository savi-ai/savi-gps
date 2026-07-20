"""Bounded blast-radius views: anchor symbol + 1-hop callers/callees + Mermaid."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.core.database import RepoAnalysisView, Repository
from app.services.intelligence.analysis_storage import get_analysis_views_dir
from app.services.intelligence.graph_query_service import GraphQueryService
from app.services.intelligence.structural_extractor import GraphIndex

VIEW_TYPE = "blast_radius"
MAX_NODES = 40
MAX_HOPS = 2
DEFAULT_PRECOMPUTE = 10


def _short_label(qualified_name: str) -> str:
    if "." in qualified_name:
        cls, method = qualified_name.rsplit(".", 1)
        cls_short = cls.rsplit(".", 1)[-1]
        return f"{cls_short}.{method}()"
    return f"{qualified_name}()"


def _mermaid_id(name: str, used: Dict[str, int]) -> str:
    base = re.sub(r"[^a-zA-Z0-9_]", "_", name)[:24] or "node"
    if base[0].isdigit():
        base = f"n_{base}"
    count = used.get(base, 0)
    used[base] = count + 1
    return base if count == 0 else f"{base}_{count}"


def pick_top_anchor_symbols(graph: GraphIndex, limit: int = DEFAULT_PRECOMPUTE) -> List[str]:
    """Rank method/function symbols by call-graph connectivity."""
    scores: Dict[str, int] = defaultdict(int)
    for edge in graph.edges:
        if edge.edge_type != "CALLS":
            continue
        scores[edge.source] += 1
        scores[edge.target] += 1

    by_qname = {s.qualified_name: s for s in graph.symbols}
    ranked = [
        qn
        for qn, score in sorted(scores.items(), key=lambda item: -item[1])
        if qn in by_qname and by_qname[qn].kind in ("method", "function")
    ]
    return ranked[:limit]


def build_summary_sentence(
    anchor: str,
    callers: List[Dict[str, Any]],
    callees: List[Dict[str, Any]],
    *,
    cross_repo_count: int = 0,
) -> str:
    label = _short_label(anchor).rstrip("()")
    caller_count = len({row.get("caller") for row in callers if row.get("caller")})
    callee_count = len({row.get("callee") for row in callees if row.get("callee")})

    parts: List[str] = []
    if caller_count:
        parts.append(
            f"called by {caller_count} upstream symbol{'s' if caller_count != 1 else ''}"
        )
    if callee_count:
        parts.append(
            f"calls {callee_count} downstream symbol{'s' if callee_count != 1 else ''}"
        )
    if not parts:
        return (
            f"`{label}` has no direct callers or callees in the indexed call graph — "
            "try another symbol or re-index after code changes."
        )

    ripple = caller_count + callee_count
    sentence = f"`{label}` is {' and '.join(parts)}"
    if cross_repo_count:
        sentence += f", including {cross_repo_count} cross-repo edge{'s' if cross_repo_count != 1 else ''}"
    sentence += f" — changing it directly affects {ripple} dependencies in this repository."
    return sentence


def build_mermaid(
    anchor: str,
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> str:
    """flowchart LR with focus / context styling (cross-repo reserved for Phase 3)."""
    id_map: Dict[str, str] = {}
    used: Dict[str, int] = {}

    def node_id(name: str) -> str:
        if name not in id_map:
            id_map[name] = _mermaid_id(name, used)
        return id_map[name]

    lines = ["flowchart LR"]
    for node in nodes:
        nid = node_id(node["id"])
        label = node.get("label") or _short_label(node["id"])
        safe_label = label.replace('"', "'")
        lines.append(f'    {nid}["{safe_label}"]')

    for edge in edges:
        src = node_id(edge["source"])
        tgt = node_id(edge["target"])
        lines.append(f"    {src} --> {tgt}")

    lines.extend(
        [
            "",
            "    classDef focus fill:#E6F1FB,stroke:#185FA5,color:#042C53;",
            "    classDef xrepo fill:#FAECE7,stroke:#993C1D,color:#4A1B0C;",
            "    classDef ctx fill:#F1EFE8,stroke:#5F5E5A,color:#2C2C2A;",
        ]
    )

    anchor_nid = node_id(anchor)
    focus_nodes = [anchor_nid]
    ctx_nodes = [node_id(n["id"]) for n in nodes if n["id"] != anchor and not n.get("cross_repo")]
    xrepo_nodes = [node_id(n["id"]) for n in nodes if n.get("cross_repo")]

    if focus_nodes:
        lines.append(f"    class {','.join(focus_nodes)} focus;")
    if ctx_nodes:
        lines.append(f"    class {','.join(ctx_nodes)} ctx;")
    if xrepo_nodes:
        lines.append(f"    class {','.join(xrepo_nodes)} xrepo;")

    return "\n".join(lines)


def _build_subgraph(
    anchor: str,
    callers: List[Dict[str, Any]],
    callees: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    node_ids: Set[str] = {anchor}
    for row in callers:
        if row.get("caller"):
            node_ids.add(row["caller"])
    for row in callees:
        if row.get("callee"):
            node_ids.add(row["callee"])

    if len(node_ids) > MAX_NODES:
        node_ids = {anchor}
        for row in callers[: MAX_NODES // 2]:
            if row.get("caller"):
                node_ids.add(row["caller"])
        for row in callees[: MAX_NODES // 2]:
            if row.get("callee"):
                node_ids.add(row["callee"])

    nodes = [
        {
            "id": name,
            "label": _short_label(name),
            "role": "anchor" if name == anchor else "caller" if any(r.get("caller") == name for r in callers) else "callee",
            "cross_repo": False,
        }
        for name in sorted(node_ids)
    ]

    graph_edges: List[Dict[str, Any]] = []
    seen_edges: Set[Tuple[str, str]] = set()
    for row in callers:
        src, tgt = row.get("caller"), anchor
        if src and src in node_ids and (src, tgt) not in seen_edges:
            seen_edges.add((src, tgt))
            graph_edges.append({"source": src, "target": tgt, "type": "CALLS"})
    for row in callees:
        src, tgt = anchor, row.get("callee")
        if tgt and tgt in node_ids and (src, tgt) not in seen_edges:
            seen_edges.add((src, tgt))
            graph_edges.append({"source": src, "target": tgt, "type": "CALLS"})

    return nodes, graph_edges


class BlastRadiusService:
    def __init__(self, db: Session):
        self.db = db
        self.graph = GraphQueryService(db)

    def _cache_key(self, anchor: str, hops: int) -> str:
        raw = f"{anchor}|hops={hops}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _load_cached(
        self, repository: Repository, anchor: str, hops: int
    ) -> Optional[Dict[str, Any]]:
        row = (
            self.db.query(RepoAnalysisView)
            .filter(
                RepoAnalysisView.repository_id == repository.id,
                RepoAnalysisView.view_type == VIEW_TYPE,
                RepoAnalysisView.anchor_symbol == anchor,
            )
            .order_by(RepoAnalysisView.updated_at.desc())
            .first()
        )
        if not row or not row.derivation_json:
            return None
        cached_hops = row.derivation_json.get("hops")
        if cached_hops is not None and int(cached_hops) != hops:
            return None
        return {
            "symbol": anchor,
            "anchor": anchor,
            "summary": row.summary_sentence,
            "mermaid": row.mermaid or "",
            "nodes": row.derivation_json.get("nodes") or [],
            "edges": row.derivation_json.get("edges") or [],
            "cross_repo": row.derivation_json.get("cross_repo") or [],
            "hops": hops,
            "cached": True,
        }

    def _persist_cache(
        self,
        repository: Repository,
        anchor: str,
        hops: int,
        payload: Dict[str, Any],
        *,
        index_run_id: Optional[str] = None,
    ) -> None:
        derivation = {
            "hops": hops,
            "nodes": payload["nodes"],
            "edges": payload["edges"],
            "cross_repo": payload.get("cross_repo") or [],
        }
        existing = (
            self.db.query(RepoAnalysisView)
            .filter(
                RepoAnalysisView.repository_id == repository.id,
                RepoAnalysisView.view_type == VIEW_TYPE,
                RepoAnalysisView.anchor_symbol == anchor,
            )
            .first()
        )
        if existing:
            existing.summary_sentence = payload["summary"]
            existing.mermaid = payload["mermaid"]
            existing.derivation_json = derivation
            existing.index_run_id = index_run_id or existing.index_run_id
            existing.updated_at = datetime.now()
        else:
            self.db.add(
                RepoAnalysisView(
                    id=str(uuid.uuid4()),
                    tenant_id=repository.tenant_id,
                    repository_id=repository.id,
                    view_type=VIEW_TYPE,
                    anchor_symbol=anchor,
                    summary_sentence=payload["summary"],
                    mermaid=payload["mermaid"],
                    derivation_json=derivation,
                    index_run_id=index_run_id,
                )
            )
        self.db.commit()

        views_dir = get_analysis_views_dir(repository)
        views_dir.mkdir(parents=True, exist_ok=True)
        cache_file = views_dir / f"blast_radius.{self._cache_key(anchor, hops)}.json"
        cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def compute(
        self,
        repository: Repository,
        symbol: str,
        *,
        hops: int = 1,
        use_cache: bool = True,
        index_run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        hops = min(max(hops, 1), MAX_HOPS)
        anchor = self.graph.resolve_anchor_symbol(repository, symbol)
        if not anchor:
            return {
                "symbol": symbol,
                "anchor": None,
                "summary": (
                    f"No symbol matching `{symbol}` found in the call graph. "
                    "Try a class or method name from this repository."
                ),
                "mermaid": "",
                "nodes": [],
                "edges": [],
                "cross_repo": [],
                "hops": hops,
                "cached": False,
                "available": False,
            }

        if use_cache and not index_run_id:
            cached = self._load_cached(repository, anchor, hops)
            if cached:
                cached["available"] = True
                return cached

        callers = self.graph.find_callers(repository, anchor, limit=30)
        callees = self.graph.find_callees(repository, anchor, limit=30)

        if hops >= 2:
            extra_callers: List[Dict[str, Any]] = []
            for row in list(callers)[:10]:
                upstream = row.get("caller")
                if upstream:
                    extra_callers.extend(
                        self.graph.find_callers(repository, upstream, limit=5)
                    )
            callers = callers + extra_callers

        cross_repo: List[Dict[str, Any]] = []
        nodes, edges = _build_subgraph(anchor, callers, callees)
        summary = build_summary_sentence(anchor, callers, callees, cross_repo_count=len(cross_repo))
        mermaid = build_mermaid(anchor, nodes, edges) if nodes else ""

        payload = {
            "symbol": symbol,
            "anchor": anchor,
            "summary": summary,
            "mermaid": mermaid,
            "nodes": nodes,
            "edges": edges,
            "cross_repo": cross_repo,
            "hops": hops,
            "cached": False,
            "available": True,
        }
        self._persist_cache(repository, anchor, hops, payload, index_run_id=index_run_id)
        payload["cached"] = False
        return payload

    def list_anchors(self, repository: Repository) -> List[Dict[str, Any]]:
        rows = (
            self.db.query(RepoAnalysisView)
            .filter(
                RepoAnalysisView.repository_id == repository.id,
                RepoAnalysisView.view_type == VIEW_TYPE,
            )
            .order_by(RepoAnalysisView.updated_at.desc())
            .all()
        )
        seen: Set[str] = set()
        anchors: List[Dict[str, Any]] = []
        for row in rows:
            if not row.anchor_symbol or row.anchor_symbol in seen:
                continue
            seen.add(row.anchor_symbol)
            anchors.append(
                {
                    "anchor": row.anchor_symbol,
                    "label": _short_label(row.anchor_symbol).rstrip("()"),
                    "summary": row.summary_sentence,
                }
            )
        return anchors

    def precompute_for_repository(
        self,
        repository: Repository,
        graph_index: GraphIndex,
        *,
        index_run_id: Optional[str] = None,
        limit: int = DEFAULT_PRECOMPUTE,
    ) -> int:
        """Precompute blast-radius for top connected symbols after indexing."""
        symbols = pick_top_anchor_symbols(graph_index, limit=limit)
        count = 0
        for symbol in symbols:
            try:
                self.compute(
                    repository,
                    symbol,
                    hops=1,
                    use_cache=False,
                    index_run_id=index_run_id,
                )
                count += 1
            except Exception:
                continue
        return count

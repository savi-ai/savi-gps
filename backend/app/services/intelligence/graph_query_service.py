"""Query symbol/call graph from Neo4j or persisted graph_index.json."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import Repository
from app.services.intelligence.analysis_storage import GRAPH_INDEX_NAME, resolve_analysis_dir
from app.services.intelligence.neo4j_client import is_neo4j_enabled, run_query
from app.services.intelligence.structural_extractor import GraphIndex


def _load_graph_index(repository: Repository) -> Optional[GraphIndex]:
    path = resolve_analysis_dir(repository) / GRAPH_INDEX_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return GraphIndex.from_dict(data)
    except (json.JSONDecodeError, OSError):
        return None


def _normalize_symbol_query(q: str) -> str:
    return q.strip().rstrip("?")


class GraphQueryService:
    def __init__(self, db: Session):
        self.db = db

    def get_graph_stats(self, repository: Repository) -> Dict[str, Any]:
        graph = _load_graph_index(repository)
        if not graph:
            return {"available": False, "neo4j": is_neo4j_enabled()}
        return {
            "available": True,
            "neo4j": is_neo4j_enabled(),
            **graph.stats,
        }

    def search_symbols(
        self, repository: Repository, query: str, limit: int = 25
    ) -> List[Dict[str, Any]]:
        q = query.lower()
        graph = _load_graph_index(repository)
        if not graph:
            return []

        hits = []
        for sym in graph.symbols:
            if q in sym.qualified_name.lower() or q in sym.name.lower():
                hits.append(
                    {
                        "name": sym.name,
                        "kind": sym.kind,
                        "qualified_name": sym.qualified_name,
                        "file_path": sym.file_path,
                        "start_line": sym.start_line,
                    }
                )
        return hits[:limit]

    def resolve_anchor_symbol(
        self, repository: Repository, symbol_query: str
    ) -> Optional[str]:
        """Resolve user query to a graph qualified_name (prefer method/function)."""
        q = _normalize_symbol_query(symbol_query)
        graph = _load_graph_index(repository)
        if not graph:
            return None

        exact = [
            s
            for s in graph.symbols
            if s.qualified_name == q or s.name == q
        ]
        if exact:
            methods = [s for s in exact if s.kind in ("method", "function")]
            return (methods or exact)[0].qualified_name

        partial = [
            s
            for s in graph.symbols
            if q.lower() in s.qualified_name.lower() or s.name.lower() == q.lower()
        ]
        if not partial:
            return None

        methods = [s for s in partial if s.kind in ("method", "function")]
        ranked = methods or partial
        ranked.sort(key=lambda s: (s.qualified_name.count("."), len(s.qualified_name)))
        return ranked[0].qualified_name

    def find_callees(
        self, repository: Repository, symbol_query: str, limit: int = 30
    ) -> List[Dict[str, Any]]:
        symbol_query = _normalize_symbol_query(symbol_query)
        anchor = self.resolve_anchor_symbol(repository, symbol_query)

        if is_neo4j_enabled():
            rows = run_query(
                """
                MATCH (r:Repository {id: $repo_id})-[:CONTAINS*]->(source:Symbol)
                WHERE source.qualified_name CONTAINS $q OR source.name = $q
                WITH source
                MATCH (source)-[:CALLS]->(callee:Symbol)
                WHERE callee.repository_id = $repo_id
                RETURN DISTINCT callee.qualified_name AS callee,
                       callee.file_path AS file,
                       callee.start_line AS line,
                       source.qualified_name AS caller
                LIMIT $limit
                """,
                {"repo_id": repository.id, "q": symbol_query, "limit": limit},
            )
            if rows:
                return rows

        graph = _load_graph_index(repository)
        if not graph:
            return []

        sources = {
            s.qualified_name
            for s in graph.symbols
            if symbol_query.lower() in s.qualified_name.lower()
            or s.name.lower() == symbol_query.lower()
        }
        if anchor:
            sources.add(anchor)

        callees: List[Dict[str, Any]] = []
        seen = set()
        for edge in graph.edges:
            if edge.edge_type != "CALLS":
                continue
            if edge.source not in sources and not any(
                t.lower() in edge.source.lower() for t in symbol_query.split(".")
            ):
                continue
            key = (edge.target, edge.target_file, edge.source_line, edge.source)
            if key in seen:
                continue
            seen.add(key)
            callees.append(
                {
                    "callee": edge.target,
                    "file": edge.target_file or edge.source_file,
                    "line": edge.source_line,
                    "caller": edge.source,
                }
            )
        return callees[:limit]

    def find_callers(
        self, repository: Repository, symbol_query: str, limit: int = 30
    ) -> List[Dict[str, Any]]:
        symbol_query = _normalize_symbol_query(symbol_query)

        if is_neo4j_enabled():
            rows = run_query(
                """
                MATCH (r:Repository {id: $repo_id})-[:CONTAINS*]->(target:Symbol)
                WHERE target.qualified_name CONTAINS $q OR target.name = $q
                WITH target
                MATCH (caller:Symbol)-[:CALLS]->(target)
                WHERE caller.repository_id = $repo_id
                RETURN DISTINCT caller.qualified_name AS caller,
                       caller.file_path AS file,
                       caller.start_line AS line
                LIMIT $limit
                """,
                {"repo_id": repository.id, "q": symbol_query, "limit": limit},
            )
            if rows:
                return rows

        graph = _load_graph_index(repository)
        if not graph:
            return []

        targets = {
            s.qualified_name
            for s in graph.symbols
            if symbol_query.lower() in s.qualified_name.lower()
            or s.name.lower() == symbol_query.lower()
        }
        for edge in graph.edges:
            if edge.edge_type == "CALLS" and (
                edge.target in targets
                or symbol_query.lower() in edge.target.lower()
            ):
                targets.add(edge.target)

        callers: List[Dict[str, Any]] = []
        seen = set()
        for edge in graph.edges:
            if edge.edge_type != "CALLS":
                continue
            if edge.target not in targets and not any(
                t.lower() in edge.target.lower() for t in symbol_query.split(".")
            ):
                continue
            key = (edge.source, edge.source_file, edge.source_line)
            if key in seen:
                continue
            seen.add(key)
            callers.append(
                {
                    "caller": edge.source,
                    "file": edge.source_file,
                    "line": edge.source_line,
                    "callee": edge.target,
                }
            )
        return callers[:limit]

    def format_callers_context(
        self, repository: Repository, symbol_query: str
    ) -> str:
        callers = self.find_callers(repository, symbol_query)
        if not callers:
            return ""

        lines = [f"## Call graph: who calls `{symbol_query}`", ""]
        for row in callers:
            cite = f"`{row['file']}:{row['line']}`"
            callee = row.get("callee", symbol_query)
            lines.append(f"- **{row['caller']}** → {callee} ({cite})")
        return "\n".join(lines)

    def extract_symbol_from_question(self, question: str) -> Optional[str]:
        q = question.lower()
        patterns = [
            r"who calls\s+([\w.]+)",
            r"what calls\s+([\w.]+)",
            r"callers of\s+([\w.]+)",
            r"who invokes\s+([\w.]+)",
        ]
        for pat in patterns:
            m = re.search(pat, q, re.I)
            if m:
                return m.group(1)
        backtick = re.search(r"`([\w.]+)`", question)
        if backtick and any(k in q for k in ("call", "invoke", "caller")):
            return backtick.group(1)
        return None

    def is_graph_question(self, question: str) -> bool:
        q = question.lower()
        return any(
            k in q
            for k in (
                "who calls",
                "what calls",
                "callers of",
                "call graph",
                "who invokes",
                "depends on",
            )
        )

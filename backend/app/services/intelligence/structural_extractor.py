"""L2/L3 static extraction for Java and Python (regex/heuristic MVP)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

SKIP_DIRS = {
    ".git", "node_modules", "target", "build", "dist", ".venv", "venv",
    "__pycache__", ".gradle", "vendor",
}

JAVA_CLASS_RE = re.compile(
    r"^\s*(?:public|private|protected)?\s*(?:abstract|final)?\s*class\s+(\w+)"
)
JAVA_METHOD_RE = re.compile(
    r"^\s*(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?"
    r"[\w<>\[\],\s.?]+\s+(\w+)\s*\("
)
JAVA_CALL_RE = re.compile(r"\b(\w+)\.(\w+)\s*\(")
JAVA_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+(?:\.\*)?)\s*;")

PY_CLASS_RE = re.compile(r"^\s*class\s+(\w+)")
PY_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(")
PY_CALL_RE = re.compile(r"\b(\w+)\.(\w+)\s*\(")


@dataclass
class GraphSymbol:
    name: str
    kind: str
    qualified_name: str
    file_path: str
    start_line: int
    end_line: int = 0
    language: str = ""


@dataclass
class GraphEdge:
    edge_type: str
    source: str
    target: str
    source_file: str
    source_line: int
    target_file: str = ""


@dataclass
class GraphIndex:
    symbols: List[GraphSymbol] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "symbols": [asdict(s) for s in self.symbols],
            "edges": [asdict(e) for e in self.edges],
            "stats": self.stats,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "GraphIndex":
        return cls(
            symbols=[GraphSymbol(**s) for s in data.get("symbols", [])],
            edges=[GraphEdge(**e) for e in data.get("edges", [])],
            stats=data.get("stats") or {},
        )


def _java_qname(file_path: str, class_name: str) -> str:
    parts = file_path.replace("\\", "/").split("/")
    if "java" in parts:
        idx = parts.index("java")
        pkg = ".".join(parts[idx + 1 : -1])
        return f"{pkg}.{class_name}" if pkg else class_name
    return class_name


def _extract_java_file(rel_path: str, text: str, index: GraphIndex) -> None:
    lines = text.splitlines()
    current_class: Optional[str] = None
    current_method: Optional[str] = None
    imports: Set[str] = set()

    for i, line in enumerate(lines, start=1):
        imp = JAVA_IMPORT_RE.match(line)
        if imp:
            imports.add(imp.group(1).replace(".*", ""))
            continue

        cm = JAVA_CLASS_RE.match(line)
        if cm:
            current_class = cm.group(1)
            qn = _java_qname(rel_path, current_class)
            index.symbols.append(
                GraphSymbol(
                    name=current_class,
                    kind="class",
                    qualified_name=qn,
                    file_path=rel_path,
                    start_line=i,
                    language="java",
                )
            )
            current_method = None
            continue

        mm = JAVA_METHOD_RE.match(line)
        if mm and current_class:
            method_name = mm.group(1)
            if method_name in ("if", "for", "while", "switch", "catch", "return"):
                continue
            current_method = method_name
            qn = f"{_java_qname(rel_path, current_class)}.{method_name}"
            index.symbols.append(
                GraphSymbol(
                    name=method_name,
                    kind="method",
                    qualified_name=qn,
                    file_path=rel_path,
                    start_line=i,
                    language="java",
                )
            )
            continue

        if current_class and current_method:
            for call in JAVA_CALL_RE.finditer(line):
                recv, meth = call.group(1), call.group(2)
                if recv in ("this", "super", "logger", "log", "System"):
                    continue
                if meth[0].isupper() and recv[0].islower():
                    target_class = recv[0].upper() + recv[1:]
                    target = f"{target_class}.{meth}"
                else:
                    target = f"{recv}.{meth}"
                source = f"{_java_qname(rel_path, current_class)}.{current_method}"
                index.edges.append(
                    GraphEdge(
                        edge_type="CALLS",
                        source=source,
                        target=target,
                        source_file=rel_path,
                        source_line=i,
                    )
                )


def _extract_python_file(rel_path: str, text: str, index: GraphIndex) -> None:
    lines = text.splitlines()
    current_class: Optional[str] = None
    current_func: Optional[str] = None
    module = rel_path.replace("/", ".").replace(".py", "")

    for i, line in enumerate(lines, start=1):
        cm = PY_CLASS_RE.match(line)
        if cm:
            current_class = cm.group(1)
            qn = f"{module}.{current_class}"
            index.symbols.append(
                GraphSymbol(
                    name=current_class,
                    kind="class",
                    qualified_name=qn,
                    file_path=rel_path,
                    start_line=i,
                    language="python",
                )
            )
            current_func = None
            continue

        dm = PY_DEF_RE.match(line)
        if dm:
            func_name = dm.group(1)
            if current_class:
                qn = f"{module}.{current_class}.{func_name}"
            else:
                qn = f"{module}.{func_name}"
            current_func = func_name
            index.symbols.append(
                GraphSymbol(
                    name=func_name,
                    kind="function",
                    qualified_name=qn,
                    file_path=rel_path,
                    start_line=i,
                    language="python",
                )
            )
            continue

        if current_func:
            for call in PY_CALL_RE.finditer(line):
                recv, meth = call.group(1), call.group(2)
                if recv in ("self", "cls", "logger"):
                    continue
                prefix = f"{module}.{current_class}." if current_class else f"{module}."
                source = f"{prefix}{current_func}"
                index.edges.append(
                    GraphEdge(
                        edge_type="CALLS",
                        source=source,
                        target=f"{recv}.{meth}",
                        source_file=rel_path,
                        source_line=i,
                    )
                )


def build_graph_index(clone_path: str) -> GraphIndex:
    """Walk clone and extract symbols + CALLS edges for Java/Python."""
    root = Path(clone_path)
    index = GraphIndex()
    file_count = 0

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix == ".java":
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            _extract_java_file(rel, text, index)
            file_count += 1
        elif path.suffix == ".py":
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            _extract_python_file(rel, text, index)
            file_count += 1

    index.stats = {
        "files_parsed": file_count,
        "symbol_count": len(index.symbols),
        "edge_count": len(index.edges),
        "calls_count": sum(1 for e in index.edges if e.edge_type == "CALLS"),
    }
    return index


def format_call_graph_for_wiki(index: GraphIndex, limit: int = 40) -> str:
    """Human-readable call paths for wiki Business Logic prompt injection."""
    if not index.edges:
        return ""

    by_source: Dict[str, List[str]] = {}
    for edge in index.edges:
        if edge.edge_type != "CALLS":
            continue
        by_source.setdefault(edge.source, [])
        cite = f"`{edge.source_file}:{edge.source_line}`"
        by_source[edge.source].append(f"{edge.target} ({cite})")

    lines = [
        "# Static call graph (extracted from source — use for Business Logic Layer workflows)",
        "",
    ]
    count = 0
    for source, targets in sorted(by_source.items(), key=lambda x: -len(x[1])):
        if count >= limit:
            break
        if not any(k in source for k in ("Service", "Servlet", "Manager", "Handler", "Impl")):
            continue
        lines.append(f"## {source}")
        for t in targets[:8]:
            lines.append(f"- calls → {t}")
        lines.append("")
        count += 1

    return "\n".join(lines)

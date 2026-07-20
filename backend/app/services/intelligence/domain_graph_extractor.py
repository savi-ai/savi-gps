"""Extract domain entities and relationships from JPA, SQL DDL, and protobuf."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

SKIP_DIRS = {
    ".git", "node_modules", "target", "build", "dist", ".venv", "venv",
    "__pycache__", ".gradle", "vendor", "test", "tests",
}

JAVA_ENTITY_RE = re.compile(r"@Entity\b")
JAVA_CLASS_RE = re.compile(r"\bclass\s+(\w+)")
JAVA_TABLE_RE = re.compile(r'@Table\s*\(\s*name\s*=\s*"([^"]+)"')
JAVA_ID_RE = re.compile(
    r"@Id\b[\s\S]*?private\s+([\<\>\w,\s]+?)\s+(\w+)\s*;",
    re.MULTILINE,
)
JAVA_MANY_TO_ONE_RE = re.compile(
    r"@ManyToOne\b[\s\S]*?private\s+(\w+)\s+(\w+)\s*;",
    re.MULTILINE,
)
JAVA_ONE_TO_MANY_RE = re.compile(
    r"@OneToMany\b[\s\S]*?private\s+(?:List|Set)<(\w+)>\s+(\w+)\s*;",
    re.MULTILINE,
)
JAVA_ONE_TO_ONE_RE = re.compile(
    r"@OneToOne\b[\s\S]*?private\s+(\w+)\s+(\w+)\s*;",
    re.MULTILINE,
)
JAVA_FIELD_RE = re.compile(r"private\s+([\<\>\w,\s]+?)\s+(\w+)\s*;")

SQL_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"']?(\w+)[`\"']?\s*\(",
    re.IGNORECASE,
)
SQL_COLUMN_RE = re.compile(
    r"^\s*[`\"']?(\w+)[`\"']?\s+([\w()]+)(?:\s+(PRIMARY\s+KEY|NOT\s+NULL|UNIQUE))?",
    re.IGNORECASE | re.MULTILINE,
)
SQL_FK_RE = re.compile(
    r"FOREIGN\s+KEY\s*\(\s*[`\"']?(\w+)[`\"']?\s*\)\s*REFERENCES\s+[`\"']?(\w+)[`\"']?",
    re.IGNORECASE,
)
SQL_INLINE_FK_RE = re.compile(
    r"[`\"']?(\w+)[`\"']?\s+[\w()]+\s+REFERENCES\s+[`\"']?(\w+)[`\"']?",
    re.IGNORECASE,
)

PROTO_MESSAGE_RE = re.compile(r"\bmessage\s+(\w+)\s*\{")
PROTO_FIELD_RE = re.compile(
    r"^\s*(?:optional|repeated|required)?\s*([\.\w]+)\s+(\w+)\s*=",
    re.MULTILINE,
)


@dataclass
class EntityField:
    name: str
    type: str
    flags: str = ""

    def mermaid_attr(self) -> str:
        parts = [self.type, self.name]
        if self.flags:
            parts.append(self.flags)
        return " ".join(parts)


@dataclass
class DomainEntity:
    name: str
    table_name: Optional[str] = None
    source_file: str = ""
    source: str = "jpa"  # jpa | sql | proto
    fields: List[EntityField] = field(default_factory=list)


@dataclass
class DomainRelationship:
    from_entity: str
    to_entity: str
    label: str
    cardinality: str = "||--o{"

    def mermaid_line(self) -> str:
        safe_label = self.label.replace('"', "'")
        return f'  {self.from_entity} {self.cardinality} {self.to_entity} : "{safe_label}"'


@dataclass
class DomainGraph:
    entities: List[DomainEntity] = field(default_factory=list)
    relationships: List[DomainRelationship] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)

    @property
    def entity_count(self) -> int:
        return len(self.entities)

    @property
    def relationship_count(self) -> int:
        return len(self.relationships)

    def to_dict(self) -> Dict:
        return {
            "entities": [asdict(e) for e in self.entities],
            "relationships": [asdict(r) for r in self.relationships],
            "sources": self.sources,
            "entity_count": self.entity_count,
            "relationship_count": self.relationship_count,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "DomainGraph":
        entities = []
        for e in data.get("entities", []):
            fields = [EntityField(**f) if isinstance(f, dict) else f for f in e.get("fields", [])]
            entities.append(
                DomainEntity(
                    name=e["name"],
                    table_name=e.get("table_name"),
                    source_file=e.get("source_file", ""),
                    source=e.get("source", "jpa"),
                    fields=fields,
                )
            )
        relationships = [
            DomainRelationship(**r) if isinstance(r, dict) else r
            for r in data.get("relationships", [])
        ]
        return cls(
            entities=entities,
            relationships=relationships,
            sources=data.get("sources") or [],
        )


def _entity_key(name: str) -> str:
    """Mermaid-safe entity id (uppercase class/table name)."""
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    return cleaned.upper()


def _merge_entity(existing: DomainEntity, incoming: DomainEntity) -> DomainEntity:
    seen = {(f.name, f.type) for f in existing.fields}
    for fld in incoming.fields:
        key = (fld.name, fld.type)
        if key not in seen:
            existing.fields.append(fld)
            seen.add(key)
    if not existing.table_name and incoming.table_name:
        existing.table_name = incoming.table_name
    if not existing.source_file and incoming.source_file:
        existing.source_file = incoming.source_file
    return existing


def _extract_jpa_file(rel_path: str, text: str) -> Tuple[List[DomainEntity], List[DomainRelationship]]:
    if "@Entity" not in text:
        return [], []

    entities: List[DomainEntity] = []
    relationships: List[DomainRelationship] = []

    for class_match in JAVA_CLASS_RE.finditer(text):
        class_name = class_match.group(1)
        # Only process if @Entity appears before this class declaration
        prefix = text[: class_match.start()]
        if "@Entity" not in prefix[-400:]:
            continue

        entity_name = _entity_key(class_name)
        table_match = JAVA_TABLE_RE.search(text[class_match.start() : class_match.start() + 400])
        table_name = table_match.group(1) if table_match else class_name.lower()

        fields: List[EntityField] = []
        for id_match in JAVA_ID_RE.finditer(text):
            if id_match.start() < class_match.start() or id_match.start() > class_match.start() + 4000:
                continue
            fields.append(EntityField(name=id_match.group(2), type=id_match.group(1).strip(), flags="PK"))

        for field_match in JAVA_FIELD_RE.finditer(text[class_match.start() : class_match.start() + 4000]):
            fname = field_match.group(2)
            ftype = field_match.group(1).strip()
            if fname in {f.name for f in fields}:
                continue
            flags = "FK" if fname.endswith("_id") or fname.endswith("Id") else ""
            fields.append(EntityField(name=fname, type=ftype, flags=flags))

        entities.append(
            DomainEntity(
                name=entity_name,
                table_name=table_name,
                source_file=rel_path,
                source="jpa",
                fields=fields[:15],
            )
        )

        for m2o in JAVA_MANY_TO_ONE_RE.finditer(text[class_match.start() : class_match.start() + 4000]):
            target = _entity_key(m2o.group(1))
            relationships.append(
                DomainRelationship(
                    from_entity=entity_name,
                    to_entity=target,
                    label=m2o.group(2),
                    cardinality="}o--||",
                )
            )
            relationships.append(
                DomainRelationship(
                    from_entity=target,
                    to_entity=entity_name,
                    label=f"has {class_name.lower()}",
                    cardinality="||--o{",
                )
            )

        for o2m in JAVA_ONE_TO_MANY_RE.finditer(text[class_match.start() : class_match.start() + 4000]):
            child = _entity_key(o2m.group(1))
            relationships.append(
                DomainRelationship(
                    from_entity=entity_name,
                    to_entity=child,
                    label=o2m.group(2),
                    cardinality="||--o{",
                )
            )

        for o2o in JAVA_ONE_TO_ONE_RE.finditer(text[class_match.start() : class_match.start() + 4000]):
            other = _entity_key(o2o.group(1))
            relationships.append(
                DomainRelationship(
                    from_entity=entity_name,
                    to_entity=other,
                    label=o2o.group(2),
                    cardinality="||--||",
                )
            )

    return entities, relationships


def _extract_sql_file(rel_path: str, text: str) -> Tuple[List[DomainEntity], List[DomainRelationship]]:
    entities: List[DomainEntity] = []
    relationships: List[DomainRelationship] = []

    for table_match in SQL_CREATE_TABLE_RE.finditer(text):
        table_name = table_match.group(1)
        entity_name = _entity_key(table_name)
        start = table_match.end()
        depth = 1
        end = start
        while end < len(text) and depth > 0:
            if text[end] == "(":
                depth += 1
            elif text[end] == ")":
                depth -= 1
            end += 1
        body = text[start : end - 1]

        fields: List[EntityField] = []
        for col in SQL_COLUMN_RE.finditer(body):
            col_name, col_type, modifier = col.group(1), col.group(2), col.group(3) or ""
            flags = "PK" if modifier and "PRIMARY" in modifier.upper() else ""
            if col_name.lower().endswith("_id") and col_name.lower() != "id":
                flags = (flags + " FK").strip()
            fields.append(EntityField(name=col_name, type=col_type, flags=flags))

        entities.append(
            DomainEntity(
                name=entity_name,
                table_name=table_name,
                source_file=rel_path,
                source="sql",
                fields=fields[:15],
            )
        )

        for fk in SQL_FK_RE.finditer(body):
            ref_table = _entity_key(fk.group(2))
            relationships.append(
                DomainRelationship(
                    from_entity=entity_name,
                    to_entity=ref_table,
                    label=fk.group(1),
                    cardinality="}o--||",
                )
            )
        for fk in SQL_INLINE_FK_RE.finditer(body):
            ref_table = _entity_key(fk.group(2))
            relationships.append(
                DomainRelationship(
                    from_entity=entity_name,
                    to_entity=ref_table,
                    label=fk.group(1),
                    cardinality="}o--||",
                )
            )

    return entities, relationships


def _extract_proto_file(rel_path: str, text: str) -> Tuple[List[DomainEntity], List[DomainRelationship]]:
    entities: List[DomainEntity] = []
    relationships: List[DomainRelationship] = []

    for msg_match in PROTO_MESSAGE_RE.finditer(text):
        msg_name = msg_match.group(1)
        entity_name = _entity_key(msg_name)
        start = msg_match.end()
        depth = 1
        end = start
        while end < len(text) and depth > 0:
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
            end += 1
        body = text[start : end - 1]

        fields: List[EntityField] = []
        for fld in PROTO_FIELD_RE.finditer(body):
            ftype, fname = fld.group(1), fld.group(2)
            flags = "repeated" if "repeated" in fld.group(0) else ""
            fields.append(EntityField(name=fname, type=ftype.split(".")[-1], flags=flags))
            if ftype[0].isupper() and ftype not in ("string", "int32", "int64", "bool", "bytes"):
                relationships.append(
                    DomainRelationship(
                        from_entity=entity_name,
                        to_entity=_entity_key(ftype.split(".")[-1]),
                        label=fname,
                        cardinality="||--o{" if "repeated" in fld.group(0) else "||--||",
                    )
                )

        entities.append(
            DomainEntity(
                name=entity_name,
                source_file=rel_path,
                source="proto",
                fields=fields[:15],
            )
        )

    return entities, relationships


def _dedupe_relationships(rels: List[DomainRelationship]) -> List[DomainRelationship]:
    seen: Set[Tuple[str, str, str]] = set()
    out: List[DomainRelationship] = []
    for rel in rels:
        key = (rel.from_entity, rel.to_entity, rel.cardinality)
        if key in seen:
            continue
        seen.add(key)
        out.append(rel)
    return out


def extract_domain_graph(clone_path: str, *, max_entities: int = 30) -> DomainGraph:
    """Walk clone and extract domain model from JPA, SQL, and proto sources."""
    root = Path(clone_path)
    if not root.is_dir():
        return DomainGraph()

    by_name: Dict[str, DomainEntity] = {}
    relationships: List[DomainRelationship] = []
    sources_used: Set[str] = set()

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        extracted: Tuple[List[DomainEntity], List[DomainRelationship]] = ([], [])
        if suffix == ".java" and "@Entity" in text:
            extracted = _extract_jpa_file(rel, text)
            if extracted[0]:
                sources_used.add("jpa")
        elif suffix in (".sql", ".ddl") or rel.lower().endswith(".sql"):
            if "CREATE TABLE" in text.upper():
                extracted = _extract_sql_file(rel, text)
                if extracted[0]:
                    sources_used.add("sql")
        elif suffix == ".proto":
            extracted = _extract_proto_file(rel, text)
            if extracted[0]:
                sources_used.add("proto")

        for ent in extracted[0]:
            if ent.name in by_name:
                by_name[ent.name] = _merge_entity(by_name[ent.name], ent)
            else:
                by_name[ent.name] = ent
        relationships.extend(extracted[1])

        if len(by_name) >= max_entities:
            break

    entities = list(by_name.values())[:max_entities]
    return DomainGraph(
        entities=entities,
        relationships=_dedupe_relationships(relationships)[: max_entities * 2],
        sources=sorted(sources_used),
    )


def build_er_mermaid(graph: DomainGraph, *, max_entities: int = 20) -> str:
    """Generate erDiagram Mermaid from domain graph."""
    if not graph.entities:
        return ""

    lines = ["erDiagram"]
    entity_names = {e.name for e in graph.entities[:max_entities]}

    for rel in graph.relationships:
        if rel.from_entity in entity_names and rel.to_entity in entity_names:
            lines.append(rel.mermaid_line())

    for entity in graph.entities[:max_entities]:
        lines.append(f"  {entity.name} {{")
        if entity.fields:
            for fld in entity.fields[:12]:
                lines.append(f"    {fld.mermaid_attr()}")
        else:
            lines.append("    string id PK")
        lines.append("  }")

    return "\n".join(lines)


def build_summary_sentence(graph: DomainGraph) -> str:
    n_ent = graph.entity_count
    n_rel = graph.relationship_count
    if n_ent == 0:
        return (
            "No domain entities detected from JPA `@Entity` mappings, SQL DDL, "
            "or `.proto` message definitions in this repository."
        )
    sources = ", ".join(graph.sources) if graph.sources else "source files"
    names = ", ".join(e.name.title() for e in graph.entities[:5])
    more = f" and {n_ent - 5} more" if n_ent > 5 else ""
    return (
        f"This repository defines **{n_ent} core domain entit{'y' if n_ent == 1 else 'ies'}** "
        f"({names}{more}) with **{n_rel} relationship{'s' if n_rel != 1 else ''}**, "
        f"extracted from {sources}."
    )

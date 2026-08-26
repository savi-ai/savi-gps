"""Application-scoped cross-repo service map (Phase 3)."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.core.database import (
    Application,
    ApplicationRepository,
    CodeChunk,
    Repository,
    RepositoryAnalysisAttribute,
    RepositoryWikiSite,
)
from app.core.logger import logger
from app.services.intelligence.analysis_storage import get_application_analysis_dir
from app.services.intelligence.blast_radius_service import BlastRadiusService

VIEW_TYPE = "service_map"
SERVICE_MAP_FILE = "service_map.json"
SERVICE_MAP_SCHEMA_VERSION = 2
_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 3600

HTTP_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
FEIGN_RE = re.compile(
    r"@FeignClient\s*\(\s*(?:name\s*=\s*)?[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
ARTIFACT_RE = re.compile(r"<artifactId>([^<]+)</artifactId>", re.IGNORECASE)
NPM_DEP_RE = re.compile(r"\"([^\"]+)\"\s*:\s*\"[^\"]*\"", re.MULTILINE)
PROTO_MESSAGE_RE = re.compile(r"\bmessage\s+(\w+)\s*\{")
OPENAPI_PATH_RE = re.compile(r"[\"'](/[a-zA-Z0-9_./{}-]+)[\"']")
REST_CLIENT_RE = re.compile(
    r"(?:RestTemplate|WebClient|HttpClient|axios|fetch)\s*\([^)]*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)


def _snippet(text: str, needle: str, *, width: int = 120) -> str:
    idx = text.lower().find(needle.lower())
    if idx < 0:
        return text[:width].strip()
    start = max(0, idx - 40)
    end = min(len(text), idx + len(needle) + 40)
    bit = text[start:end].replace("\n", " ").strip()
    if start > 0:
        bit = "…" + bit
    if end < len(text):
        bit = bit + "…"
    return bit[:width]


def _first_file_match(
    sources: List[Tuple[str, str]],
    predicate,
) -> Tuple[Optional[str], Optional[str]]:
    for path, text in sources:
        if predicate(path, text):
            return path, text
    return None, None


def _make_edge(
    source: MemberProfile,
    target: MemberProfile,
    *,
    kind: str,
    evidence: str,
    confidence: str,
    evidence_paths: Optional[List[str]] = None,
    evidence_snippet: Optional[str] = None,
) -> ServiceEdge:
    return ServiceEdge(
        source_repository_id=source.repository_id,
        target_repository_id=target.repository_id,
        source_name=source.display_name,
        target_name=target.display_name,
        kind=kind,
        evidence=evidence,
        confidence=confidence,
        evidence_paths=evidence_paths or [],
        evidence_snippet=evidence_snippet,
    )


@dataclass
class MemberProfile:
    repository_id: str
    name: str
    display_name: str
    role: Optional[str]
    status: str
    aliases: Set[str] = field(default_factory=set)
    api_paths: List[str] = field(default_factory=list)
    api_path_sources: Dict[str, str] = field(default_factory=dict)
    corpus: str = ""
    file_sources: List[Tuple[str, str]] = field(default_factory=list)
    package_names: Set[str] = field(default_factory=set)
    proto_messages: Set[str] = field(default_factory=set)
    graph_available: bool = False
    symbol_count: int = 0


@dataclass
class ServiceEdge:
    source_repository_id: str
    target_repository_id: str
    source_name: str
    target_name: str
    kind: str
    evidence: str
    confidence: str = "medium"
    evidence_paths: List[str] = field(default_factory=list)
    evidence_snippet: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_repository_id": self.source_repository_id,
            "target_repository_id": self.target_repository_id,
            "source_name": self.source_name,
            "target_name": self.target_name,
            "kind": self.kind,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "evidence_paths": self.evidence_paths,
            "evidence_snippet": self.evidence_snippet,
            "why_linked": self._why_linked(),
            "cross_repo": True,
        }

    def _why_linked(self) -> str:
        kind_label = self.kind.replace("_", " ")
        if self.evidence_paths:
            paths = ", ".join(f"`{p}`" for p in self.evidence_paths[:3])
            return f"{kind_label}: {self.evidence} (in {paths})"
        return f"{kind_label}: {self.evidence}"


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def _build_aliases(repo: Repository, role: Optional[str]) -> Set[str]:
    aliases: Set[str] = set()
    for raw in (repo.name, repo.github_repo, repo.github_full_name, role):
        if not raw:
            continue
        token = _normalize_token(raw)
        if len(token) >= 3:
            aliases.add(token)
        if "/" in raw:
            for part in raw.split("/"):
                part_token = _normalize_token(part)
                if len(part_token) >= 3:
                    aliases.add(part_token)
    return aliases


def _mermaid_node_id(name: str, used: Dict[str, int]) -> str:
    base = re.sub(r"[^a-zA-Z0-9_]", "_", _normalize_token(name))[:20] or "svc"
    count = used.get(base, 0)
    used[base] = count + 1
    return base if count == 0 else f"{base}_{count}"


def build_service_map_mermaid(
    members: List[MemberProfile],
    edges: List[ServiceEdge],
) -> str:
    if not members:
        return ""

    id_map: Dict[str, str] = {}
    used: Dict[str, int] = {}
    for member in members:
        id_map[member.repository_id] = _mermaid_node_id(member.display_name, used)

    lines = ["flowchart LR"]
    for member in members:
        nid = id_map[member.repository_id]
        role = f"<br/>{member.role}" if member.role else ""
        label = f"{member.display_name}{role}".replace('"', "'")
        lines.append(f'    {nid}["{label}"]')

    link_indices: List[int] = []
    seen_pairs: Set[Tuple[str, str, str]] = set()
    link_idx = 0
    for edge in edges:
        src = id_map.get(edge.source_repository_id)
        tgt = id_map.get(edge.target_repository_id)
        if not src or not tgt or src == tgt:
            continue
        key = (edge.source_repository_id, edge.target_repository_id, edge.kind)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        safe_label = edge.kind.replace("_", " ")
        lines.append(f"    {src} -->|{safe_label}| {tgt}")
        link_indices.append(link_idx)
        link_idx += 1

    lines.extend(
        [
            "",
            "    classDef service fill:#F1EFE8,stroke:#5F5E5A,color:#2C2C2A;",
            "    classDef xrepo fill:#FAECE7,stroke:#993C1D,color:#4A1B0C;",
        ]
    )
    if members:
        lines.append(f"    class {','.join(id_map.values())} service;")

    for idx in link_indices:
        lines.append(f"    linkStyle {idx} stroke:#993C1D,stroke-width:2px")

    return "\n".join(lines)


def build_summary_sentence(
    application_name: str,
    members: List[MemberProfile],
    edges: List[ServiceEdge],
) -> str:
    if len(members) < 2:
        return (
            f"**{application_name}** needs at least two linked repositories to render a "
            "cross-service dependency map."
        )
    if not edges:
        indexed = sum(1 for m in members if m.status == "ready")
        return (
            f"**{application_name}** groups {len(members)} repositories ({indexed} indexed), "
            "but no cross-repo HTTP, OpenAPI, package, or proto links were detected yet. "
            "Re-index members after wiring service clients."
        )

    kinds: Dict[str, int] = {}
    for edge in edges:
        kinds[edge.kind] = kinds.get(edge.kind, 0) + 1
    kind_bits = ", ".join(f"{count} {kind.replace('_', ' ')}" for kind, count in sorted(kinds.items()))
    pairs = len({(e.source_repository_id, e.target_repository_id) for e in edges})
    return (
        f"**{application_name}** connects {len(members)} repositories through "
        f"**{pairs} cross-service link{'s' if pairs != 1 else ''}** ({kind_bits}). "
        "Coral edges in the diagram are cross-repo dependencies — the ones that hurt during refactors."
    )


def _detect_edges(members: List[MemberProfile]) -> List[ServiceEdge]:
    edges: List[ServiceEdge] = []

    for source in members:
        corpus_lower = source.corpus.lower()
        for target in members:
            if source.repository_id == target.repository_id:
                continue

            for alias in sorted(target.aliases, key=len, reverse=True):
                if len(alias) < 3:
                    continue

                def alias_match(_path: str, text: str, token: str = alias) -> bool:
                    return token in text.lower()

                path, text = _first_file_match(source.file_sources, alias_match)
                if path or alias in corpus_lower:
                    snippet_text = text or source.corpus
                    edges.append(
                        _make_edge(
                            source,
                            target,
                            kind="name_reference",
                            evidence=f"References `{alias}` in {source.display_name} source",
                            confidence="low",
                            evidence_paths=[path] if path else [],
                            evidence_snippet=_snippet(snippet_text, alias) if snippet_text else None,
                        )
                    )
                    break

            for url in HTTP_URL_RE.findall(source.corpus):
                host = url.split("://", 1)[-1].split("/")[0].lower()
                if not any(alias in host for alias in target.aliases if len(alias) >= 4):
                    continue

                def url_match(_path: str, text: str, needle: str = url[:60]) -> bool:
                    return needle in text

                path, text = _first_file_match(source.file_sources, url_match)
                edges.append(
                    _make_edge(
                        source,
                        target,
                        kind="http_client",
                        evidence=f"HTTP URL `{url[:80]}`",
                        confidence="high",
                        evidence_paths=[path] if path else [],
                        evidence_snippet=_snippet(text or source.corpus, url[:40]) if text or source.corpus else None,
                    )
                )
                break

            for match in FEIGN_RE.findall(source.corpus):
                token = _normalize_token(match)
                if token not in target.aliases:
                    continue

                def feign_match(_path: str, text: str, needle: str = match) -> bool:
                    return f"@FeignClient" in text and needle in text

                path, text = _first_file_match(source.file_sources, feign_match)
                edges.append(
                    _make_edge(
                        source,
                        target,
                        kind="http_client",
                        evidence=f"@FeignClient `{match}`",
                        confidence="high",
                        evidence_paths=[path] if path else [],
                        evidence_snippet=_snippet(text or source.corpus, match) if text or source.corpus else None,
                    )
                )
                break

            for client_url in REST_CLIENT_RE.findall(source.corpus):
                host = client_url.split("://", 1)[-1].split("/")[0].lower() if "://" in client_url else client_url.lower()
                if not any(alias in host or alias in client_url.lower() for alias in target.aliases if len(alias) >= 3):
                    continue

                def client_match(_path: str, text: str, needle: str = client_url[:40]) -> bool:
                    return needle in text

                path, text = _first_file_match(source.file_sources, client_match)
                edges.append(
                    _make_edge(
                        source,
                        target,
                        kind="http_client",
                        evidence=f"HTTP client call `{client_url[:80]}`",
                        confidence="high",
                        evidence_paths=[path] if path else [],
                        evidence_snippet=_snippet(text or source.corpus, client_url[:30]) if text or source.corpus else None,
                    )
                )
                break

            for pkg in source.package_names:
                token = _normalize_token(pkg)
                if token not in target.aliases:
                    continue

                def pkg_match(path: str, text: str, artifact: str = pkg) -> bool:
                    return (
                        path.endswith("pom.xml") or path.endswith("package.json")
                    ) and artifact in text

                path, text = _first_file_match(source.file_sources, pkg_match)
                edges.append(
                    _make_edge(
                        source,
                        target,
                        kind="package_dep",
                        evidence=f"Package dependency `{pkg}`",
                        confidence="medium",
                        evidence_paths=[path] if path else [],
                        evidence_snippet=_snippet(text or source.corpus, pkg) if text or source.corpus else None,
                    )
                )
                break

            shared_proto = source.proto_messages & target.proto_messages
            if shared_proto:
                msg = sorted(shared_proto)[0]

                def proto_match(path: str, text: str, message: str = msg) -> bool:
                    return path.endswith(".proto") and f"message {message}" in text

                path, text = _first_file_match(source.file_sources, proto_match)
                edges.append(
                    _make_edge(
                        source,
                        target,
                        kind="shared_proto",
                        evidence=f"Shared proto message `{msg}`",
                        confidence="medium",
                        evidence_paths=[path] if path else [],
                        evidence_snippet=_snippet(text or source.corpus, msg) if text or source.corpus else None,
                    )
                )

            for api_path in target.api_paths:
                if not api_path or api_path not in source.corpus:
                    continue

                def path_match(_path: str, text: str, needle: str = api_path) -> bool:
                    return needle in text

                file_path, text = _first_file_match(source.file_sources, path_match)
                provider_path = target.api_path_sources.get(api_path)
                evidence_paths = [p for p in [file_path, provider_path] if p]
                edges.append(
                    _make_edge(
                        source,
                        target,
                        kind="openapi_consumer",
                        evidence=f"References API path `{api_path}`",
                        confidence="high",
                        evidence_paths=evidence_paths,
                        evidence_snippet=_snippet(text or source.corpus, api_path) if text or source.corpus else None,
                    )
                )
                break

    deduped: List[ServiceEdge] = []
    seen: Set[Tuple[str, str, str]] = set()
    for edge in edges:
        key = (edge.source_repository_id, edge.target_repository_id, edge.kind)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(edge)
    return deduped


class ApplicationGraphService:
    def __init__(self, db: Session):
        self.db = db

    def _cache_key(self, tenant_id: str, application_id: str) -> str:
        return f"{tenant_id}:{application_id}"

    def _load_disk(self, tenant_id: str, application_id: str) -> Optional[Dict[str, Any]]:
        path = get_application_analysis_dir(tenant_id, application_id) / SERVICE_MAP_FILE
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _save_disk(self, tenant_id: str, application_id: str, payload: Dict[str, Any]) -> None:
        out_dir = get_application_analysis_dir(tenant_id, application_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / SERVICE_MAP_FILE).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _build_member_profile(
        self, repo: Repository, membership: ApplicationRepository
    ) -> MemberProfile:
        display = repo.github_full_name or repo.name
        profile = MemberProfile(
            repository_id=repo.id,
            name=repo.name,
            display_name=display,
            role=membership.role,
            status=repo.status or "unknown",
            aliases=_build_aliases(repo, membership.role),
        )

        site = (
            self.db.query(RepositoryWikiSite)
            .filter(RepositoryWikiSite.repository_id == repo.id)
            .order_by(RepositoryWikiSite.updated_at.desc())
            .first()
        )
        summary = (site.summary_json if site else None) or {}
        wiki_bits: List[str] = []
        for key in ("overview", "functionality", "api_surface", "business_logic_layer"):
            val = summary.get(key)
            if isinstance(val, dict):
                wiki_bits.append(json.dumps(val))
            elif isinstance(val, list):
                wiki_bits.append(json.dumps(val))
            elif isinstance(val, str):
                wiki_bits.append(val)

        api_surface = summary.get("api_surface") or []
        if isinstance(api_surface, list):
            for item in api_surface:
                if isinstance(item, dict):
                    path_val = None
                    for field in ("path", "route", "endpoint"):
                        if item.get(field):
                            path_val = str(item[field])
                            profile.api_paths.append(path_val)
                            if item.get("file"):
                                profile.api_path_sources[path_val] = str(item["file"])
                            break
                    if not path_val and item.get("file"):
                        profile.api_path_sources.setdefault(str(item["file"]), str(item["file"]))
                elif isinstance(item, str):
                    for match in OPENAPI_PATH_RE.findall(item):
                        profile.api_paths.append(match)

        chunks = (
            self.db.query(CodeChunk)
            .filter(CodeChunk.repository_id == repo.id)
            .limit(250)
            .all()
        )
        chunk_texts: List[str] = []
        for chunk in chunks:
            path = chunk.file_path or "unknown"
            text = chunk.content or ""
            profile.file_sources.append((path, text))
            chunk_texts.append(text)
            path_lower = path.lower()
            if path_lower.endswith("pom.xml"):
                profile.package_names.update(ARTIFACT_RE.findall(text))
            if path_lower.endswith("package.json") and '"dependencies"' in text:
                profile.package_names.update(NPM_DEP_RE.findall(text))
            if path_lower.endswith(".proto"):
                profile.proto_messages.update(PROTO_MESSAGE_RE.findall(text))
            if path_lower.endswith((".yaml", ".yml", ".json")) and (
                "openapi" in text.lower() or "swagger" in text.lower()
            ):
                for match in OPENAPI_PATH_RE.findall(text):
                    profile.api_paths.append(match)
                    profile.api_path_sources.setdefault(match, path)

        profile.corpus = "\n".join(wiki_bits + chunk_texts)[:500_000]

        attrs = (
            self.db.query(RepositoryAnalysisAttribute)
            .filter(RepositoryAnalysisAttribute.repository_id == repo.id)
            .all()
        )
        for attr in attrs:
            if attr.value_text:
                profile.corpus += f"\n{attr.attribute_key}={attr.value_text}"

        from app.services.intelligence.graph_query_service import GraphQueryService

        stats = GraphQueryService(self.db).get_graph_stats(repo)
        profile.graph_available = bool(stats.get("available"))
        profile.symbol_count = int(stats.get("symbol_count") or 0)
        return profile

    def compute_service_map(
        self,
        tenant_id: str,
        application_id: str,
        *,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        cache_key = self._cache_key(tenant_id, application_id)
        if use_cache and cache_key in _CACHE:
            ts, payload = _CACHE[cache_key]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return {**payload, "cached": True}

        if use_cache:
            disk = self._load_disk(tenant_id, application_id)
            if disk and disk.get("schema_version") == SERVICE_MAP_SCHEMA_VERSION:
                _CACHE[cache_key] = (time.time(), disk)
                return {**disk, "cached": True}

        app = (
            self.db.query(Application)
            .filter(Application.id == application_id, Application.tenant_id == tenant_id)
            .first()
        )
        if not app:
            return {"available": False, "error": "Application not found"}

        rows = (
            self.db.query(ApplicationRepository, Repository)
            .join(Repository, ApplicationRepository.repository_id == Repository.id)
            .filter(ApplicationRepository.application_id == application_id)
            .order_by(Repository.name.asc())
            .all()
        )

        members = [self._build_member_profile(repo, membership) for membership, repo in rows]
        edges = _detect_edges(members)
        mermaid = build_service_map_mermaid(members, edges) if len(members) >= 2 else ""
        summary = build_summary_sentence(app.name, members, edges)

        payload = {
            "schema_version": SERVICE_MAP_SCHEMA_VERSION,
            "application_id": application_id,
            "application_name": app.name,
            "view_type": VIEW_TYPE,
            "summary": summary,
            "mermaid": mermaid,
            "nodes": [
                {
                    "repository_id": m.repository_id,
                    "name": m.display_name,
                    "role": m.role,
                    "status": m.status,
                    "graph_available": m.graph_available,
                    "symbol_count": m.symbol_count,
                }
                for m in members
            ],
            "edges": [e.to_dict() for e in edges],
            "cross_repo": [e.to_dict() for e in edges],
            "repository_count": len(members),
            "edge_count": len(edges),
            "available": len(members) >= 2,
            "has_dependencies": len(edges) > 0,
            "cached": False,
        }
        self._save_disk(tenant_id, application_id, payload)
        _CACHE[cache_key] = (time.time(), payload)
        logger.info(
            "Service map for application %s: %s repos, %s edges",
            application_id,
            len(members),
            len(edges),
        )
        try:
            from app.services.modernize.assessment_service import AssessmentService

            AssessmentService(self.db).maybe_auto_assess_application_after_analysis(
                tenant_id, application_id
            )
        except Exception as assess_err:
            logger.warning(
                "Optional auto-assessment after application analysis failed for %s: %s",
                application_id,
                assess_err,
            )
        return payload

    def application_blast_radius(
        self,
        tenant_id: str,
        application_id: str,
        repository_id: str,
        symbol: str,
        *,
        hops: int = 1,
    ) -> Dict[str, Any]:
        app = (
            self.db.query(Application)
            .filter(Application.id == application_id, Application.tenant_id == tenant_id)
            .first()
        )
        if not app:
            return {"available": False, "error": "Application not found"}

        membership = (
            self.db.query(ApplicationRepository)
            .filter(
                ApplicationRepository.application_id == application_id,
                ApplicationRepository.repository_id == repository_id,
            )
            .first()
        )
        if not membership:
            return {"available": False, "error": "Repository is not in this application"}

        repo = (
            self.db.query(Repository)
            .filter(Repository.id == repository_id, Repository.tenant_id == tenant_id)
            .first()
        )
        if not repo:
            return {"available": False, "error": "Repository not found"}

        result = BlastRadiusService(self.db).compute(repo, symbol, hops=hops)
        service_map = self.compute_service_map(tenant_id, application_id)
        member_ids = {n["repository_id"] for n in service_map.get("nodes") or []}

        cross_repo_hints = [
            e
            for e in service_map.get("edges") or []
            if e.get("source_repository_id") == repository_id
            or e.get("target_repository_id") == repository_id
        ]

        result["application_id"] = application_id
        result["repository_id"] = repository_id
        result["member_repository_ids"] = sorted(member_ids)
        result["cross_repo"] = cross_repo_hints
        return result


def invalidate_application_graph_cache(tenant_id: str, application_id: str) -> None:
    _CACHE.pop(f"{tenant_id}:{application_id}", None)

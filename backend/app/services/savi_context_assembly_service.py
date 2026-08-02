"""Context assembly for Savi work items — Phase T4 (portal-first).

Resolves Application → repos under Team ACL, packs GPS substrate excerpts
into savi_work_items.context_pack. Human URLs/notes stay as pending until T5
connectors. Direct GPS service calls (not MCP).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.core.database import (
    Application,
    ApplicationRepository,
    Repository,
    SaviWorkItem,
    TeamApplication,
)
from app.core.logger import logger
from app.services.intelligence.application_service import ApplicationService
from app.services.intelligence.chat_scope import ChatScope
from app.services.intelligence.hybrid_search_service import HybridSearchService
from app.services.intelligence.retrieval_service import RetrievalService
from app.services.savi_work_queue_service import SaviWorkQueueService
from app.services.team_service import TeamService

CONTEXT_REF_TYPES = ("url", "note", "jira_text")


class SaviContextAssemblyService:
    def __init__(self, db: Session):
        self.db = db

    def team_allowed_repository_ids(self, tenant_id: str, team_id: str) -> Set[str]:
        """Repos belonging to Applications linked to this Team."""
        team = TeamService(self.db).get_team(tenant_id, team_id)
        if not team:
            raise ValueError("Team not found")
        app_ids = [
            row[0]
            for row in self.db.query(TeamApplication.application_id)
            .filter(TeamApplication.team_id == team_id)
            .all()
        ]
        if not app_ids:
            return set()
        rows = (
            self.db.query(ApplicationRepository.repository_id)
            .filter(ApplicationRepository.application_id.in_(app_ids))
            .all()
        )
        return {r[0] for r in rows}

    def normalize_context_refs(
        self,
        refs: Optional[List[Dict[str, Any]]],
        extra_repository_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Store shape on SaviWorkItem.context_refs."""
        cleaned_refs: List[Dict[str, Any]] = []
        for raw in refs or []:
            if not isinstance(raw, dict):
                continue
            rtype = (raw.get("type") or "note").lower()
            if rtype not in CONTEXT_REF_TYPES:
                raise ValueError(
                    f"context_refs.type must be one of: {', '.join(CONTEXT_REF_TYPES)}"
                )
            value = (raw.get("value") or "").strip()
            if not value:
                continue
            cleaned_refs.append(
                {
                    "type": rtype,
                    "label": (raw.get("label") or "").strip() or None,
                    "value": value,
                }
            )
        extras = []
        for rid in extra_repository_ids or []:
            if rid and str(rid) not in extras:
                extras.append(str(rid))
        return {
            "refs": cleaned_refs,
            "extra_repository_ids": extras,
        }

    def validate_extra_repos(
        self, tenant_id: str, team_id: str, extra_ids: List[str]
    ) -> List[str]:
        if not extra_ids:
            return []
        allowed = self.team_allowed_repository_ids(tenant_id, team_id)
        bad = [rid for rid in extra_ids if rid not in allowed]
        if bad:
            raise ValueError(
                "extra_repository_ids must belong to Applications on this Team "
                f"(rejected: {', '.join(bad[:5])})"
            )
        return list(extra_ids)

    async def assemble(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        item_id: str,
        *,
        commit: bool = True,
    ) -> SaviWorkItem:
        """
        Build/replace context_pack on a work item.
        Optional Build Project spawn (mode=enhance) deferred — T4 packs only.
        """
        queue = SaviWorkQueueService(self.db)
        item = queue.get(tenant_id, team_id, savi_id, item_id)
        if not item:
            raise ValueError("Work item not found")
        if not item.application_id:
            raise ValueError("Work item needs an application_id before context assembly")

        queue._require_app_on_team(tenant_id, team_id, item.application_id)

        stored = item.context_refs or {}
        if not isinstance(stored, dict):
            stored = {"refs": [], "extra_repository_ids": []}
        extra_ids = self.validate_extra_repos(
            tenant_id, team_id, list(stored.get("extra_repository_ids") or [])
        )
        human_refs = list(stored.get("refs") or [])

        app_svc = ApplicationService(self.db)
        app = app_svc.get_application(tenant_id, item.application_id)
        if not app:
            raise ValueError("Application not found")

        app_repo_ids = app_svc.list_repository_ids(tenant_id, app.id)
        allowed = self.team_allowed_repository_ids(tenant_id, team_id)
        # Never include out-of-team repos (defense in depth)
        app_repo_ids = [rid for rid in app_repo_ids if rid in allowed]
        extra_ids = [rid for rid in extra_ids if rid in allowed and rid not in app_repo_ids]

        repositories = self._repo_dicts(app_repo_ids, app.id)
        extra_repositories = self._repo_dicts(extra_ids, None)

        human_ref_entries = []
        for ref in human_refs:
            entry = dict(ref)
            if entry.get("type") == "url":
                entry["fetch_status"] = "pending_connector"
                # T5: try Confluence fetch when bound
                try:
                    from app.services.connectors.registry import get_active_connector

                    conf = get_active_connector(
                        self.db, tenant_id, team_id, savi_id, "confluence"
                    )
                    url = entry.get("value") or ""
                    if conf and ("confluence" in url.lower() or "/wiki/" in url.lower() or "pageId=" in url):
                        fetched = await conf.fetch_page_by_url(url=url)
                        if fetched.ok:
                            entry["fetch_status"] = fetched.data.get(
                                "fetch_status", "fetched"
                            )
                            entry["title"] = fetched.data.get("title")
                            entry["body_excerpt"] = (fetched.data.get("body_text") or "")[
                                :2000
                            ]
                            if fetched.stubbed:
                                entry["fetch_status"] = "stubbed"
                        else:
                            entry["fetch_status"] = "error"
                            entry["fetch_error"] = fetched.error
                except Exception as e:
                    entry["fetch_status"] = "error"
                    entry["fetch_error"] = str(e)[:200]
            human_ref_entries.append(entry)

        query = self._query_from_item(item)
        substrate = await self._gather_substrate(
            tenant_id,
            application_id=app.id,
            repo_ids=app_repo_ids + extra_ids,
            query=query,
        )

        pack = {
            "assembled_at": datetime.now().isoformat(),
            "application": {"id": app.id, "name": app.name},
            "repositories": repositories,
            "extra_repositories": extra_repositories,
            "human_refs": human_ref_entries,
            "substrate": substrate,
            "brief_markdown": self._brief_markdown(
                item, app, repositories, extra_repositories, human_ref_entries, substrate
            ),
        }

        item.context_pack = pack
        item.updated_at = datetime.now()
        if commit:
            self.db.commit()
            self.db.refresh(item)
        else:
            self.db.flush()

        logger.info(
            "Assembled context pack for work %s (app=%s repos=%d extras=%d)",
            item.id,
            app.id,
            len(repositories),
            len(extra_repositories),
        )
        return item

    async def assemble_if_queued(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        item: SaviWorkItem,
    ) -> SaviWorkItem:
        if item.state != "queued" or not item.application_id:
            return item
        if item.context_pack:
            return item
        try:
            return await self.assemble(
                tenant_id, team_id, savi_id, item.id, commit=True
            )
        except Exception as e:
            logger.warning(
                "Context assembly skipped for work %s: %s", item.id, e
            )
            return item

    def _repo_dicts(
        self, repo_ids: List[str], application_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        if not repo_ids:
            return []
        rows = (
            self.db.query(Repository, ApplicationRepository)
            .outerjoin(
                ApplicationRepository,
                ApplicationRepository.repository_id == Repository.id,
            )
            .filter(Repository.id.in_(repo_ids))
            .all()
        )
        by_id: Dict[str, Dict[str, Any]] = {}
        for repo, link in rows:
            role = None
            if link and (
                application_id is None or link.application_id == application_id
            ):
                role = link.role
            by_id[repo.id] = {
                "id": repo.id,
                "name": repo.github_full_name or repo.name,
                "url": repo.url,
                "role": role,
                "status": repo.status,
            }
        return [by_id[rid] for rid in repo_ids if rid in by_id]

    def _query_from_item(self, item: SaviWorkItem) -> str:
        parts = [item.title or ""]
        if item.description:
            parts.append(item.description[:800])
        return "\n".join(p for p in parts if p).strip() or (item.title or "context")

    async def _gather_substrate(
        self,
        tenant_id: str,
        *,
        application_id: str,
        repo_ids: List[str],
        query: str,
    ) -> Dict[str, Any]:
        notes: List[str] = []
        wiki_summary = ""
        search_hits: List[Dict[str, Any]] = []
        specs: List[Dict[str, Any]] = []

        scope = ChatScope.application(application_id, tenant_id)
        retrieval = RetrievalService(self.db)
        try:
            wiki_summary = retrieval.get_wiki_summary_context_for_scope(scope) or ""
        except Exception as e:
            notes.append(f"wiki_summary unavailable: {e}")

        try:
            sources = await retrieval.retrieve_for_scope(scope, query, top_k=6)
            # Filter to allowed repo set only
            allowed = set(repo_ids)
            for s in sources:
                if s.repository_id and s.repository_id not in allowed:
                    continue
                search_hits.append(
                    {
                        "source": s.source_type,
                        "path": s.file_path,
                        "snippet": (s.excerpt or "")[:500],
                        "score": s.score,
                        "repository_id": s.repository_id,
                        "repository_name": s.repository_name,
                    }
                )
        except Exception as e:
            notes.append(f"retrieval unavailable: {e}")

        # Hybrid search as supplemental (fail-soft); keep only in-scope repos
        try:
            hybrid = HybridSearchService(self.db)
            result = await hybrid.search(
                tenant_id,
                query,
                application_id=application_id,
                limit=8,
            )
            allowed = set(repo_ids)
            for hit in result.get("results") or []:
                rid = hit.get("repository_id")
                if rid and rid not in allowed:
                    continue
                path = hit.get("file_path") or hit.get("path") or hit.get("title")
                if any(h.get("path") == path and h.get("repository_id") == rid for h in search_hits):
                    continue
                search_hits.append(
                    {
                        "source": hit.get("source") or hit.get("type") or "hybrid",
                        "path": path,
                        "snippet": (hit.get("snippet") or hit.get("excerpt") or "")[:500],
                        "score": hit.get("score") or hit.get("rrf_score"),
                        "repository_id": rid,
                        "repository_name": hit.get("repository_name"),
                    }
                )
        except Exception as e:
            notes.append(f"hybrid_search unavailable: {e}")

        try:
            from app.services.tenant_config_service import TenantConfigService
            from app.services.intelligence.spec_drift_service import SpecDriftService

            layer = TenantConfigService(self.db).get_spec_layer_settings(tenant_id)
            if layer.get("enabled"):
                drift = SpecDriftService(self.db)
                for rid in repo_ids:
                    for spec in drift.list_specs_for_tenant(tenant_id, rid)[:20]:
                        specs.append(
                            {
                                "path": spec.get("path") or spec.get("rel_path"),
                                "repo_id": rid,
                                "repository_name": spec.get("repository_name"),
                                "title": spec.get("title") or spec.get("name"),
                            }
                        )
        except Exception as e:
            notes.append(f"specs unavailable: {e}")

        return {
            "wiki_summary": wiki_summary[:6000] if wiki_summary else "",
            "search_hits": search_hits[:12],
            "specs": specs[:30],
            "notes": notes,
        }

    def _brief_markdown(
        self,
        item: SaviWorkItem,
        app: Application,
        repositories: List[Dict[str, Any]],
        extra_repositories: List[Dict[str, Any]],
        human_refs: List[Dict[str, Any]],
        substrate: Dict[str, Any],
    ) -> str:
        lines = [
            f"# Context brief: {item.title}",
            "",
            f"**Application:** {app.name} (`{app.id}`)",
            "",
            "## In-scope repositories",
        ]
        if repositories:
            for r in repositories:
                role = f" ({r['role']})" if r.get("role") else ""
                lines.append(f"- {r['name']}{role} — {r.get('url') or ''}")
        else:
            lines.append("- _(none linked to application)_")

        if extra_repositories:
            lines.extend(["", "## Extra repositories (portal)"])
            for r in extra_repositories:
                lines.append(f"- {r['name']} — {r.get('url') or ''}")

        if human_refs:
            lines.extend(["", "## Human-provided context"])
            for ref in human_refs:
                label = ref.get("label") or ref.get("type")
                status = ref.get("fetch_status")
                suffix = f" [{status}]" if status else ""
                lines.append(f"- **{label}**{suffix}: {ref.get('value')}")

        wiki = substrate.get("wiki_summary") or ""
        if wiki:
            lines.extend(["", "## Wiki / substrate summary", "", wiki])

        hits = substrate.get("search_hits") or []
        if hits:
            lines.extend(["", "## Related code / wiki hits"])
            for h in hits[:8]:
                path = h.get("path") or "?"
                repo = h.get("repository_name") or h.get("repository_id") or ""
                snip = (h.get("snippet") or "").replace("\n", " ")[:160]
                lines.append(f"- `{repo}` `{path}` — {snip}")

        specs = substrate.get("specs") or []
        if specs:
            lines.extend(["", "## Specs"])
            for s in specs[:15]:
                lines.append(
                    f"- `{s.get('repository_name') or s.get('repo_id')}` "
                    f"`{s.get('path')}`"
                )

        notes = substrate.get("notes") or []
        if notes:
            lines.extend(["", "## Assembly notes"])
            for n in notes:
                lines.append(f"- {n}")

        lines.extend(
            [
                "",
                "---",
                "_Assembled by Savi GPS T4 (direct substrate; Confluence/Jira fetch pending T5)._",
            ]
        )
        return "\n".join(lines)

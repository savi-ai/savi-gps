"""Jira connector for Savi — comment / transition / get issue (T5 thin slice)."""
from __future__ import annotations

from typing import Any, Dict, Optional

import aiohttp
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SaviConnectorBinding
from app.core.logger import logger
from app.services.connectors.base import ConnectorResult
from app.services.connectors.binding_service import SaviConnectorBindingService


class SaviJiraConnector:
    def __init__(self, db: Session, binding: SaviConnectorBinding):
        self.db = db
        self.binding = binding
        self.config = dict(binding.config_json or {})
        self._bindings = SaviConnectorBindingService(db)

    def _auth_headers(self) -> Dict[str, str]:
        email = self.config.get("email") or self.config.get("user_email")
        token = self._bindings.get_secret(self.binding)
        if not email or not token:
            raise ValueError("Jira binding needs config.email and a secret (API token)")
        import base64

        raw = f"{email}:{token}".encode("utf-8")
        return {
            "Authorization": f"Basic {base64.b64encode(raw).decode('ascii')}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _base_url(self) -> str:
        base = (self.config.get("base_url") or "").rstrip("/")
        if not base:
            raise ValueError("Jira binding needs config.base_url")
        return base

    async def _request(
        self, method: str, path: str, json_body: Optional[Dict[str, Any]] = None
    ) -> Any:
        url = path if path.startswith("http") else f"{self._base_url()}{path}"
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method, url, headers=self._auth_headers(), json=json_body
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise ValueError(f"Jira API {resp.status}: {text[:500]}")
                if not text:
                    return None
                return await resp.json()

    async def add_comment(self, *, issue_key: str, body: str) -> ConnectorResult:
        if not settings.JIRA_ENABLED and not self.config.get("force_live"):
            return ConnectorResult(
                ok=True,
                stubbed=True,
                data={"issue_key": issue_key, "body": body, "stub": True},
            )
        try:
            data = await self._request(
                "POST",
                f"/rest/api/3/issue/{issue_key}/comment",
                {"body": {"type": "doc", "version": 1, "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": body}]}
                ]}},
            )
            return ConnectorResult(
                ok=True, data={"issue_key": issue_key, "comment_id": (data or {}).get("id")}
            )
        except Exception as e:
            logger.warning("Jira add_comment failed: %s", e)
            return ConnectorResult(ok=False, error=str(e)[:500])

    async def transition_issue(
        self, *, issue_key: str, transition_name: str
    ) -> ConnectorResult:
        if not settings.JIRA_ENABLED and not self.config.get("force_live"):
            return ConnectorResult(
                ok=True,
                stubbed=True,
                data={
                    "issue_key": issue_key,
                    "transition": transition_name,
                    "stub": True,
                },
            )
        try:
            transitions = await self._request(
                "GET", f"/rest/api/3/issue/{issue_key}/transitions"
            )
            target = None
            for t in (transitions or {}).get("transitions") or []:
                if (t.get("name") or "").lower() == transition_name.lower():
                    target = t
                    break
            if not target:
                return ConnectorResult(
                    ok=False,
                    error=f"Transition '{transition_name}' not found on {issue_key}",
                )
            await self._request(
                "POST",
                f"/rest/api/3/issue/{issue_key}/transitions",
                {"transition": {"id": target["id"]}},
            )
            return ConnectorResult(
                ok=True,
                data={"issue_key": issue_key, "transition": transition_name},
            )
        except Exception as e:
            logger.warning("Jira transition failed: %s", e)
            return ConnectorResult(ok=False, error=str(e)[:500])

    async def get_issue(self, *, issue_key: str) -> ConnectorResult:
        if not settings.JIRA_ENABLED and not self.config.get("force_live"):
            return ConnectorResult(
                ok=True,
                stubbed=True,
                data={
                    "issue_key": issue_key,
                    "summary": f"(stub) {issue_key}",
                    "description": "",
                    "stub": True,
                },
            )
        try:
            data = await self._request("GET", f"/rest/api/3/issue/{issue_key}")
            fields = (data or {}).get("fields") or {}
            return ConnectorResult(
                ok=True,
                data={
                    "issue_key": issue_key,
                    "summary": fields.get("summary"),
                    "description": fields.get("description"),
                    "status": (fields.get("status") or {}).get("name"),
                },
            )
        except Exception as e:
            return ConnectorResult(ok=False, error=str(e)[:500])

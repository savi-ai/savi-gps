"""Confluence connector — read page by URL (T5)."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse, parse_qs, unquote

import aiohttp
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SaviConnectorBinding
from app.core.logger import logger
from app.services.connectors.base import ConnectorResult
from app.services.connectors.binding_service import SaviConnectorBindingService


def parse_confluence_url(url: str) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
    """
    Return (base_url, page_id, space_key_hint) from common Confluence URL shapes.
    """
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    base = f"{parsed.scheme}://{parsed.netloc}"
    qs = parse_qs(parsed.query)
    if "pageId" in qs:
        return base, qs["pageId"][0], None
    # /wiki/spaces/KEY/pages/12345/Title
    m = re.search(r"/spaces/([^/]+)/pages/(\d+)", parsed.path or "")
    if m:
        return base, m.group(2), m.group(1)
    # /pages/viewpage.action?pageId=
    if "viewpage.action" in (parsed.path or "") and "pageId" in qs:
        return base, qs["pageId"][0], None
    return base, None, None


class SaviConfluenceConnector:
    def __init__(self, db: Session, binding: SaviConnectorBinding):
        self.db = db
        self.binding = binding
        self.config = dict(binding.config_json or {})
        self._bindings = SaviConnectorBindingService(db)

    def _auth_headers(self) -> Dict[str, str]:
        email = self.config.get("email") or self.config.get("user_email")
        token = self._bindings.get_secret(self.binding)
        if not email or not token:
            raise ValueError(
                "Confluence binding needs config.email and a secret (API token)"
            )
        import base64

        raw = f"{email}:{token}".encode("utf-8")
        return {
            "Authorization": f"Basic {base64.b64encode(raw).decode('ascii')}",
            "Accept": "application/json",
        }

    async def fetch_page_by_url(self, *, url: str) -> ConnectorResult:
        if not settings.CONFLUENCE_ENABLED and not self.config.get("force_live"):
            return ConnectorResult(
                ok=True,
                stubbed=True,
                data={
                    "url": url,
                    "title": "(stub) Confluence page",
                    "body_text": "",
                    "fetch_status": "stubbed",
                    "stub": True,
                },
            )

        parsed = parse_confluence_url(url)
        if not parsed:
            return ConnectorResult(ok=False, error="Invalid Confluence URL")
        base, page_id, _space = parsed
        config_base = (self.config.get("base_url") or "").rstrip("/")
        if config_base:
            base = config_base
        if not page_id:
            return ConnectorResult(
                ok=False,
                error="Could not extract pageId from URL (paste a /pages/{id}/ link)",
            )

        try:
            api = f"{base}/wiki/rest/api/content/{page_id}?expand=body.storage,space"
            async with aiohttp.ClientSession() as session:
                async with session.get(api, headers=self._auth_headers()) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        raise ValueError(f"Confluence API {resp.status}: {text[:400]}")
                    data = await resp.json()
            storage = ((data.get("body") or {}).get("storage") or {}).get("value") or ""
            # Crude HTML strip for brief packing
            body_text = re.sub(r"<[^>]+>", " ", storage)
            body_text = re.sub(r"\s+", " ", body_text).strip()
            return ConnectorResult(
                ok=True,
                data={
                    "url": url,
                    "page_id": page_id,
                    "title": data.get("title"),
                    "space": (data.get("space") or {}).get("key"),
                    "body_text": body_text[:12000],
                    "fetch_status": "fetched",
                },
            )
        except Exception as e:
            logger.warning("Confluence fetch failed: %s", e)
            return ConnectorResult(
                ok=False,
                error=str(e)[:500],
                data={"url": url, "fetch_status": "error"},
            )

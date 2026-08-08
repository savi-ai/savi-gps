"""Resolve Savi connector implementations from bindings."""
from __future__ import annotations

from typing import Any, Optional, Union

from sqlalchemy.orm import Session

from app.core.database import SaviConnectorBinding
from app.services.connectors.binding_service import SaviConnectorBindingService
from app.services.connectors.confluence_connector import SaviConfluenceConnector
from app.services.connectors.github_connector import SaviGitHubConnector
from app.services.connectors.jira_connector import SaviJiraConnector
from app.services.connectors.slack_connector import SaviSlackConnector

ConnectorImpl = Union[
    SaviGitHubConnector,
    SaviJiraConnector,
    SaviSlackConnector,
    SaviConfluenceConnector,
]


def get_connector(
    db: Session,
    binding: SaviConnectorBinding,
) -> ConnectorImpl:
    ctype = (binding.connector_type or "").lower()
    if ctype == "github":
        return SaviGitHubConnector(db, binding)
    if ctype == "jira":
        return SaviJiraConnector(db, binding)
    if ctype == "slack":
        return SaviSlackConnector(db, binding)
    if ctype == "confluence":
        return SaviConfluenceConnector(db, binding)
    raise ValueError(f"Unknown connector_type: {ctype}")


def get_active_connector(
    db: Session,
    tenant_id: str,
    team_id: str,
    savi_id: str,
    connector_type: str,
) -> Optional[ConnectorImpl]:
    binding = SaviConnectorBindingService(db).get_active(
        tenant_id, team_id, savi_id, connector_type
    )
    if not binding:
        return None
    return get_connector(db, binding)

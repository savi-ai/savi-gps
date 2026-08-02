"""Connector protocols for Savi Teammate (T5)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

CONNECTOR_TYPES = ("github", "jira", "slack", "confluence")


@dataclass
class ConnectorResult:
    ok: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    stubbed: bool = False


class GitHubConnector(Protocol):
    async def open_pull_request(
        self,
        *,
        repository_id: str,
        branch: str,
        base_branch: Optional[str],
        title: str,
        body: str,
        files: List[Dict[str, str]],
    ) -> ConnectorResult: ...

    async def get_pr_checks(
        self, *, repository_id: str, pr_number: int
    ) -> ConnectorResult: ...

    async def list_pr_comments(
        self, *, repository_id: str, pr_number: int
    ) -> ConnectorResult: ...


class JiraConnector(Protocol):
    async def add_comment(self, *, issue_key: str, body: str) -> ConnectorResult: ...

    async def transition_issue(
        self, *, issue_key: str, transition_name: str
    ) -> ConnectorResult: ...

    async def get_issue(self, *, issue_key: str) -> ConnectorResult: ...


class SlackConnector(Protocol):
    async def post_message(
        self, *, text: str, thread_ts: Optional[str] = None
    ) -> ConnectorResult: ...

    async def ask_question(
        self, *, text: str, thread_ts: Optional[str] = None
    ) -> ConnectorResult: ...


class ConfluenceConnector(Protocol):
    async def fetch_page_by_url(self, *, url: str) -> ConnectorResult: ...

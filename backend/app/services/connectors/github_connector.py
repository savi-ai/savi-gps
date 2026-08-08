"""GitHub connector for Savi — branch / files / PR / checks (T5)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.database import Repository, SaviConnectorBinding, SaviWorkItem
from app.core.logger import logger
from app.services.connectors.base import ConnectorResult
from app.services.connectors.binding_service import SaviConnectorBindingService
from app.services.intelligence.github_client import GitHubApiError, GitHubClient
from app.services.intelligence.github_credential_service import GitHubCredentialService


def _split_owner_repo(repository: Repository) -> Optional[Tuple[str, str]]:
    full = repository.github_full_name or ""
    if "/" in full:
        owner, name = full.split("/", 1)
        if owner and name:
            return owner, name
    owner = repository.github_owner or repository.github_org
    name = repository.github_repo or repository.name
    if owner and name:
        return owner, name
    return None


class SaviGitHubConnector:
    def __init__(
        self,
        db: Session,
        binding: SaviConnectorBinding,
    ):
        self.db = db
        self.binding = binding
        self.config = dict(binding.config_json or {})

    def _client_for_repo(self, repository: Repository) -> GitHubClient:
        cred_svc = GitHubCredentialService(self.db)
        cred_id = (
            self.config.get("github_credential_id")
            or repository.github_credential_id
        )
        if not cred_id:
            raise ValueError(
                "No GitHub credential: bind github_credential_id on the "
                "Savi GitHub connector or on the repository"
            )
        cred = cred_svc.get_credential(self.binding.tenant_id, cred_id)
        if not cred:
            raise ValueError("GitHub credential not found or inactive")
        token = cred_svc.get_token(cred)
        if not token:
            raise ValueError("Could not decrypt GitHub token")
        return GitHubClient(token)

    async def open_pull_request(
        self,
        *,
        repository_id: str,
        branch: str,
        base_branch: Optional[str],
        title: str,
        body: str,
        files: List[Dict[str, str]],
        idempotency_key: Optional[str] = None,
    ) -> ConnectorResult:
        repo = (
            self.db.query(Repository)
            .filter(
                Repository.id == repository_id,
                Repository.tenant_id == self.binding.tenant_id,
            )
            .first()
        )
        if not repo:
            return ConnectorResult(ok=False, error="Repository not found")

        owner_repo = _split_owner_repo(repo)
        if not owner_repo:
            return ConnectorResult(
                ok=False, error="Repository missing GitHub owner/name"
            )
        owner, repo_name = owner_repo

        if not files:
            return ConnectorResult(ok=False, error="files list is required")

        try:
            from app.services.agent_runtime.outbound_scrub import scrub_structure

            scrubbed_files, _ = scrub_structure(files)
            files = scrubbed_files if isinstance(scrubbed_files, list) else files

            client = self._client_for_repo(repo)
            base = base_branch or repo.default_branch or "main"
            base_sha = await client.get_ref_sha(owner, repo_name, f"heads/{base}")
            await client.create_branch(owner, repo_name, branch, base_sha)

            for f in files:
                path = (f.get("path") or "").strip()
                content = f.get("content")
                if not path or content is None:
                    continue
                sha = await client.get_file_sha(owner, repo_name, path, ref=branch)
                await client.put_file(
                    owner,
                    repo_name,
                    path,
                    content,
                    message=f"savi: update {path}",
                    branch=branch,
                    sha=sha,
                )

            # create-PR-by-head (ADR 0010 §5b) — client.create_pull_request is idempotent
            pr = await client.create_pull_request(
                owner,
                repo_name,
                title=title,
                body=body,
                head=branch,
                base=base,
            )
            data = {
                "pr_url": pr.get("html_url"),
                "pr_number": pr.get("number"),
                "branch": branch,
                "base_branch": base,
                "base_sha": base_sha,
                "repository_id": repo.id,
                "github_full_name": repo.github_full_name or f"{owner}/{repo_name}",
                "idempotency_key": idempotency_key,
                "reused_existing_pr": bool(pr.get("_reused")) or False,
            }
            return ConnectorResult(ok=True, data=data)
        except (GitHubApiError, ValueError) as e:
            logger.warning("Savi GitHub open_pr failed: %s", e)
            return ConnectorResult(ok=False, error=str(e)[:800])

    async def get_pr_checks(
        self, *, repository_id: str, pr_number: int
    ) -> ConnectorResult:
        repo = (
            self.db.query(Repository)
            .filter(
                Repository.id == repository_id,
                Repository.tenant_id == self.binding.tenant_id,
            )
            .first()
        )
        if not repo:
            return ConnectorResult(ok=False, error="Repository not found")
        owner_repo = _split_owner_repo(repo)
        if not owner_repo:
            return ConnectorResult(ok=False, error="Repository missing GitHub owner/name")
        owner, repo_name = owner_repo
        try:
            client = self._client_for_repo(repo)
            pr = await client._request(
                "GET", f"/repos/{owner}/{repo_name}/pulls/{pr_number}"
            )
            head_sha = (pr.get("head") or {}).get("sha")
            if not head_sha:
                return ConnectorResult(ok=False, error="PR head SHA missing")
            checks = await client._request(
                "GET",
                f"/repos/{owner}/{repo_name}/commits/{head_sha}/check-runs",
            )
            runs = checks.get("check_runs") or []
            return ConnectorResult(
                ok=True,
                data={
                    "pr_number": pr_number,
                    "head_sha": head_sha,
                    "check_runs": [
                        {
                            "name": r.get("name"),
                            "status": r.get("status"),
                            "conclusion": r.get("conclusion"),
                        }
                        for r in runs[:50]
                    ],
                },
            )
        except (GitHubApiError, ValueError) as e:
            return ConnectorResult(ok=False, error=str(e)[:800])

    async def list_pr_comments(
        self, *, repository_id: str, pr_number: int
    ) -> ConnectorResult:
        repo = (
            self.db.query(Repository)
            .filter(
                Repository.id == repository_id,
                Repository.tenant_id == self.binding.tenant_id,
            )
            .first()
        )
        if not repo:
            return ConnectorResult(ok=False, error="Repository not found")
        owner_repo = _split_owner_repo(repo)
        if not owner_repo:
            return ConnectorResult(ok=False, error="Repository missing GitHub owner/name")
        owner, repo_name = owner_repo
        try:
            client = self._client_for_repo(repo)
            comments = await client._request(
                "GET",
                f"/repos/{owner}/{repo_name}/pulls/{pr_number}/comments",
            )
            issue_comments = await client._request(
                "GET",
                f"/repos/{owner}/{repo_name}/issues/{pr_number}/comments",
            )
            return ConnectorResult(
                ok=True,
                data={
                    "review_comments": [
                        {
                            "id": c.get("id"),
                            "user": (c.get("user") or {}).get("login"),
                            "body": c.get("body"),
                            "path": c.get("path"),
                        }
                        for c in (comments or [])[:50]
                    ],
                    "issue_comments": [
                        {
                            "id": c.get("id"),
                            "user": (c.get("user") or {}).get("login"),
                            "body": c.get("body"),
                        }
                        for c in (issue_comments or [])[:50]
                    ],
                },
            )
        except (GitHubApiError, ValueError) as e:
            return ConnectorResult(ok=False, error=str(e)[:800])

    async def open_pr_for_work_item(
        self,
        item: SaviWorkItem,
        *,
        repository_id: str,
        files: Optional[List[Dict[str, str]]] = None,
        title: Optional[str] = None,
        body: Optional[str] = None,
        attempt: int = 1,
    ) -> ConnectorResult:
        """Open PR for a work item using deterministic branch + create-PR-by-head."""
        from app.services.agent_runtime.contracts import IdempotencyKey

        short = (item.id or "")[:8]
        key = IdempotencyKey(
            tenant_id=item.tenant_id,
            repo_id=repository_id,
            work_ref=item.id,
            action_type="open_pr",
            attempt=attempt,
        )
        branch = key.branch_name(prefix="savi")
        brief = ""
        if item.context_pack and isinstance(item.context_pack, dict):
            brief = item.context_pack.get("brief_markdown") or ""
        default_files = files or [
            {
                "path": f".savi/work/{short}/context-brief.md",
                "content": brief
                or f"# {item.title}\n\n{item.description or ''}\n",
            }
        ]
        pr_title = title or f"[Savi] {item.title}"
        pr_body = body or (
            f"Opened by Savi Teammate for work item `{item.id}`.\n\n"
            f"**Source:** {item.source}"
            + (f" · `{item.external_ref}`" if item.external_ref else "")
            + f"\n\n**Idempotency:** `{key.as_string()}`\n\n---\n"
            + (brief[:4000] if brief else (item.description or "")[:2000])
        )
        result = await self.open_pull_request(
            repository_id=repository_id,
            branch=branch,
            base_branch=None,
            title=pr_title,
            body=pr_body,
            files=default_files,
            idempotency_key=key.as_string(),
        )
        if result.ok:
            item.pr_url = result.data.get("pr_url")
            item.pr_number = result.data.get("pr_number")
            item.pr_repository_id = repository_id
            meta = dict(item.connector_meta or {})
            meta["github"] = {
                "branch": result.data.get("branch"),
                "base_sha": result.data.get("base_sha"),
                "idempotency_key": key.as_string(),
                "opened_at": datetime.now(timezone.utc).isoformat(),
            }
            item.connector_meta = meta
            if item.state in ("queued", "in_progress"):
                item.state = "in_review"
            item.updated_at = datetime.now()
            self.db.commit()
            self.db.refresh(item)
        return result

"""GitHub REST API client for org/repo discovery."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import aiohttp

from app.core.logger import logger

GITHUB_API = "https://api.github.com"
PERSONAL_ORG_KEY = "_personal"


class GitHubApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


class GitHubClient:
    def __init__(self, token: str):
        self.token = token.strip()
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{GITHUB_API}{path}"
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method,
                url,
                headers=self._headers,
                params=params,
                json=json_body,
            ) as resp:
                if resp.status == 401:
                    raise GitHubApiError(401, "Invalid or expired GitHub token")
                if resp.status == 403:
                    detail = await resp.text()
                    if "rate limit" in detail.lower():
                        raise GitHubApiError(403, "GitHub API rate limit exceeded")
                    raise GitHubApiError(403, "GitHub token lacks required permissions")
                if resp.status == 404:
                    raise GitHubApiError(404, "GitHub resource not found")
                if resp.status == 422:
                    detail = await resp.text()
                    raise GitHubApiError(422, detail[:800] or "Unprocessable entity")
                if resp.status >= 400:
                    detail = await resp.text()
                    raise GitHubApiError(resp.status, detail[:500] or resp.reason)

                if resp.status == 204:
                    return None
                return await resp.json()

    async def _paginate(self, path: str, params: Optional[Dict[str, Any]] = None) -> List[Any]:
        params = dict(params or {})
        params.setdefault("per_page", 100)
        page = 1
        items: List[Any] = []
        while True:
            params["page"] = page
            batch = await self._request("GET", path, params=params)
            if not batch:
                break
            items.extend(batch)
            if len(batch) < params["per_page"]:
                break
            page += 1
            if page > 50:
                logger.warning(f"GitHub pagination capped at 50 pages for {path}")
                break
        return items

    async def validate_token(self) -> Dict[str, Any]:
        user = await self._request("GET", "/user")
        scopes_header = ""
        # Scopes returned on some responses via aiohttp - fetch from rate_limit endpoint metadata
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{GITHUB_API}/rate_limit", headers=self._headers
                ) as resp:
                    scopes_header = resp.headers.get("X-OAuth-Scopes", "")
        except Exception:
            pass

        scopes = [s.strip() for s in scopes_header.split(",") if s.strip()]
        return {
            "login": user.get("login"),
            "name": user.get("name"),
            "avatar_url": user.get("avatar_url"),
            "scopes": scopes,
        }

    async def list_orgs(self) -> List[Dict[str, Any]]:
        orgs = await self._paginate("/user/orgs")
        return [
            {
                "login": o.get("login"),
                "description": o.get("description"),
                "avatar_url": o.get("avatar_url"),
            }
            for o in orgs
        ]

    def _normalize_repo(self, repo: Dict[str, Any], org_key: str) -> Dict[str, Any]:
        owner = (repo.get("owner") or {}).get("login") or ""
        name = repo.get("name") or ""
        return {
            "id": repo.get("id"),
            "owner": owner,
            "name": name,
            "full_name": repo.get("full_name") or f"{owner}/{name}",
            "org": org_key,
            "default_branch": repo.get("default_branch") or "main",
            "private": bool(repo.get("private")),
            "html_url": repo.get("html_url"),
            "clone_url": repo.get("clone_url"),
            "description": repo.get("description"),
            "language": repo.get("language"),
            "updated_at": repo.get("updated_at"),
        }

    async def list_org_repos(self, org: str) -> List[Dict[str, Any]]:
        repos = await self._paginate(
            f"/orgs/{org}/repos",
            params={"type": "all", "sort": "updated", "direction": "desc"},
        )
        return [self._normalize_repo(r, org) for r in repos]

    async def list_personal_repos(self) -> List[Dict[str, Any]]:
        repos = await self._paginate(
            "/user/repos",
            params={
                "affiliation": "owner",
                "sort": "updated",
                "direction": "desc",
            },
        )
        return [self._normalize_repo(r, PERSONAL_ORG_KEY) for r in repos]

    async def discover_repos_for_orgs(
        self,
        org_logins: List[str],
        include_personal: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return repo groups for selected orgs (+ optional personal namespace)."""
        groups: List[Dict[str, Any]] = []

        if include_personal:
            personal = await self.list_personal_repos()
            groups.append(
                {
                    "org": PERSONAL_ORG_KEY,
                    "org_display_name": "Personal",
                    "repos": personal,
                }
            )

        for org in org_logins:
            if org == PERSONAL_ORG_KEY:
                continue
            try:
                repos = await self.list_org_repos(org)
                groups.append(
                    {
                        "org": org,
                        "org_display_name": org,
                        "repos": repos,
                    }
                )
            except GitHubApiError as e:
                logger.warning(f"Could not list repos for org {org}: {e.message}")
                groups.append(
                    {
                        "org": org,
                        "org_display_name": org,
                        "repos": [],
                        "error": e.message,
                    }
                )

        return groups

    async def get_repo(self, owner: str, name: str) -> Dict[str, Any]:
        repo = await self._request("GET", f"/repos/{owner}/{name}")
        org_key = owner if repo.get("owner", {}).get("type") == "Organization" else PERSONAL_ORG_KEY
        return self._normalize_repo(repo, org_key)

    async def get_ref_sha(self, owner: str, repo: str, ref: str) -> str:
        """Resolve branch/tag ref to commit SHA. ``ref`` like ``heads/main``."""
        data = await self._request("GET", f"/repos/{owner}/{repo}/git/ref/{ref}")
        obj = data.get("object") or {}
        sha = obj.get("sha")
        if not sha:
            raise GitHubApiError(404, f"No SHA for ref {ref}")
        return sha

    async def create_branch(
        self, owner: str, repo: str, branch: str, from_sha: str
    ) -> None:
        try:
            await self._request(
                "POST",
                f"/repos/{owner}/{repo}/git/refs",
                json_body={"ref": f"refs/heads/{branch}", "sha": from_sha},
            )
        except GitHubApiError as e:
            if e.status == 422 and "already exists" in (e.message or "").lower():
                # Update existing branch tip
                await self._request(
                    "PATCH",
                    f"/repos/{owner}/{repo}/git/refs/heads/{branch}",
                    json_body={"sha": from_sha, "force": True},
                )
                return
            raise

    async def put_file(
        self,
        owner: str,
        repo: str,
        path: str,
        content: str,
        message: str,
        branch: str,
        *,
        sha: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create or update a single file via Contents API (UTF-8 text)."""
        import base64

        body: Dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        return await self._request(
            "PUT",
            f"/repos/{owner}/{repo}/contents/{path.lstrip('/')}",
            json_body=body,
        )

    async def get_file_sha(
        self, owner: str, repo: str, path: str, ref: str
    ) -> Optional[str]:
        try:
            data = await self._request(
                "GET",
                f"/repos/{owner}/{repo}/contents/{path.lstrip('/')}",
                params={"ref": ref},
            )
            if isinstance(data, dict):
                return data.get("sha")
        except GitHubApiError as e:
            if e.status == 404:
                return None
            raise
        return None

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> Dict[str, Any]:
        return await self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json_body={
                "title": title,
                "body": body,
                "head": head,
                "base": base,
            },
        )

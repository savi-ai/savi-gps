"""Optional export of Savi wiki markdown into the linked GitHub repo as a PR.

Gated by tenant setting ``wiki_github_export_enabled``. Files land under
``WIKI_GITHUB_EXPORT_PATH`` so subsequent indexes skip regen when only that
folder changed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.database import ApplicationRepository, Repository
from app.core.logger import logger
from app.services.intelligence.analysis_storage import WIKI_MD_NAME
from app.services.intelligence.github_client import GitHubClient
from app.services.intelligence.github_credential_service import GitHubCredentialService
from app.services.intelligence.wiki_git_refresh import (
    wiki_app_export_path_prefix,
    wiki_export_path_prefix,
)
from app.services.tenant_config_service import TenantConfigService


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


class WikiGitHubExportService:
    def __init__(self, db: Session):
        self.db = db

    def is_enabled_for_tenant(self, tenant_id: str) -> bool:
        llm = TenantConfigService(self.db).get_llm_settings(tenant_id)
        return bool(llm.get("wiki_github_export_enabled"))

    async def maybe_export_after_wiki(
        self,
        repository: Repository,
        *,
        analysis_dir: Path,
        wiki_md: Optional[str] = None,
        sections_md: Optional[Dict[str, str]] = None,
        index_run_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.is_enabled_for_tenant(repository.tenant_id):
            return None
        try:
            return await self.export_wiki_pr(
                repository,
                analysis_dir=analysis_dir,
                wiki_md=wiki_md,
                sections_md=sections_md,
                index_run_id=index_run_id,
            )
        except Exception as e:
            logger.warning(
                "Wiki GitHub export failed for %s (non-fatal): %s",
                repository.id,
                e,
            )
            return {"ok": False, "error": str(e)[:500]}

    async def export_wiki_pr(
        self,
        repository: Repository,
        *,
        analysis_dir: Path,
        wiki_md: Optional[str] = None,
        sections_md: Optional[Dict[str, str]] = None,
        index_run_id: Optional[str] = None,
        export_root: Optional[str] = None,
        pr_title_prefix: str = "Savi GPS wiki update",
        commit_msg_prefix: str = "docs(savi-wiki): update wiki from Savi GPS",
        body_kind: str = "repository",
    ) -> Dict[str, Any]:
        owner_repo = _split_owner_repo(repository)
        if not owner_repo:
            raise ValueError("Repository is missing GitHub owner/name for export")
        owner, repo_name = owner_repo

        if not repository.github_credential_id:
            raise ValueError("Repository has no GitHub credential for export")

        cred_svc = GitHubCredentialService(self.db)
        cred = cred_svc.get_credential(
            repository.tenant_id, repository.github_credential_id
        )
        if not cred:
            raise ValueError("GitHub credential not found or inactive")
        token = cred_svc.get_token(cred)
        if not token:
            raise ValueError("Could not decrypt GitHub token")

        md_path = Path(analysis_dir) / WIKI_MD_NAME
        content = wiki_md
        if content is None and md_path.is_file():
            content = md_path.read_text(encoding="utf-8")
        if not content or not content.strip():
            raise ValueError("No wiki markdown available to export")

        root = (export_root or wiki_export_path_prefix()).strip().strip("/")
        files: List[Tuple[str, str]] = [
            (f"{root}/README.md", content),
        ]
        for slug, body in (sections_md or {}).items():
            if body and str(body).strip():
                safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in slug)
                files.append((f"{root}/{safe}.md", str(body)))

        client = GitHubClient(token)
        base_branch = repository.default_branch or "main"
        base_sha = await client.get_ref_sha(owner, repo_name, f"heads/{base_branch}")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        short_run = (index_run_id or "manual")[:8]
        branch_prefix = "savi-app-wiki" if body_kind == "application" else "savi-wiki"
        branch = f"{branch_prefix}/{stamp}-{short_run}"

        await client.create_branch(owner, repo_name, branch, base_sha)

        commit_msg = f"{commit_msg_prefix} ({short_run})"
        for path, text in files:
            existing_sha = await client.get_file_sha(
                owner, repo_name, path, ref=branch
            )
            await client.put_file(
                owner,
                repo_name,
                path,
                text,
                commit_msg,
                branch,
                sha=existing_sha,
            )

        if body_kind == "application":
            body = (
                "Automated **application** wiki export from **Savi GPS**.\n\n"
                f"- Export path: `{root}/`\n"
                f"- Application wiki fan-out into this member repository\n"
                f"- Run id: `{index_run_id or 'n/a'}`\n\n"
                "Merging this PR only changes the application-wiki folder; Savi will "
                "**not** re-run per-repo wiki analysis for wiki-folder-only commits.\n"
            )
            title = f"{pr_title_prefix} ({repository.name})"
        else:
            body = (
                "Automated wiki export from **Savi GPS**.\n\n"
                f"- Export path: `{root}/`\n"
                f"- Index run: `{index_run_id or 'n/a'}`\n\n"
                "Merging this PR only changes the wiki folder; Savi will **not** "
                "re-run wiki analysis for wiki-folder-only commits.\n"
            )
            title = f"{pr_title_prefix} ({repository.name})"

        pr = await client.create_pull_request(
            owner,
            repo_name,
            title=title,
            body=body,
            head=branch,
            base=base_branch,
        )

        result = {
            "ok": True,
            "pr_url": pr.get("html_url"),
            "pr_number": pr.get("number"),
            "branch": branch,
            "export_path": root,
            "files": [p for p, _ in files],
            "repository_id": repository.id,
        }
        logger.info(
            "Opened wiki export PR for %s: %s",
            repository.github_full_name or repository.id,
            result.get("pr_url"),
        )
        return result

    async def maybe_export_application_wiki_to_members(
        self,
        *,
        tenant_id: str,
        application_id: str,
        application_name: str,
        analysis_dir: Path,
        wiki_md: Optional[str] = None,
        sections_md: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fan-out application wiki into each member repo when export is enabled."""
        if not self.is_enabled_for_tenant(tenant_id):
            return None

        rows = (
            self.db.query(ApplicationRepository, Repository)
            .join(Repository, ApplicationRepository.repository_id == Repository.id)
            .filter(ApplicationRepository.application_id == application_id)
            .all()
        )
        if not rows:
            return {"ok": True, "exports": [], "skipped": "no_members"}

        export_root = wiki_app_export_path_prefix()
        exports: List[Dict[str, Any]] = []
        for _, repo in rows:
            try:
                result = await self.export_wiki_pr(
                    repo,
                    analysis_dir=analysis_dir,
                    wiki_md=wiki_md,
                    sections_md=sections_md,
                    index_run_id=f"app-{application_id[:8]}",
                    export_root=export_root,
                    pr_title_prefix=f"Savi GPS application wiki ({application_name})",
                    commit_msg_prefix="docs(savi-app-wiki): application wiki from Savi GPS",
                    body_kind="application",
                )
                exports.append(result)
            except Exception as e:
                logger.warning(
                    "Application wiki export failed for member %s: %s",
                    repo.id,
                    e,
                )
                exports.append({
                    "ok": False,
                    "repository_id": repo.id,
                    "error": str(e)[:500],
                })

        ok_count = sum(1 for e in exports if e.get("ok"))
        return {
            "ok": ok_count > 0,
            "export_path": export_root,
            "member_count": len(rows),
            "success_count": ok_count,
            "exports": exports,
        }

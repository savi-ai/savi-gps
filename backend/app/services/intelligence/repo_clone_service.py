"""Shallow clone repositories for indexing."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import Optional, Tuple
from urllib.parse import urlparse

from app.core.logger import logger


def normalize_github_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url


def inject_token_in_clone_url(url: str, token: str) -> str:
    """Inject PAT into https://github.com/... clone URL."""
    url = normalize_github_url(url)
    if url.startswith("git@"):
        # git@github.com:org/repo -> https with token
        match = re.match(r"git@github\.com:(.+)", url)
        if match:
            url = f"https://github.com/{match.group(1)}"
    parsed = urlparse(url)
    if "github.com" in parsed.netloc:
        return f"https://{token}@github.com{parsed.path}.git"
    return url if url.endswith(".git") else f"{url}.git"


class RepoCloneService:
    def shallow_clone(
        self,
        url: str,
        branch: str,
        token: Optional[str] = None,
    ) -> str:
        temp_dir = tempfile.mkdtemp(prefix="savi_repo_")
        clone_url = url
        if token:
            clone_url = inject_token_in_clone_url(url, token)

        cmd = [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            branch,
            clone_url,
            temp_dir,
        ]
        logger.info(f"Shallow cloning {normalize_github_url(url)} branch={branch}")
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.CalledProcessError as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            stderr = e.stderr or e.stdout or str(e)
            raise RuntimeError(f"Git clone failed: {stderr[:500]}") from e
        except subprocess.TimeoutExpired as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError("Git clone timed out after 300s") from e

        return temp_dir

    def ensure_clone(
        self,
        url: str,
        branch: str,
        token: Optional[str] = None,
        clone_path: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """Return (path, owned).

        If ``clone_path`` is a usable git work tree, reuse it (owned=False).
        Otherwise shallow-clone and return owned=True so the caller can cleanup.
        """
        if clone_path and self.is_git_work_tree(clone_path):
            return clone_path, False
        path = self.shallow_clone(url, branch, token=token)
        return path, True

    @staticmethod
    def is_git_work_tree(path: Optional[str]) -> bool:
        if not path or not os.path.isdir(path):
            return False
        git_dir = os.path.join(path, ".git")
        if not (os.path.isdir(git_dir) or os.path.isfile(git_dir)):
            return False
        try:
            result = subprocess.run(
                ["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            return result.returncode == 0 and (result.stdout or "").strip() == "true"
        except (OSError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def get_head_sha(path: str) -> Optional[str]:
        from app.services.intelligence.wiki_git_refresh import get_repo_head

        return get_repo_head(path)

    @staticmethod
    def cleanup(path: str) -> None:
        if path and os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

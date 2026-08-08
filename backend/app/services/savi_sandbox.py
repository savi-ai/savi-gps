"""Ephemeral workspace for Savi execution (ADR 0008 thin slice)."""
from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from app.core.logger import logger


@dataclass
class SaviSandbox:
    root: Path
    repository_id: Optional[str] = None
    cloned: bool = False

    def cleanup(self) -> None:
        try:
            shutil.rmtree(self.root, ignore_errors=True)
        except Exception as e:
            logger.warning("Sandbox cleanup failed for %s: %s", self.root, e)


@contextmanager
def ephemeral_sandbox(prefix: str = "savi_job_") -> Iterator[SaviSandbox]:
    """Create a throwaway directory; always destroyed on exit."""
    temp = Path(tempfile.mkdtemp(prefix=prefix))
    box = SaviSandbox(root=temp)
    try:
        yield box
    finally:
        box.cleanup()


def write_files(sandbox: SaviSandbox, files: list) -> list:
    """Write [{path, content}] under sandbox.root; return written relative paths."""
    written = []
    for f in files or []:
        rel = (f.get("path") or "").lstrip("/")
        if not rel or f.get("content") is None:
            continue
        dest = sandbox.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(str(f["content"]), encoding="utf-8")
        written.append(rel)
    return written
